"""
Central de operação dos Reels: fila com estados, controle (pausar/retomar/reagendar/cancelar/horários),
limites de produção, recuperação depois de queda, registro de atividades, controle de qualidade (nota 0-100),
aprendizado (testes A/B de abertura) e o PAINEL.md.

Tudo é guardado no próprio repositório (pasta reels/), então sobrevive a qualquer reinício do robô.
"""
import json
import re
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from util import RAIZ, carregar_config, configurar_log

log = configurar_log()
FUSO = ZoneInfo("America/Sao_Paulo")
PASTA = RAIZ / "reels"
CONTROLE = PASTA / "controle.json"
ATIVIDADES = PASTA / "atividades.jsonl"
TEMAS_DB = PASTA / "temas.json"
USO = PASTA / "uso.json"

# Estados da fila
EM_PRODUCAO, EM_REVISAO, AGUARDANDO, PUBLICANDO, PUBLICADO, FALHA, CANCELADO, QUARENTENA = (
    "em_producao", "em_revisao", "aguardando", "publicando", "publicado", "falha", "cancelado", "quarentena")
NOMES = {EM_PRODUCAO: "🛠️ Em produção", EM_REVISAO: "🔎 Em revisão", AGUARDANDO: "⏳ Aguardando publicação",
         PUBLICANDO: "📤 Publicando", PUBLICADO: "✅ Publicado", FALHA: "❌ Falha", CANCELADO: "🚫 Cancelado",
         QUARENTENA: "🧪 Quarentena"}
ANTIGOS = {"pronto": AGUARDANDO, "erro": FALHA}
NOTA_MINIMA = 90

# Estilos de abertura testados (uma variável por vez: só a abertura muda entre os vídeos)
ABERTURAS = {
    "pergunta": "Comece com uma PERGUNTA intrigante e específica (nada de \"Você sabia que\").",
    "afirmacao": "Comece com uma AFIRMAÇÃO chocante, curta e direta, como uma manchete.",
    "historia": "Comece NO MEIO de uma cena, como uma história (ex.: \"Em 1932, um exército inteiro...\").",
    "desafio": "Comece com um DESAFIO ao espectador (ex.: \"Aposto que você não sabe...\").",
    "numero": "Comece com um NÚMERO impressionante do tema, dito por extenso.",
}


def agora():
    return datetime.now(FUSO)


def _ler(arq, padrao):
    try:
        return json.loads(arq.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return padrao


def _gravar(arq, dados):
    PASTA.mkdir(exist_ok=True)
    arq.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")


# =================================================================== registro de atividades
def atividade(tipo, texto, reel=None, erro=False):
    PASTA.mkdir(exist_ok=True)
    linha = {"quando": agora().isoformat(timespec="seconds"), "tipo": tipo, "texto": texto[:400],
             "reel": reel, "erro": erro}
    with open(ATIVIDADES, "a", encoding="utf-8") as f:
        f.write(json.dumps(linha, ensure_ascii=False) + "\n")
    # mantém só as últimas 600 linhas
    linhas = ATIVIDADES.read_text(encoding="utf-8").splitlines()
    if len(linhas) > 600:
        ATIVIDADES.write_text("\n".join(linhas[-600:]) + "\n", encoding="utf-8")


def atividades(n=40, so_erros=False):
    if not ATIVIDADES.exists():
        return []
    itens = [json.loads(l) for l in ATIVIDADES.read_text(encoding="utf-8").splitlines() if l.strip()]
    if so_erros:
        itens = [i for i in itens if i.get("erro")]
    return itens[-n:][::-1]


# =================================================================== controle
def controle():
    c = _ler(CONTROLE, {})
    c.setdefault("pausado", False)
    c.setdefault("limite_reels_dia", 4)            # tentativas de produção por dia (protege a cota grátis)
    c.setdefault("limite_chamadas_ia_dia", 160)    # pedidos ao Gemini por dia
    return c


def salvar_controle(c):
    _gravar(CONTROLE, c)


def horarios():
    c = controle()
    return c.get("horarios") or carregar_config().get("reels", {}).get("horarios") or ["12:30", "19:30"]


def pausado():
    return bool(controle().get("pausado"))


# =================================================================== limites e uso
def uso_hoje():
    u = _ler(USO, {})
    return u.get(agora().date().isoformat(), {"reels": 0, "chamadas_ia": 0})


def somar_uso(reels=0, chamadas=0):
    u = _ler(USO, {})
    dia = agora().date().isoformat()
    d = u.setdefault(dia, {"reels": 0, "chamadas_ia": 0})
    d["reels"] += reels
    d["chamadas_ia"] += chamadas
    _gravar(USO, dict(sorted(u.items())[-60:]))


def pode_produzir():
    c, u = controle(), uso_hoje()
    if c["pausado"]:
        return False, "automação pausada no painel"
    if u["reels"] >= c["limite_reels_dia"]:
        return False, f"limite de {c['limite_reels_dia']} produções por dia atingido"
    if u["chamadas_ia"] >= c["limite_chamadas_ia_dia"]:
        return False, f"limite de {c['limite_chamadas_ia_dia']} pedidos à IA por dia atingido"
    return True, ""


# =================================================================== fila
def normalizar(reg):
    """Converte estados antigos e completa campos (registro de versões anteriores continua valendo)."""
    for r in reg:
        r["status"] = ANTIGOS.get(r.get("status"), r.get("status"))
        r.setdefault("erros", [])
        r.setdefault("tentativas", 0)
        r.setdefault("historico", [])
    return reg


def mudar(r, status, motivo=""):
    if r.get("status") != status:
        r.setdefault("historico", []).append({"quando": agora().isoformat(timespec="minutes"), "de": r.get("status"),
                                              "para": status, "motivo": motivo[:200]})
        r["status"] = status


def recuperar(reg, proximos_horarios):
    """Depois de uma queda: produção interrompida vira falha; horário perdido é reprogramado sem duplicar."""
    mudou = False
    for r in reg:
        criado = datetime.fromisoformat(r.get("criado") or agora().isoformat())
        if r["status"] in (EM_PRODUCAO, EM_REVISAO) and agora() - criado > timedelta(hours=3):
            mudar(r, FALHA, "produção interrompida (o robô caiu no meio)")
            atividade("recuperação", f"Produção de '{r.get('tema')}' foi interrompida; marcada como falha.", r["id"], True)
            mudou = True
    perdidos = sorted([r for r in reg if r["status"] == AGUARDANDO and
                       datetime.fromisoformat(r["horario"]) < agora() - timedelta(hours=5)], key=lambda r: r["horario"])
    for r in perdidos:
        antigo = r["horario"]
        r["horario"] = proximos_horarios(reg, 1)[0]
        atividade("recuperação", f"'{r['titulo']}' perdeu o horário {antigo[:16]}; reprogramado para {r['horario'][:16]}.", r["id"])
        mudou = True
    return mudou


# =================================================================== controle de qualidade
def nota_qualidade(r, item, pasta, cenas, audios, mp4, capa, legenda, problemas_video):
    """Inspeção antes de liberar. Devolve (nota 0-100, lista de pontos perdidos)."""
    pontos, perdas = 0, []

    def item_(ok, valor, falha):
        nonlocal pontos
        if ok:
            pontos += valor
        else:
            perdas.append(f"-{valor}: {falha}")

    rev = (r.get("revisao") or {}).get("nota") or 0
    try:
        rev = float(rev)
    except (TypeError, ValueError):
        rev = 0
    pontos += round(25 * min(rev, 10) / 10)
    if rev < 10:
        perdas.append(f"-{25 - round(25 * min(rev, 10) / 10)}: revisão do roteiro deu {rev}/10")
    item_(bool(item.get("fontes")), 10, "sem fonte registrada")
    sem_svg = sum(1 for c in cenas if not Path(c).with_suffix(".svg").exists())
    item_(sem_svg == 0, 15, f"{sem_svg} desenho(s) não foram gerados")
    # narração completa: ritmo plausível em todas as falas (nem cortada, nem travada)
    ruins = 0
    for c, a in zip(r["cenas"], audios):
        try:
            from util import duracao
            ritmo = len(c["narracao"].split()) / max(duracao(a), 0.1)
            ruins += not (1.6 <= ritmo <= 4.8)
        except Exception:  # noqa: BLE001
            ruins += 1
    item_(ruins == 0, 10, f"{ruins} fala(s) com narração suspeita (cortada ou travada)")
    sem_tempo = sum(1 for a in audios if not Path(a).with_suffix(".palavras.json").exists())
    item_(sem_tempo == 0, 5, f"{sem_tempo} fala(s) sem tempo exato das palavras (legenda estimada)")
    item_(not problemas_video, 20, "; ".join(problemas_video) or "")
    d = item.get("duracao") or 0
    item_(28 <= d <= 62, 5, f"duração de {d:.0f}s (ideal 30 a 60s)")
    item_(Path(capa).exists() and len((r.get("texto_capa") or "").split()) <= 5, 5, "capa ausente ou com texto longo")
    tags = len(re.findall(r"#\w", legenda))
    item_("?" in legenda and "@" in legenda and 3 <= tags <= 10, 5, "legenda sem pergunta, sem @ ou hashtags fora do padrão")
    return min(100, pontos), perdas


# =================================================================== aprendizado
def escolher_abertura(reg):
    """Teste A/B: alterna os estilos de abertura; com amostra suficiente, usa mais o vencedor (sem abandonar os outros)."""
    apr = _ler(PASTA / "aprendizados.json", {})
    venc = (apr.get("teste_abertura") or {}).get("vencedor")
    usados = {k: 0 for k in ABERTURAS}
    for r in reg[-30:]:
        k = (r.get("teste") or {}).get("abertura")
        if k in usados:
            usados[k] += 1
    if venc and venc in ABERTURAS and sum(usados.values()) % 5 in (0, 2, 4):   # ~60% vencedor, 40% exploração
        return venc
    return min(usados, key=lambda k: (usados[k], list(ABERTURAS).index(k)))


def analisar_testes(publicados):
    """Compara estilos de abertura só quando cada um tem 5+ vídeos com resultado (sem conclusões de amostra pequena)."""
    grupos = {}
    for r in publicados:
        k = (r.get("teste") or {}).get("abertura")
        if k and r.get("nota"):
            grupos.setdefault(k, []).append(r["nota"])
    medias = {k: round(sum(v) / len(v), 1) for k, v in grupos.items()}
    prontos = {k: m for k, m in medias.items() if len(grupos[k]) >= 5}
    res = {"medias": medias, "amostras": {k: len(v) for k, v in grupos.items()}, "vencedor": None}
    if len(prontos) >= 2:
        ordem = sorted(prontos, key=prontos.get, reverse=True)
        if prontos[ordem[0]] >= 1.15 * prontos[ordem[1]]:
            res["vencedor"] = ordem[0]
    return res


def registrar_temas(opcoes, escolhidos):
    db = _ler(TEMAS_DB, [])
    vistos = {t["tema"] for t in db}
    for o in opcoes:
        if o.get("tema") and o["tema"] not in vistos:
            db.append({"tema": o["tema"], "categoria": o.get("categoria"), "pontuacao": o.get("pontuacao"),
                       "criterios": o.get("criterios"), "visto": agora().isoformat(timespec="minutes"),
                       "status": "escolhido" if o in escolhidos else "na reserva"})
    _gravar(TEMAS_DB, db[-1500:])


def marcar_tema(tema, status, motivo=""):
    db = _ler(TEMAS_DB, [])
    for t in db:
        if t["tema"] == tema:
            t["status"], t["motivo"] = status, motivo[:200]
    _gravar(TEMAS_DB, db)


def temas_usados():
    return [t["tema"] for t in _ler(TEMAS_DB, []) if t.get("status") in ("publicado", "produzido", "escolhido")]


# =================================================================== painel
def _semana(reg):
    """Calendário de 7 dias (de ontem até daqui a 5 dias), com todos os Reels de cada dia e seus horários."""
    hoje = agora().date()
    dias = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]
    linhas = ["| Dia | Reels (horário · status · título) |", "|---|---|"]
    for k in range(-1, 6):
        d = hoje + timedelta(days=k)
        do_dia = sorted([r for r in reg if (r.get("horario") or "").startswith(d.isoformat()) and r["status"] != CANCELADO],
                        key=lambda r: r["horario"])
        cel = []
        for r in do_dia:
            icone = NOMES.get(r["status"], r["status"]).split()[0]
            tit = r["titulo"][:40]
            tit = f"[{tit}]({r['link']})" if r.get("link") else f"{tit} `{r['id']}`"
            cel.append(f"{r['horario'][11:16]} {icone} {tit}")
        livres = [h for h in horarios() if k >= 0 and not any(r["horario"][11:16] == h for r in do_dia)]
        cel += [f"{h} — livre" for h in livres]
        linhas.append(f"| {dias[d.weekday()]} {d:%d/%m}{' (hoje)' if k == 0 else ''} | " + (" · ".join(cel) or "—") + " |")
    return linhas


def painel(reg, seguidores_hist=None):
    c, u = controle(), uso_hoje()
    pub = [r for r in reg if r["status"] == PUBLICADO]
    views = sum((r.get("resultados") or {}).get("views") or 0 for r in pub)
    seg = seguidores_hist or _ler(PASTA / "seguidores.json", [])
    cresc = ""
    if len(seg) >= 2:
        sem = [s for s in seg if s["data"] >= (agora().date() - timedelta(days=7)).isoformat()]
        if sem:
            cresc = f" ({sem[-1]['seguidores'] - sem[0]['seguidores']:+d} em 7 dias)"
    prox = sorted([r for r in reg if r["status"] == AGUARDANDO], key=lambda r: r["horario"])
    L = [f"# 🎛️ Painel do Bino Explica — Reels", "",
         f"Atualizado em {agora():%d/%m/%Y às %H:%M} (horário de Brasília) · "
         f"automação **{'⏸️ PAUSADA' if c['pausado'] else '▶️ ATIVA'}** · horários {', '.join(horarios())}", "",
         "## Visão geral", "",
         "| Produzidos | Publicados | Na fila | Falhas | Quarentena | Views (com estatísticas) | Seguidores |",
         "|---|---|---|---|---|---|---|",
         f"| {sum(r['status'] not in (EM_PRODUCAO, CANCELADO) for r in reg)} | {len(pub)} | {len(prox)} | "
         f"{sum(r['status'] == FALHA for r in reg)} | {sum(r['status'] == QUARENTENA for r in reg)} | {views} | "
         f"{seg[-1]['seguidores'] if seg else '–'}{cresc} |", "",
         "**Próximas publicações:** " + (", ".join(f"{r['horario'][8:10]}/{r['horario'][5:7]} {r['horario'][11:16]} — {r['titulo']}"
                                                    for r in prox[:4]) or "nenhuma (a produção roda às 08:00)"), "",
         "## 📅 Calendário da semana", ""] + _semana(reg) + ["", "## 🛠️ Produção", ""]
    prod = [r for r in reg if r["status"] in (EM_PRODUCAO, EM_REVISAO, AGUARDANDO, QUARENTENA)]
    if prod:
        L += ["| Reel | Status | Qualidade | Abertura testada | Horário | Arquivos |", "|---|---|---|---|---|---|"]
        for r in sorted(prod, key=lambda x: x.get("horario") or ""):
            L.append(f"| {r['titulo']} `{r['id']}` | {NOMES.get(r['status'], r['status'])} | {r.get('qualidade', '–')} | "
                     f"{(r.get('teste') or {}).get('abertura', '–')} | {(r.get('horario') or '')[:16].replace('T', ' ')} | "
                     f"{'Releases: ' + r['release'] if r.get('release') else '–'} |")
        quar = [r for r in prod if r["status"] == QUARENTENA]
        for r in quar:
            L.append(f"\n> 🧪 **{r['titulo']}** em quarentena (nota {r.get('qualidade')}): " + "; ".join(r.get("perdas_qa", [])[:4]))
    else:
        L.append("Nada em produção agora.")
    sb = [r for r in prod if r.get("storyboard")][:2]
    for r in sb:
        L += ["", f"<details><summary>🎬 Storyboard — {r['titulo']}</summary>", "",
              "| Cena | Narração | Ilustração | Movimento | Destaque | Efeito |", "|---|---|---|---|---|---|"]
        for k, s in enumerate(r["storyboard"]):
            L.append(f"| {k + 1} | {s.get('narracao', '')[:90]} | {s.get('visual', '')[:60]} | {s.get('movimento', '')} | "
                     f"{', '.join(s.get('destaques', [])[:2])} | {s.get('efeito', '')} |")
        L += ["", "</details>"]
    apr = _ler(PASTA / "aprendizados.json", {})
    L += ["", "## 🧠 Inteligência", ""]
    if apr.get("melhores"):
        L += [f"- **Temas mais eficientes:** {'; '.join(apr['melhores'][:3])}",
              f"- **Categorias fortes:** {', '.join(apr.get('categorias_fortes', []))}",
              f"- **Desempenho por horário (views médias):** {apr.get('views_por_horario', {})}",
              f"- **Retenção média:** {apr.get('retencao_media', '–')}"]
    else:
        L.append("- Ainda sem estatísticas suficientes (precisa da permissão de estatísticas e de alguns Reels publicados).")
    t = apr.get("teste_abertura") or {}
    L.append(f"- **Teste A/B de aberturas:** amostras {t.get('amostras', {})} · médias {t.get('medias', {})} · "
             f"vencedor: {t.get('vencedor') or 'ainda sem conclusão (mínimo 5 vídeos por estilo)'}")
    for rec in apr.get("recomendacoes", [])[:5]:
        L.append(f"- 💡 {rec}")
    L += ["", "## 🎚️ Controle", "",
          f"- Limites por dia: **{c['limite_reels_dia']}** produções · **{c['limite_chamadas_ia_dia']}** pedidos à IA "
          f"(hoje: {u['reels']} produções, {u['chamadas_ia']} pedidos) · custo: **R$ 0** (tudo grátis)",
          "- Comandos: aba **Actions → Reels Instagram (automático) → Run workflow** e escolha a ação:",
          "  - `pausar` / `retomar` — para ou volta toda a automação",
          "  - `reagendar` — informe o **id** do Reel e o novo **quando** (ex.: `05/11 19:30`)",
          "  - `cancelar` — informe o **id** (não será publicado)",
          "  - `horarios` — informe em **quando** os horários separados por vírgula (ex.: `12:30,19:30`)", "",
          "## ❗ Histórico de erros", ""]
    erros = atividades(10, so_erros=True)
    L += [f"- {e['quando'][:16].replace('T', ' ')} · {e['tipo']}: {e['texto']}" for e in erros] or ["- Nenhum erro registrado."]
    L += ["", "## 📝 Registro de atividades", ""]
    L += [f"- {a['quando'][:16].replace('T', ' ')} · {a['tipo']}: {a['texto']}" for a in atividades(25)] or ["- Sem atividades ainda."]
    (PASTA / "PAINEL.md").write_text("\n".join(L), encoding="utf-8")


# =================================================================== comandos do painel
def comando(acao, reg, ident="", quando="", proximos_horarios=None):
    c = controle()
    if acao == "pausar":
        c["pausado"] = True
        salvar_controle(c)
        atividade("controle", "Automação pausada.")
        return "Automação pausada: nada será produzido nem publicado até retomar."
    if acao == "retomar":
        c["pausado"] = False
        salvar_controle(c)
        atividade("controle", "Automação retomada.")
        return "Automação retomada."
    if acao == "horarios":
        hs = [h.strip() for h in quando.split(",") if re.fullmatch(r"\d{1,2}:\d{2}", h.strip())]
        if not hs:
            raise ValueError("informe os horários em 'quando', ex.: 12:30,19:30")
        c["horarios"] = [f"{int(h.split(':')[0]):02d}:{h.split(':')[1]}" for h in hs]
        salvar_controle(c)
        atividade("controle", f"Horários alterados para {', '.join(c['horarios'])}.")
        return f"Novos horários: {', '.join(c['horarios'])} (valem para os próximos Reels)."
    r = next((x for x in reg if x["id"] == ident.strip()), None)
    if not r:
        raise ValueError(f"não achei o Reel com id '{ident}' (veja os ids no PAINEL.md)")
    if acao == "cancelar":
        if r["status"] == PUBLICADO:
            raise ValueError("esse Reel já foi publicado; apague direto no Instagram se quiser")
        mudar(r, CANCELADO, "cancelado no painel")
        atividade("controle", f"'{r['titulo']}' cancelado.", r["id"])
        return f"'{r['titulo']}' cancelado."
    if acao == "reagendar":
        m = re.fullmatch(r"\s*(\d{1,2})/(\d{1,2})(?:/(\d{4}))?\s+(\d{1,2}):(\d{2})\s*", quando)
        if not m:
            raise ValueError("informe 'quando' como dd/mm HH:MM, ex.: 05/11 19:30")
        d, mes, ano, h, mi = m.groups()
        novo = datetime(int(ano or agora().year), int(mes), int(d), int(h), int(mi), tzinfo=FUSO)
        if novo < agora():
            raise ValueError("a nova data já passou")
        if r["status"] in (PUBLICADO, PUBLICANDO):
            raise ValueError("esse Reel já foi ou está sendo publicado")
        r["horario"] = novo.isoformat(timespec="minutes")
        if r["status"] in (FALHA, CANCELADO, QUARENTENA):
            mudar(r, AGUARDANDO, "reagendado no painel")
            r["tentativas"] = 0
        atividade("controle", f"'{r['titulo']}' reagendado para {novo:%d/%m %H:%M}.", r["id"])
        return f"'{r['titulo']}' reagendado para {novo:%d/%m às %H:%M}."
    raise ValueError(f"ação desconhecida: {acao}")
