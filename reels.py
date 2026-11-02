"""
Operação automática de Reels do Bino Explica (Instagram), 100% grátis, rodando no GitHub Actions.

Módulos: pesquisador de assuntos e roteirista (aqui) · diretor de arte/ilustração (main_gratis) · animação e edição
(animacao) · narração (narracao) · qualidade, fila, aprendizado e painel (operacao) · Instagram (instagram_upload).

    python reels.py produzir [--quantos 2] [--tema "..."]   # 08:00  pesquisa → roteiro → storyboard → vídeo → QA
    python reels.py publicar                                # 12:30 e 19:30  publica o próximo Reel aprovado
    python reels.py analisar                                # 22:00  resultados, aprendizado e relatório semanal
    python reels.py auditoria                               # confere o que está conectado
    python reels.py pausar | retomar | reagendar --id X --quando "05/11 19:30" | cancelar --id X | horarios --quando "12:30,19:30"

Tudo fica em reels/ (registro.json, temas.json, aprendizados.json, atividades.jsonl, PAINEL.md).
Os vídeos aprovados ficam na aba Releases do GitHub (reel-<id>), com capa e legenda.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import ia_gemini as ia
import operacao as op
from util import RAIZ, carregar_config, configurar_log, duracao, slug

log = configurar_log()
FUSO = op.FUSO
PASTA = RAIZ / "reels"
REGISTRO = PASTA / "registro.json"
APRENDIZADOS = PASTA / "aprendizados.json"
VOZ = PASTA / "voz.json"
CATEGORIAS = ["curiosidades sobre animais", "corpo humano", "ciência e tecnologia", "psicologia", "história", "espaço",
              "mistérios", "fenômenos naturais", "conhecimentos gerais", "curiosidades inacreditáveis"]
CRITERIOS = ["curiosidade", "facilidade", "compartilhamento", "interesse_brasil", "ilustravel", "originalidade",
             "credibilidade"]
MOVIMENTOS = ["aproximar", "afastar", "panoramica", "impacto"]
EFEITOS = ["nenhum", "pop", "whoosh", "ding"]


def marca_instagram():
    """@ do perfil do Instagram (config.yaml → reels: marca)."""
    return carregar_config().get("reels", {}).get("marca") or "@binoteexplica"


def agora():
    return op.agora()


def ler_registro():
    if REGISTRO.exists():
        return op.normalizar(json.loads(REGISTRO.read_text(encoding="utf-8")))
    return []


def salvar_registro(reg):
    PASTA.mkdir(exist_ok=True)
    REGISTRO.write_text(json.dumps(reg, ensure_ascii=False, indent=2), encoding="utf-8")


def horarios():
    return op.horarios()


def proximos_horarios(reg, n):
    """Os próximos n horários livres, a partir de agora + 20 min."""
    ocupados = {r["horario"] for r in reg if r.get("horario") and
                r.get("status") in (op.AGUARDANDO, op.PUBLICANDO, op.PUBLICADO)}
    livres, dia, limite = [], agora().date(), agora() + timedelta(minutes=20)
    while len(livres) < n:
        for h in horarios():
            hh, mm = map(int, h.split(":"))
            quando = datetime(dia.year, dia.month, dia.day, hh, mm, tzinfo=FUSO)
            iso = quando.isoformat(timespec="minutes")
            if quando > limite and iso not in ocupados and len(livres) < n:
                livres.append(iso)
        dia += timedelta(days=1)
    return livres


def palavras_por_segundo():
    """Velocidade REAL da narração, medida nos últimos vídeos (para acertar a duração do roteiro)."""
    try:
        return max(2.0, min(3.6, json.loads(VOZ.read_text(encoding="utf-8"))["pps"]))
    except Exception:  # noqa: BLE001
        return 2.6


def medir_voz(cenas, audios):
    pal = sum(len(c["narracao"].split()) for c in cenas)
    seg = sum(duracao(a) for a in audios)
    if seg > 5:
        novo = pal / seg
        antigo = palavras_por_segundo() if VOZ.exists() else novo
        VOZ.write_text(json.dumps({"pps": round(0.7 * antigo + 0.3 * novo, 3)}), encoding="utf-8")


# =================================================================== 1. pesquisador de assuntos
def escolher_temas(reg, quantos, modelo):
    feitos = list(dict.fromkeys([r["tema"] for r in reg] + op.temas_usados()))[-120:]
    apr = json.loads(APRENDIZADOS.read_text(encoding="utf-8")) if APRENDIZADOS.exists() else {}
    cat_stats = apr.get("categorias") or {}
    dicas = ""
    if apr.get("melhores"):
        dicas = ("Desempenho real do perfil (guia, sem repetir temas): melhores temas "
                 f"{json.dumps(apr['melhores'][:5], ensure_ascii=False)}; categorias fortes {apr.get('categorias_fortes', [])}.")
    prompt = f"""Você é o pesquisador de pauta do perfil "Bino Explica" (Reels de curiosidades desenhadas à mão, Brasil).
Data de hoje: {agora():%d/%m/%Y}. Pesquise no Google oportunidades de conteúdo com alto potencial no Instagram
brasileiro nestas categorias: {", ".join(CATEGORIAS)}.
Só fatos bem documentados (universidades, instituições de pesquisa, publicações especializadas, órgãos oficiais,
enciclopédias, grandes veículos). Nada de pessoas vivas, tragédias recentes, política, saúde arriscada ou boatos.
Não copie roteiros de outros criadores. {dicas}
Não repita estes temas: {json.dumps(feitos, ensure_ascii=False)}.
Dê uma nota de 0 a 10 para cada critério: curiosidade, facilidade (de entender em 50s), compartilhamento,
interesse_brasil, ilustravel (dá um desenho simples e claro), originalidade, credibilidade (fontes fortes).
Responda SÓ um JSON: {{"temas":[{{"tema":"assunto específico em uma frase","categoria":"uma das categorias",
"porque":"por que viraliza, 1 frase","criterios":{{"curiosidade":0,"facilidade":0,"compartilhamento":0,
"interesse_brasil":0,"ilustravel":0,"originalidade":0,"credibilidade":0}},
"artigos":["1 a 3 títulos EXATOS de artigos da Wikipédia em português que comprovam o tema (ex.: \\"Vênus (planeta)\\")"]}}]}}
com 8 opções de categorias variadas."""
    try:
        texto, _ = ia.pesquisar(prompt, modelo)
        opcoes = ia.extrair_json(texto).get("temas", [])
    except Exception as e:  # noqa: BLE001  (busca do Google sem cota: a IA sugere e a Wikipédia confirma depois)
        log.warning(f"Pesquisa de pauta no Google indisponível ({e}); sugerindo temas sem busca.")
        opcoes = ia.gerar_json(prompt.replace("Pesquise no Google oportunidades", "Sugira oportunidades"), modelo).get("temas", [])
    for o in opcoes:                      # pontuação interna 0-100 (+ ajuste pelo aprendizado, com amostra mínima)
        c = o.get("criterios") or {}
        base = sum(min(10, max(0, float(c.get(k, 5) or 0))) for k in CRITERIOS) / (10 * len(CRITERIOS)) * 100
        st = cat_stats.get(o.get("categoria") or "", {})
        ajuste = 0
        if st.get("n", 0) >= 3 and cat_stats:
            media_geral = sum(v["media"] for v in cat_stats.values()) / len(cat_stats)
            ajuste = max(-8, min(8, (st["media"] - media_geral) / 2))
        o["pontuacao"] = round(min(100, max(0, base + ajuste)), 1)
    opcoes = [o for o in opcoes if o.get("tema") and o["tema"] not in feitos]
    opcoes.sort(key=lambda o: o["pontuacao"], reverse=True)
    escolhidos, cats = [], set()
    for o in opcoes:
        if o.get("categoria") not in cats and o["pontuacao"] >= 55:
            escolhidos.append(o)
            cats.add(o.get("categoria"))
    escolhidos = escolhidos[:quantos + 2]           # reservas, caso algum seja reprovado
    op.registrar_temas(opcoes, escolhidos)
    log.info("Pauta: " + " | ".join(f"{o['pontuacao']:.0f} {o['tema'][:50]}" for o in escolhidos))
    return escolhidos


def pesquisar_fatos(tema, modelo, artigos=None):
    prompt = f"""Pesquise no Google, em fontes confiáveis, fatos verificados sobre: {tema}.
Quero de 6 a 9 fatos curtos, precisos e surpreendentes (números, datas e nomes exatos como aparecem nas fontes).
Não inclua nada que você não encontrou nas fontes. Se um número varia entre fontes, diga "cerca de".
Responda SÓ JSON: {{"fatos":["..."],"mais_surpreendente":"o fato mais impressionante"}}"""
    try:
        texto, fontes = ia.pesquisar(prompt, modelo)
        dados = ia.extrair_json(texto)
        if fontes and dados.get("fatos"):
            return dados, fontes
        log.warning("A busca no Google não trouxe fontes; conferindo na Wikipédia.")
    except Exception as e:  # noqa: BLE001
        log.warning(f"Busca no Google indisponível ({e}); conferindo na Wikipédia.")
    textos, fontes = [], []
    for termo in (artigos or [])[:3] + ([] if artigos else [tema]):
        artigo, fonte = ia.wikipedia(str(termo))
        if artigo and fonte["url"] not in [f["url"] for f in fontes]:
            textos.append(f"=== {fonte['titulo']} ===\n{artigo}")
            fontes.append(fonte)
    if not textos:
        raise RuntimeError("não achei fonte confiável para este tema")
    artigo = "\n\n".join(textos)[:24000]
    titulo = " + ".join(f["titulo"] for f in fontes)
    log.info(f"Wikipédia: {titulo} ({len(artigo)} caracteres)")
    dados = ia.gerar_json(f"""Leia o(s) artigo(s) abaixo e extraia de 6 a 9 fatos curtos, precisos e surpreendentes que sirvam para
um vídeo sobre: {tema}.
Use SOMENTE o que está escrito nos artigos (números, datas e nomes exatos). Fatos relacionados ao assunto valem.
Diga também se os artigos comprovam a ideia principal do tema (pode ser juntando fatos, ex.: comparando datas).
Artigo ({titulo}):
{artigo}
Responda SÓ JSON: {{"fatos":["..."],"mais_surpreendente":"...","comprova_o_tema":true|false}}""", modelo)
    log.info(f"Fatos extraídos: {len(dados.get('fatos') or [])}; comprova o tema: {dados.get('comprova_o_tema')}")
    if dados.get("comprova_o_tema") is False:
        raise RuntimeError("as fontes não comprovam a ideia principal do tema")
    if len(dados.get("fatos") or []) < 4:
        raise RuntimeError("a fonte encontrada não tem fatos suficientes sobre o tema")
    return dados, fontes


# =================================================================== 2. roteirista + storyboard
def prompt_roteiro(tema, fatos, abertura, ganchos_recentes, correcoes="", alvo=(40, 54), n_cenas=6):
    import main_gratis as mg
    MARCA = marca_instagram()
    regras = mg.REGRAS_VIRAL.replace("@binoexplica", MARCA)
    pps = palavras_por_segundo()
    pmin, pmax = round(alvo[0] * pps), round(alvo[1] * pps)
    return f"""{regras}

Formato: vídeo vertical (Reels/TikTok) de {alvo[0]} a {alvo[1]} segundos. A voz fala {pps:.1f} palavras por segundo, então
escreva de {pmin} a {pmax} palavras no total, em EXATAMENTE {n_cenas} cenas. Frases curtas, sem introdução.
Use SOMENTE estes fatos pesquisados (não acrescente nenhum fato, número ou data que não esteja aqui):
{json.dumps(fatos, ensure_ascii=False)}
Estrutura obrigatória (storytelling de alta retenção):
- Cena 1 = GANCHO (até 2 s, até 10 palavras). {op.ABERTURAS[abertura]}
  PROIBIDO começar com "Você sabia" e proibido repetir estas aberturas recentes: {json.dumps(ganchos_recentes, ensure_ascii=False)}
- Cena 2 = CURIOSIDADE: crie a pergunta na cabeça de quem assiste.
- Cena 3 = DESENVOLVIMENTO: explique sem enrolar.
- Cena 4 = QUEBRA DE EXPECTATIVA: algo que ninguém espera.
- Cenas seguintes = mais um fato surpreendente{" (entre 20 e 30 segundos, uma frase curta pedindo para seguir o Bino)" if n_cenas > 6 else ""}.
- Penúltima cena = REVELAÇÃO: frase curta de suspense + o fato mais surpreendente.
- Última cena = ENCERRAMENTO: conclusão curta + pergunta natural para os comentários + "segue o Bino Explica".
{"Corrija estes problemas apontados pela revisão: " + correcoes if correcoes else ""}
STORYBOARD de cada cena:
"visual": a ilustração EM INGLÊS que EXPLICA a fala (rabisco de quadro branco, 1 a 3 bonequinhos de palito, uma ação clara).
"movimento": um de {MOVIMENTOS} ("impacto" só na revelação). "efeito": um de {EFEITOS} ("ding" só na revelação).
"destaques": 1 a 3 palavras EXATAS da narração (números, nomes, a palavra mais surpreendente).
"personagens": aparência fixa de cada personagem, em inglês. "legenda_tela": 2 a 4 palavras, funciona sem som.
Responda SÓ JSON:
{{"titulo":"curto, curioso e honesto","texto_capa":"2 a 4 palavras em MAIÚSCULAS, terminando em ? ou !",
"personagens":"...","surpresa":4,
"cenas":[{{"narracao":"...","legenda_tela":"...","visual":"...","movimento":"...","efeito":"...","destaques":["..."]}}],
"legenda":"legenda do post: gancho + 2 frases que contam um pouco mais + uma pergunta para os comentários + chamada para seguir o {MARCA}",
"legenda_tiktok":"legenda curta para o TikTok: gancho + pergunta para os comentários (sem hashtags)",
"hashtags":["5 a 8 hashtags ESPECÍFICAS do assunto, sem #, poucas genéricas"]}}"""


def revisar(r, fatos, modelo):
    texto = json.dumps({"titulo": r["titulo"], "capa": r.get("texto_capa"), "narracao": [c["narracao"] for c in r["cenas"]],
                        "ilustracoes": [c.get("visual", "") for c in r["cenas"]], "legenda": r.get("legenda")},
                       ensure_ascii=False)
    prompt = f"""Você é o revisor final antes de publicar um Reel. Fatos pesquisados (com fontes):
{json.dumps(fatos, ensure_ascii=False)}
Roteiro: {texto}
Reprove se: (1) algum fato, número ou data do roteiro NÃO está nos fatos pesquisados ou foi exagerado/distorcido;
(2) erro de português ou de ortografia; (3) título enganoso; (4) a 1ª frase não prende; (5) conteúdo impróprio,
pessoa viva, política ou saúde arriscada; (6) falta pergunta final para os comentários; (7) alguma ilustração não
corresponde à fala da cena.
Responda SÓ JSON: {{"aprovado": true|false, "problemas": "vazio se aprovado", "nota": 0-10}}"""
    return ia.gerar_json(prompt, modelo)


def criar_roteiro(tema, fatos, modelo, abertura, ganchos_recentes, alvo=(40, 54), n_cenas=6):
    obs = ""
    pps = palavras_por_segundo()
    for tentativa in range(3):
        log.info(f"Roteiro (tentativa {tentativa + 1}, abertura '{abertura}'): {tema}")
        r = ia.gerar_json(prompt_roteiro(tema, fatos, abertura, ganchos_recentes, obs, alvo, n_cenas), modelo)
        cenas = [c for c in r.get("cenas", []) if c.get("narracao")]
        if len(cenas) < n_cenas - 1:
            obs = f"o roteiro precisa ter exatamente {n_cenas} cenas com narração"
            continue
        r["cenas"] = cenas[:n_cenas + 1]
        palavras = sum(len(c["narracao"].split()) for c in r["cenas"])
        if not (alvo[0] - 6) * pps <= palavras <= (alvo[1] + 8) * pps:
            obs = f"o roteiro tem {palavras} palavras; precisa ter entre {round(alvo[0] * pps)} e {round(alvo[1] * pps)}"
            continue
        if re.match(r"\s*voc[eê] sabia", r["cenas"][0]["narracao"], re.I):
            obs = "a primeira frase não pode começar com 'Você sabia'"
            continue
        for k, c in enumerate(r["cenas"]):             # storyboard sempre válido
            if c.get("movimento") not in MOVIMENTOS:
                c["movimento"] = MOVIMENTOS[k % 3]
            if c.get("efeito") not in EFEITOS:
                c["efeito"] = "nenhum"
        rev = revisar(r, fatos, modelo)
        if rev.get("aprovado"):
            r["revisao"] = {"aprovado": True, "nota": rev.get("nota")}
            return r
        obs = rev.get("problemas", "")
        log.warning(f"Revisão reprovou: {obs}")
    return None


# =================================================================== 3. produção
def montar_legenda(r, fontes):
    tags = []
    for t in r.get("hashtags", []):
        t = re.sub(r"[^\wÀ-ÿ]", "", str(t))
        if t.lower() == "binoexplica":
            t = marca_instagram().lstrip("@")
        if t and t.lower() not in [x.lower() for x in tags]:
            tags.append(t)
    tags = tags[:8] or ["curiosidades", "vocesabia"]
    dominios = []
    for f in fontes:
        d = re.sub(r"^www\.", "", (f.get("titulo") or "").strip())
        if d and d not in dominios:
            dominios.append(d)
    texto = (r.get("legenda") or r["titulo"]).strip()
    marca = marca_instagram()
    texto = re.sub(r"@binoexplica\b", marca, texto, flags=re.I)
    texto = re.sub(r"(segue|siga)( o)? (o )?bino ?explica\b", lambda m: f"{m.group(1)} o {marca}", texto, flags=re.I)
    if marca.lower() not in texto.lower():
        texto += f"\n\nSegue o {marca} pra uma curiosidade nova todo dia!"
    if dominios:
        texto += "\n\nFontes: " + ", ".join(dominios[:4])
    texto += "\n\n" + " ".join("#" + t for t in tags)
    return texto[:2200]


def verificar_video(mp4):
    """Checagem técnica: formato, duração, áudio presente e no volume certo."""
    problemas = []
    try:
        info = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json",
                                          str(mp4)], capture_output=True, text=True, check=True).stdout)
    except Exception as e:  # noqa: BLE001
        return [f"arquivo corrompido ({e})"]
    v = [s for s in info["streams"] if s["codec_type"] == "video"]
    a = [s for s in info["streams"] if s["codec_type"] == "audio"]
    if not v or (int(v[0]["width"]), int(v[0]["height"])) != (1080, 1920):
        problemas.append("vídeo não está em 1080x1920")
    if not a:
        problemas.append("vídeo sem áudio")
    d = float(info["format"].get("duration", 0))
    if not 20 <= d <= 90:
        problemas.append(f"duração fora do padrão ({d:.0f}s)")
    if a:
        r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(mp4), "-af", "ebur128", "-f", "null", "-"],
                           capture_output=True, text=True)
        m = re.findall(r"I:\s+(-?[\d.]+) LUFS", r.stderr)
        if m and not -22 <= float(m[-1]) <= -9:
            problemas.append(f"volume fora do padrão ({m[-1]} LUFS)")
    return problemas


def _capa_no_fim(mp4, capa_jpg):
    """Põe a capa nos últimos 2 quadros do vídeo: a API escolhe esse quadro como capa (thumb_offset)."""
    d = duracao(mp4)
    tmp = mp4.with_name("com_capa.mp4")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(mp4), "-i", str(capa_jpg), "-filter_complex",
                    f"[1:v]scale=1080:1920[c];[0:v][c]overlay=enable='gte(t,{d - 0.07:.3f})'[v]", "-map", "[v]",
                    "-map", "0:a", "-c:v", "libx264", "-preset", "veryfast", "-crf", "19", "-pix_fmt", "yuv420p",
                    "-c:a", "copy", "-movflags", "+faststart", str(tmp)], check=True)
    tmp.replace(mp4)
    return int((d - 0.04) * 1000)


def produzir_um(cfg, tema_info, reg, horario, modelo_txt):
    import animacao
    import main_gratis as mg
    import narracao
    tema = tema_info["tema"]
    vid = f"{agora():%Y%m%d}-{uuid.uuid4().hex[:6]}"
    abertura = op.escolher_abertura(reg)
    item = {"id": vid, "criado": agora().isoformat(timespec="minutes"), "tema": tema, "titulo": tema[:60],
            "categoria": tema_info.get("categoria"), "pontuacao_tema": tema_info.get("pontuacao"),
            "teste": {"abertura": abertura}, "status": op.EM_PRODUCAO, "horario": None, "tentativas": 0,
            "erros": [], "historico": [], "media_id": None, "link": None, "resultados": {}}
    reg.append(item)
    salvar_registro(reg)
    op.atividade("produção", f"Começou: {tema} (pontuação {tema_info.get('pontuacao', '–')}, abertura {abertura})", vid)
    pasta = RAIZ / "saida" / f"reel_{vid}_{slug(tema)[:40]}"
    pasta.mkdir(parents=True, exist_ok=True)
    log.info(f"===== Reel {vid}: {tema} =====")
    try:
        fatos, fontes = pesquisar_fatos(tema, modelo_txt, tema_info.get("artigos"))
        item["fontes"] = fontes[:8]
        log.info(f"Pesquisa: {len(fatos.get('fatos', []))} fatos, {len(fontes)} fontes")
        recentes = [r.get("gancho") for r in reg if r.get("gancho")][-8:]
        r = criar_roteiro(tema, fatos, modelo_txt, abertura, recentes)
        if not r:
            raise RuntimeError("roteiro reprovado 3 vezes na revisão")
    except Exception as e:  # noqa: BLE001
        op.mudar(item, op.CANCELADO, str(e))
        op.marcar_tema(tema, "descartado", str(e))
        op.atividade("produção", f"Tema descartado: {tema} — {e}", vid)
        salvar_registro(reg)
        return None
    r["tema"] = tema
    item.update(titulo=r["titulo"], texto_capa=r.get("texto_capa"), gancho=r["cenas"][0]["narracao"],
                roteiro=[c["narracao"] for c in r["cenas"]],
                storyboard=[{k: c.get(k) for k in ("narracao", "visual", "movimento", "efeito", "destaques")}
                            for c in r["cenas"]])
    salvar_registro(reg)
    (pasta / "roteiro.json").write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")

    cenas = mg.desenhar_cenas(cfg, r, pasta)
    for tentativa in range(2):                      # correção automática: refaz desenhos que falharam
        falhos = [c for c in cenas if not c.with_suffix(".svg").exists()]
        if not falhos:
            break
        log.warning(f"{len(falhos)} desenho(s) falharam; refazendo (correção automática {tentativa + 1}).")
        for c in falhos:
            c.unlink(missing_ok=True)
        cenas = mg.desenhar_cenas(cfg, r, pasta)
    auds = narracao.narrar_cenas(cfg, r["cenas"], pasta, "reel")
    medir_voz(r["cenas"], auds)
    titulos = [re.sub(r"[^\w\s:?!,.\-]", "", r.get("texto_capa") or r["titulo"]).strip()] + \
              [c.get("legenda_tela", "") for c in r["cenas"][1:]]
    marca = marca_instagram()
    mp4 = animacao.montar_tiktok(cfg, r, cenas, auds, titulos, pasta, marca, minimo=0, nome="reel")
    i_capa = int(r.get("surpresa") or 0) if str(r.get("surpresa", "")).isdigit() else 0
    i_capa = min(max(i_capa, 0), len(cenas) - 1)
    svg = cenas[i_capa].with_suffix(".svg")
    capa = animacao.capa(cenas[i_capa], r.get("texto_capa") or r["titulo"], pasta / "capa.jpg", marca,
                         svg.read_text(encoding="utf-8") if svg.exists() else None)
    capa_ms = _capa_no_fim(mp4, capa)
    legenda = montar_legenda(r, fontes)
    item.update(duracao=round(duracao(mp4), 1), capa_ms=capa_ms, legenda=legenda,
                hashtags=[t for t in legenda.split() if t.startswith("#")])
    op.mudar(item, op.EM_REVISAO, "controle de qualidade")
    nota, perdas = op.nota_qualidade(r, item, pasta, cenas, auds, mp4, capa, legenda, verificar_video(mp4))
    item.update(qualidade=nota, perdas_qa=perdas)
    log.info(f"Controle de qualidade: nota {nota}/100 {perdas}")
    (pasta / "legenda.txt").write_text(legenda, encoding="utf-8")
    nome = f"{slug(r['titulo'])[:50]}"
    arqs = {pasta / f"{nome}.mp4": mp4, pasta / f"{nome}-capa.jpg": capa, pasta / f"{nome}-legenda.txt": pasta / "legenda.txt"}
    for dst, src in arqs.items():
        shutil.copyfile(src, dst)
    aprovado = nota >= op.NOTA_MINIMA
    if aprovado:
        item["horario"] = horario
    quando = datetime.fromisoformat(horario)
    tag = f"reel-{vid}"
    notas = ((f"✅ Aprovado (qualidade {nota}/100) e programado para {quando:%d/%m às %H:%M}.\n\n" if aprovado else
              f"🧪 QUARENTENA (qualidade {nota}/100, mínimo {op.NOTA_MINIMA}): " + "; ".join(perdas) + "\n\n") +
             f"Tema: {tema}\nAbertura testada: {abertura}\n\nFontes da pesquisa:\n" +
             "\n".join(f"- {f['titulo']} {f.get('url', '')}" for f in fontes[:8]))
    subprocess.run(["gh", "release", "create", tag, *map(str, arqs), "--title",
                    f"{'📱' if aprovado else '🧪'} {r['titulo']}", "--notes", notas, "--latest=false"], check=True)
    item.update(release=tag, arquivo=f"{nome}.mp4")
    if aprovado:
        try:                                         # versão TikTok (> 1 min); se falhar, o Reel segue normal
            item["tiktok"] = versao_tiktok(cfg, r, fatos, cenas, pasta, nome, tag, modelo_txt)
        except Exception as e:  # noqa: BLE001
            log.warning(f"Versão TikTok não ficou pronta: {e}")
            op.atividade("tiktok", f"Versão TikTok de '{r['titulo']}' falhou: {str(e)[:200]}", vid, True)
        op.mudar(item, op.AGUARDANDO, f"qualidade {nota}")
        op.marcar_tema(tema, "produzido")
        op.atividade("produção", f"Aprovado ({nota}/100) e programado para {quando:%d/%m %H:%M}: {r['titulo']}", vid)
        log.info(f"Reel {vid} aprovado e programado para {quando:%d/%m %H:%M}.")
    else:
        op.mudar(item, op.QUARENTENA, "; ".join(perdas))
        op.marcar_tema(tema, "quarentena", "; ".join(perdas))
        op.atividade("qualidade", f"Quarentena ({nota}/100): {r['titulo']} — " + "; ".join(perdas[:3]), vid, True)
        print(f"::warning::Reel '{r['titulo']}' ficou em quarentena (qualidade {nota}/100): {'; '.join(perdas)}")
    salvar_registro(reg)
    return item if aprovado else None


# =================================================================== pacote da semana (você posta)
PACOTE = PASTA / "pacote.json"
DIAS = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]


def hashtags(r, extras=()):
    tags = []
    for t in list(r.get("hashtags", [])) + list(extras):
        t = re.sub(r"[^\wÀ-ÿ]", "", str(t))
        if t and t.lower() not in [x.lower() for x in tags] and t.lower() not in ("binoexplica", "binoteexplica"):
            tags.append(t)
    return tags


def produzir_pacote(total=14):
    """Gera um pacote fechado de vídeos virais (62 a 70 s, servem para Instagram e TikTok) com legendas e hashtags.
    Retoma de onde parou se a rodada cair no meio. Sobe tudo num .zip na aba Releases."""
    import zipfile
    import animacao
    import main_gratis as mg
    import narracao
    cfg = carregar_config()
    modelo = cfg["gemini"]["modelo_texto"]
    reg = ler_registro()
    pac = json.loads(PACOTE.read_text(encoding="utf-8")) if PACOTE.exists() else {}
    if not pac or pac.get("fechado"):
        pac = {"id": f"pacote-{agora():%Y%m%d-%H%M}", "criado": agora().isoformat(timespec="minutes"), "videos": [], "fechado": False}
    pasta_pac = RAIZ / "saida" / pac["id"]
    pasta_pac.mkdir(parents=True, exist_ok=True)
    tentativas = 0
    while len(pac["videos"]) < total and tentativas < total * 2:
        faltam = total - len(pac["videos"])
        temas = escolher_temas(reg + [{"tema": v["tema"]} for v in pac["videos"]], min(faltam, 6), modelo)
        if not temas:
            break
        for t in temas:
            if len(pac["videos"]) >= total or tentativas >= total * 2:
                break
            tentativas += 1
            n = len(pac["videos"]) + 1
            log.info(f"===== Pacote: vídeo {n}/{total}: {t['tema']} =====")
            try:
                fatos, fontes = pesquisar_fatos(t["tema"], modelo, t.get("artigos"))
                abertura = op.escolher_abertura(reg + [{"teste": {"abertura": v.get("abertura")}} for v in pac["videos"]])
                r = criar_roteiro(t["tema"], fatos, modelo, abertura, [v["gancho"] for v in pac["videos"]][-8:],
                                  alvo=(64, 72), n_cenas=7)
                if not r:
                    raise RuntimeError("roteiro reprovado na revisão")
                pasta = RAIZ / "saida" / f"pac_{n:02d}_{slug(t['tema'])[:30]}"
                pasta.mkdir(parents=True, exist_ok=True)
                cenas = mg.desenhar_cenas(cfg, r, pasta)
                for _ in range(2):
                    falhos = [c for c in cenas if not c.with_suffix(".svg").exists()]
                    if not falhos:
                        break
                    for c in falhos:
                        c.unlink(missing_ok=True)
                    cenas = mg.desenhar_cenas(cfg, r, pasta)
                auds = narracao.narrar_cenas(cfg, r["cenas"], pasta, "pac")
                medir_voz(r["cenas"], auds)
                titulos = [re.sub(r"[^\w\s:?!,.\-]", "", r.get("texto_capa") or r["titulo"]).strip()] + \
                          [c.get("legenda_tela", "") for c in r["cenas"][1:]]
                mp4 = animacao.montar_tiktok(cfg, r, cenas, auds, titulos, pasta, "Bino Explica", minimo=62, nome="video",
                                             texto_seguir="+ SEGUE O BINO EXPLICA")
                i_capa = min(max(int(r.get("surpresa") or 0) if str(r.get("surpresa", "")).isdigit() else 0, 0), len(cenas) - 1)
                svg = cenas[i_capa].with_suffix(".svg")
                capa = animacao.capa(cenas[i_capa], r.get("texto_capa") or r["titulo"], pasta / "capa.jpg", "Bino Explica",
                                     svg.read_text(encoding="utf-8") if svg.exists() else None)
                item = {"duracao": round(duracao(mp4), 1), "fontes": fontes}
                leg_ig = montar_legenda(r, fontes)
                nota, perdas = op.nota_qualidade(r, item, pasta, cenas, auds, mp4, capa, leg_ig, verificar_video(mp4),
                                                 faixa=(60, 80))
                if nota < op.NOTA_MINIMA:
                    raise RuntimeError(f"qualidade {nota}/100: {'; '.join(perdas)}")
                tags = hashtags(r)
                leg_tt = ((r.get("legenda_tiktok") or r.get("titulo")).strip() + "\n\n" +
                          " ".join("#" + x for x in list(dict.fromkeys(
                              [x.lower() for x in tags[:3]] + ["curiosidades", "vocesabia", "aprendanotiktok"]))))
                nome = f"{n:02d}-{slug(r['titulo'])[:45]}"
                shutil.copyfile(mp4, pasta_pac / f"{nome}.mp4")
                shutil.copyfile(capa, pasta_pac / f"{nome}-capa.jpg")
                pac["videos"].append({"n": n, "tema": t["tema"], "titulo": r["titulo"], "arquivo": f"{nome}.mp4",
                                      "capa": f"{nome}-capa.jpg", "duracao": item["duracao"], "qualidade": nota,
                                      "abertura": abertura, "gancho": r["cenas"][0]["narracao"],
                                      "legenda_instagram": leg_ig, "legenda_tiktok": leg_tt,
                                      "fontes": [f.get("url") or f.get("titulo") for f in fontes]})
                PACOTE.write_text(json.dumps(pac, ensure_ascii=False, indent=2), encoding="utf-8")
                op.marcar_tema(t["tema"], "produzido")
                op.atividade("pacote", f"Vídeo {n}/{total} pronto ({item['duracao']:.0f}s, {nota}/100): {r['titulo']}")
            except Exception as e:  # noqa: BLE001
                log.warning(f"Tema descartado no pacote ({t['tema']}): {e}")
                op.marcar_tema(t["tema"], "descartado", str(e))
            time.sleep(3)
    fechar_pacote(pac, pasta_pac, total)


def fechar_pacote(pac, pasta_pac, total):
    import zipfile
    linhas = [f"# 📦 Pacote Bino Explica — {len(pac['videos'])} vídeos", "",
              "Sugestão: 2 por dia, às 12:30 e 19:30. Cada vídeo tem mais de 1 minuto (vale para o Instagram e para a "
              "monetização do TikTok).", ""]
    for k, v in enumerate(pac["videos"]):
        d = agora().date() + timedelta(days=1 + k // 2)
        dia, hora = f"{DIAS[d.weekday()]} {d:%d/%m}", ("12:30" if k % 2 == 0 else "19:30")
        linhas += [f"## {v['n']:02d}. {v['titulo']}", f"**Quando postar:** {dia}, {hora} · **Arquivo:** `{v['arquivo']}` "
                   f"· **Capa:** `{v['capa']}` · {v['duracao']:.0f}s", "", "**Legenda Instagram:**", "```",
                   v["legenda_instagram"], "```", "", "**Legenda TikTok:**", "```", v["legenda_tiktok"], "```", ""]
    (pasta_pac / "LEGENDAS.md").write_text("\n".join(linhas), encoding="utf-8")
    zipar = pasta_pac / f"{pac['id']}.zip"
    with zipfile.ZipFile(zipar, "w", zipfile.ZIP_STORED) as z:
        for f in sorted(pasta_pac.iterdir()):
            if f.suffix in (".mp4", ".jpg", ".md"):
                z.write(f, f.name)
    completo = len(pac["videos"]) >= total
    titulo = f"📦 Pacote da semana — {len(pac['videos'])} vídeos{'' if completo else ' (parcial)'}"
    existe = subprocess.run(["gh", "release", "view", pac["id"]], capture_output=True).returncode == 0
    if existe:
        subprocess.run(["gh", "release", "upload", pac["id"], str(zipar), str(pasta_pac / "LEGENDAS.md"), "--clobber"], check=True)
        subprocess.run(["gh", "release", "edit", pac["id"], "--title", titulo], check=True)
    else:
        subprocess.run(["gh", "release", "create", pac["id"], str(zipar), str(pasta_pac / "LEGENDAS.md"), "--title", titulo,
                        "--notes", "Baixe o .zip: vídeos, capas e LEGENDAS.md (legendas e hashtags de Instagram e TikTok).",
                        "--latest=false"], check=True)
    pac["fechado"] = completo
    PACOTE.write_text(json.dumps(pac, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"::notice::{titulo} em Releases ({pac['id']})")
    if not completo:
        print(f"::warning::Faltaram {total - len(pac['videos'])} vídeos (cota da IA grátis). Rode 'pacote' de novo para completar.")


# =================================================================== versão TikTok (mais de 1 minuto)
def marca_tiktok():
    return carregar_config().get("reels", {}).get("marca_tiktok") or "@binoexplica"


def versao_tiktok(cfg, r, fatos, cenas_ig, pasta, nome, tag, modelo):
    """Mesmo tema, 65 a 72 s (o TikTok só paga vídeos com mais de 1 minuto): reaproveita os desenhos do Reel,
    desenha só as cenas novas, voz e edição próprias. Sobe na mesma página de Releases."""
    import animacao
    import main_gratis as mg
    import narracao
    pps = palavras_por_segundo()
    pmin, pmax = round(62 * pps), round(70 * pps)
    visuais = [f"{k}: {c.get('visual', '')}" for k, c in enumerate(r["cenas"])]
    marca = marca_tiktok()
    obs = ""
    for tentativa in range(3):
        t = ia.gerar_json(f"""Você é roteirista do perfil "Bino Explica" no TikTok (curiosidades desenhadas à mão, Brasil).
Reescreva este vídeo como uma VERSÃO PARA TIKTOK de 65 a 72 segundos: {pmin} a {pmax} palavras no total, em EXATAMENTE
7 cenas. A voz fala {pps:.1f} palavras por segundo. Linguagem de TikTok brasileiro, frases curtas, sem enrolar.
Tema: {r['tema']}
Roteiro do Instagram (base): {json.dumps([c['narracao'] for c in r['cenas']], ensure_ascii=False)}
Use SOMENTE estes fatos (pode trazer 1 ou 2 fatos que o roteiro base não usou): {json.dumps(fatos, ensure_ascii=False)}
Regras: 1º segundo com gancho diferente do Instagram (nunca "Você sabia"); entre 20 e 30 segundos, uma frase curta
pedindo para seguir ("segue o Bino que tem curiosidade nova todo dia"); final com pergunta para os comentários.
{"Corrija: " + obs if obs else ""}
Ilustrações já prontas (reaproveite com "img" = número): {json.dumps(visuais, ensure_ascii=False)}
Em cada cena, use "img" com o número de uma ilustração pronta, OU "img": -1 com um "visual" novo em inglês
(no máximo 2 cenas novas). "legenda_tela": 2 a 4 palavras. "destaques": 1 a 3 palavras EXATAS da fala.
Responda SÓ JSON: {{"texto_capa":"2 a 4 palavras em MAIÚSCULAS terminando em ? ou !",
"cenas":[{{"narracao":"...","img":0,"visual":"","legenda_tela":"...","destaques":["..."]}}],
"legenda_tiktok":"gancho + 1 frase + pergunta + 4 a 6 hashtags (ex.: #curiosidades #vocesabia #aprendanotiktok)"}}""", modelo)
        tc = [c for c in t.get("cenas", []) if c.get("narracao")][:8]
        palavras = sum(len(c["narracao"].split()) for c in tc)
        if len(tc) < 6 or not 0.9 * pmin <= palavras <= 1.15 * pmax:
            obs = f"precisa de 7 cenas e {pmin} a {pmax} palavras (veio {len(tc)} cenas e {palavras} palavras)"
            continue
        if re.match(r"\s*voc[eê] sabia", tc[0]["narracao"], re.I):
            obs = "a primeira frase não pode começar com 'Você sabia'"
            continue
        rev = revisar({"titulo": r["titulo"], "texto_capa": t.get("texto_capa"), "cenas": tc,
                       "legenda": t.get("legenda_tiktok")}, fatos, modelo)
        if rev.get("aprovado"):
            break
        obs = rev.get("problemas", "")
        log.warning(f"Revisão da versão TikTok reprovou: {obs}")
    else:
        raise RuntimeError("roteiro da versão TikTok reprovado")
    # desenhos: reaproveita os do Reel e desenha só os novos
    novos = [c for c in tc if not (isinstance(c.get("img"), int) and 0 <= c["img"] < len(cenas_ig))]
    pngs_novos = []
    if novos:
        sub = pasta / "tiktok_desenhos"
        sub.mkdir(exist_ok=True)
        pngs_novos = mg.desenhar_cenas(cfg, {"cenas": [{"visual": c.get("visual") or r["cenas"][0].get("visual", "")}
                                                       for c in novos], "personagens": r.get("personagens", "")}, sub)
    pngs, k = [], 0
    for c in tc:
        if isinstance(c.get("img"), int) and 0 <= c["img"] < len(cenas_ig):
            pngs.append(cenas_ig[c["img"]])
        else:
            pngs.append(pngs_novos[k])
            k += 1
    auds = narracao.narrar_cenas(cfg, tc, pasta, "tt")
    titulos = [re.sub(r"[^\w\s:?!,.\-]", "", t.get("texto_capa") or r.get("texto_capa") or "").strip()] + \
              [c.get("legenda_tela", "") for c in tc[1:]]
    rot = {"cenas": [{"narracao": c["narracao"], "destaques": c.get("destaques") or []} for c in tc],
           "surpresa": len(tc) - 2}
    mp4 = animacao.montar_tiktok(cfg, rot, pngs, auds, titulos, pasta, marca, minimo=62, nome="tiktok")
    problemas = verificar_video(mp4)
    d = duracao(mp4)
    if problemas or d < 61:
        raise RuntimeError(f"versão TikTok reprovada na checagem ({problemas or f'{d:.0f}s'})")
    leg = (t.get("legenda_tiktok") or r["titulo"]).strip()
    leg = re.sub(r"@binoteexplica\b", marca, leg, flags=re.I)
    arq_v, arq_l = pasta / f"{nome}-TIKTOK.mp4", pasta / f"{nome}-TIKTOK-legenda.txt"
    shutil.copyfile(mp4, arq_v)
    arq_l.write_text(leg, encoding="utf-8")
    subprocess.run(["gh", "release", "upload", tag, str(arq_v), str(arq_l), "--clobber"], check=True)
    log.info(f"Versão TikTok pronta: {d:.0f}s")
    op.atividade("tiktok", f"Versão TikTok pronta ({d:.0f}s): {r['titulo']}")
    return {"arquivo": arq_v.name, "duracao": round(d, 1), "legenda": leg}


def produzir(quantos=2, tema=None):
    cfg = carregar_config()
    reg = ler_registro()
    op.recuperar(reg, proximos_horarios)
    salvar_registro(reg)
    pode, motivo = op.pode_produzir()
    if not pode:
        log.warning(f"Produção não executada: {motivo}.")
        op.atividade("produção", f"Não produziu: {motivo}.")
        op.painel(reg)
        return
    futuros = [r for r in reg if r["status"] == op.AGUARDANDO and r["horario"] >= agora().isoformat()]
    quantos = max(0, quantos - len(futuros)) if not tema else quantos
    if quantos == 0:
        log.info("Já há Reels aprovados para os próximos horários; nada a produzir.")
        op.painel(reg)
        return
    modelo = cfg["gemini"]["modelo_texto"]
    temas = [{"tema": tema, "categoria": "manual", "pontuacao": None}] if tema else escolher_temas(reg, quantos, modelo)
    feitos = []
    try:
        for t in temas:
            if len(feitos) >= quantos:
                break
            pode, motivo = op.pode_produzir()
            if not pode:
                log.warning(f"Parando: {motivo}.")
                break
            op.somar_uso(reels=1)
            horario = proximos_horarios(reg, 1)[0]
            try:
                item = produzir_um(cfg, t, reg, horario, modelo)
                if item:
                    feitos.append(item)
            except Exception as e:  # noqa: BLE001
                log.error(f"Falhou o tema '{t['tema']}': {e}")
                for r in reg:
                    if r["status"] in (op.EM_PRODUCAO, op.EM_REVISAO):
                        op.mudar(r, op.FALHA, str(e))
                        r["erros"].append(f"{agora():%d/%m %H:%M} {str(e)[:300]}")
                op.atividade("produção", f"Falha em '{t['tema']}': {str(e)[:250]}", erro=True)
                salvar_registro(reg)
            time.sleep(5)
    finally:
        op.somar_uso(chamadas=ia.CHAMADAS)
        op.painel(reg)
    if len(feitos) < quantos:
        print(f"::warning::Só {len(feitos)} de {quantos} Reels foram aprovados hoje (veja o PAINEL.md).")
        if not feitos:
            sys.exit(1)


# =================================================================== 4. publicação
def publicar():
    import instagram_upload as ig
    reg = ler_registro()
    if op.recuperar(reg, proximos_horarios):
        salvar_registro(reg)
    if op.pausado():
        log.info("Automação pausada: nada será publicado.")
        op.painel(reg)
        return
    da_vez = sorted([r for r in reg if r["status"] in (op.AGUARDANDO, op.PUBLICANDO) and r.get("horario") and
                     datetime.fromisoformat(r["horario"]) <= agora()], key=lambda r: r["horario"])
    if not da_vez:
        # o agendador do GitHub atrasa: as rodadas começam mais cedo e esperam o horário exato (até 20 min)
        prox = sorted([r for r in reg if r["status"] == op.AGUARDANDO and r.get("horario") and
                       agora() < datetime.fromisoformat(r["horario"]) <= agora() + timedelta(minutes=20)],
                      key=lambda r: r["horario"])
        if prox:
            espera = (datetime.fromisoformat(prox[0]["horario"]) - agora()).total_seconds()
            log.info(f"Esperando {espera / 60:.0f} min até {prox[0]['horario'][11:16]} para publicar no horário certo.")
            time.sleep(max(0, espera))
            da_vez = [prox[0]]
        else:
            log.info("Nenhum Reel na hora de publicar.")
            op.painel(reg)
            return
    item = da_vez[0]
    if not ig.conectado():
        print(f"::warning::Instagram não conectado (falta o segredo INSTAGRAM_TOKEN). '{item['titulo']}' está em Releases.")
        return
    try:
        ig.renovar_token()
        existente = ig.ja_publicado(item["legenda"])
        if existente:                                   # tentativa anterior caiu no meio: já está no ar
            item.update(media_id=existente["id"], link=existente.get("permalink"),
                        publicado=agora().isoformat(timespec="minutes"))
            op.mudar(item, op.PUBLICADO, "confirmado nos posts recentes (sem duplicar)")
            op.atividade("publicação", f"'{item['titulo']}' já estava no ar: {item['link']}", item["id"])
            salvar_registro(reg)
            return
        pasta = RAIZ / "saida" / "publicar"
        shutil.rmtree(pasta, ignore_errors=True)
        pasta.mkdir(parents=True)
        subprocess.run(["gh", "release", "download", item["release"], "-p", "*.mp4", "-D", str(pasta)], check=True)
        mp4 = next(pasta.glob("*.mp4"))
        problemas = verificar_video(mp4)
        if problemas:
            raise RuntimeError(f"checagem antes de publicar reprovou: {problemas}")
        op.mudar(item, op.PUBLICANDO, "enviando ao Instagram")
        salvar_registro(reg)
        mid = ig.publicar(mp4, item["legenda"], item.get("capa_ms"))
        item.update(media_id=mid, link=ig.permalink(mid), publicado=agora().isoformat(timespec="minutes"))
        op.mudar(item, op.PUBLICADO, "confirmado pela Meta")
        op.marcar_tema(item["tema"], "publicado")
        op.atividade("publicação", f"Publicado: {item['titulo']} → {item['link']}", item["id"])
        salvar_registro(reg)
        log.info(f"✅ Publicado: {item['link']}")
        print(f"::notice::Reel publicado: {item['titulo']} → {item['link']}")
    except Exception as e:  # noqa: BLE001
        item["tentativas"] = item.get("tentativas", 0) + 1
        item["erros"].append(f"{agora():%d/%m %H:%M} {str(e)[:300]}")
        op.mudar(item, op.FALHA if item["tentativas"] >= 3 else op.AGUARDANDO, str(e))
        op.atividade("publicação", f"Falha ao publicar '{item['titulo']}' ({item['tentativas']}/3): {str(e)[:250]}",
                     item["id"], True)
        salvar_registro(reg)
        print(f"::error::Falha ao publicar '{item['titulo']}' (tentativa {item['tentativas']}/3): {e}")
        sys.exit(1)
    finally:
        op.painel(reg)


# =================================================================== 5. análise e aprendizado
def _retencao(r):
    res = r.get("resultados") or {}
    return min(1.0, ((res.get("ig_reels_avg_watch_time") or 0) / 1000) / max(r.get("duracao") or 45, 1))


def _pontuar(r):
    res = r.get("resultados") or {}
    views = res.get("views") or 0
    if not views:
        return 0
    eng = ((res.get("shares") or 0) * 3 + (res.get("saved") or 0) * 2 + (res.get("comments") or 0) +
           (res.get("likes") or 0) * 0.5) / views
    return round(min(100, 25 * min(views / 1000, 2) + 30 * _retencao(r) + 600 * eng), 1)


def analisar():
    import instagram_upload as ig
    reg = ler_registro()
    seg = None
    if ig.conectado():
        ig.renovar_token()
        limite = agora() - timedelta(days=30)
        for r in reg:
            if r.get("media_id") and datetime.fromisoformat(r.get("publicado") or r["horario"]) > limite:
                try:
                    res = ig.insights(r["media_id"])
                    if res:
                        r["resultados"] = {**res, "atualizado": agora().isoformat(timespec="minutes")}
                        r["nota"] = _pontuar(r)
                except Exception as e:  # noqa: BLE001
                    log.warning(f"Resultados de {r['id']} indisponíveis: {e}")
        salvar_registro(reg)
        try:
            seg = ig.seguidores()
            arq = PASTA / "seguidores.json"
            hist = json.loads(arq.read_text(encoding="utf-8")) if arq.exists() else []
            if not hist or hist[-1]["data"] != agora().date().isoformat():
                hist.append({"data": agora().date().isoformat(), "seguidores": seg})
            else:
                hist[-1]["seguidores"] = seg
            arq.write_text(json.dumps(hist[-400:], ensure_ascii=False, indent=1), encoding="utf-8")
        except Exception as e:  # noqa: BLE001
            log.warning(f"Seguidores indisponíveis: {e}")
    else:
        log.warning("Instagram não conectado: sem resultados para analisar.")
    aprender(reg)
    _relatorio(reg, seg)
    op.atividade("análise", f"Resultados atualizados ({sum(1 for r in reg if r.get('nota'))} Reels com estatísticas).")
    op.painel(reg)


def aprender(reg):
    """Aprendizado com amostra mínima: categorias, horários, duração, aberturas (teste A/B) e recomendações."""
    pub = [r for r in reg if r["status"] == op.PUBLICADO and r.get("nota")]
    apr = json.loads(APRENDIZADOS.read_text(encoding="utf-8")) if APRENDIZADOS.exists() else {}
    apr["teste_abertura"] = op.analisar_testes(pub)
    if pub:
        top = sorted(pub, key=lambda r: r["nota"], reverse=True)
        cats, por_hora = {}, {}
        for r in pub:
            cats.setdefault(r.get("categoria") or "?", []).append(r["nota"])
            por_hora.setdefault(r["horario"][11:16], []).append((r.get("resultados") or {}).get("views") or 0)
        apr.update(
            melhores=[r["tema"] for r in top[:6]], piores=[r["tema"] for r in top[-3:]],
            categorias={c: {"media": round(sum(v) / len(v), 1), "n": len(v)} for c, v in cats.items()},
            categorias_fortes=[c for c in sorted(cats, key=lambda c: -sum(cats[c]) / len(cats[c])) if len(cats[c]) >= 3][:3],
            ganchos=[r["gancho"] for r in top[:4] if r.get("gancho")],
            views_por_horario={h: round(sum(v) / len(v)) for h, v in por_hora.items()},
            retencao_media=f"{sum(_retencao(r) for r in pub) / len(pub):.0%}")
        rec = []
        curtos = [r["nota"] for r in pub if (r.get("duracao") or 0) < 45]
        longos = [r["nota"] for r in pub if (r.get("duracao") or 0) >= 45]
        if len(curtos) >= 5 and len(longos) >= 5:
            mc, ml = sum(curtos) / len(curtos), sum(longos) / len(longos)
            if mc > 1.15 * ml:
                rec.append(f"Vídeos com menos de 45s rendem mais (nota {mc:.0f} x {ml:.0f}): testar roteiros mais curtos.")
            elif ml > 1.15 * mc:
                rec.append(f"Vídeos de 45s ou mais rendem mais (nota {ml:.0f} x {mc:.0f}): manter roteiros completos.")
        if apr["categorias_fortes"]:
            rec.append(f"Aumentar aos poucos a categoria '{apr['categorias_fortes'][0]}' (melhor média com 3+ vídeos).")
        if len(pub) >= 10:
            ret = sum(_retencao(r) for r in pub) / len(pub)
            if ret < 0.35:
                rec.append(f"Retenção média baixa ({ret:.0%}): ganchos mais fortes e revelação mais cedo.")
            comp = sorted(pub, key=lambda r: ((r.get("resultados") or {}).get("shares") or 0), reverse=True)[:3]
            rec.append("Mais compartilhados: " + "; ".join(r["titulo"] for r in comp) + ".")
        if len(por_hora) >= 2 and len(pub) >= 10:
            (h1, v1), (h2, v2) = sorted(por_hora.items(), key=lambda kv: -sum(kv[1]) / len(kv[1]))[:2]
            if sum(v1) / len(v1) > 1.3 * (sum(v2) / max(len(v2), 1)):
                rec.append(f"O horário {h1} rende bem mais que {h2}: teste trocar {h2} pela ação `horarios`.")
        if apr["teste_abertura"].get("vencedor"):
            rec.append(f"Abertura vencedora no teste A/B: '{apr['teste_abertura']['vencedor']}' (passa a ser usada ~60% das vezes).")
        if len(pub) < 10:
            rec.append(f"Ainda são só {len(pub)} Reels com estatísticas: conclusões firmes só a partir de 10.")
        apr["recomendacoes"] = rec
    apr["atualizado"] = agora().isoformat(timespec="minutes")
    APRENDIZADOS.write_text(json.dumps(apr, ensure_ascii=False, indent=2), encoding="utf-8")


def _relatorio(reg, seguidores):
    pub = [r for r in reg if r.get("status") == op.PUBLICADO]
    hoje = agora()
    linhas = [f"# Relatório Bino Explica — {hoje:%d/%m/%Y %H:%M}", "", "Painel completo: [PAINEL.md](PAINEL.md)", ""]
    if seguidores is not None:
        linhas.append(f"**Seguidores:** {seguidores}")
    linhas += [f"**Reels publicados:** {len(pub)}", "",
               "| Data | Reel | Views | Alcance | Curtidas | Coment. | Compart. | Salvos | Retenção | Nota | Link |",
               "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in sorted(pub, key=lambda x: x.get("publicado") or "", reverse=True)[:30]:
        x = r.get("resultados") or {}
        linhas.append(f"| {(r.get('publicado') or r['horario'])[:16].replace('T', ' ')} | {r['titulo']} | {x.get('views', '–')} | "
                      f"{x.get('reach', '–')} | {x.get('likes', '–')} | {x.get('comments', '–')} | {x.get('shares', '–')} | "
                      f"{x.get('saved', '–')} | {_retencao(r):.0%} | {r.get('nota', '–')} | [abrir]({r.get('link') or ''}) |")
    (PASTA / "relatorio.md").write_text("\n".join(linhas), encoding="utf-8")
    apr = json.loads(APRENDIZADOS.read_text(encoding="utf-8")) if APRENDIZADOS.exists() else {}
    if hoje.weekday() == 6 or not (PASTA / "semanal.md").exists():
        notados = sorted([r for r in pub if r.get("nota")], key=lambda r: r["nota"], reverse=True)
        sem = [f"# Análise semanal — {hoje:%d/%m/%Y}", "",
               f"Reels publicados: {len(pub)} · com estatísticas: {len(notados)} · retenção média: {apr.get('retencao_media', '–')}", "",
               "## Melhores Reels (nota combina views, retenção, compartilhamentos, salvos e comentários)"]
        sem += [f"{k + 1}. {r['titulo']} — nota {r['nota']} ({(r.get('resultados') or {}).get('views', 0)} views, "
                f"abertura '{(r.get('teste') or {}).get('abertura', '–')}')" for k, r in enumerate(notados[:5])] or ["- ainda sem dados"]
        sem += ["", "## Ganchos que prenderam"] + [f"- \"{g}\"" for g in apr.get("ganchos", [])[:3]]
        sem += ["", f"## Desempenho por horário", f"{apr.get('views_por_horario', {})}", "",
                "## Teste A/B de aberturas", f"{apr.get('teste_abertura', {})}", "", "## Recomendações"]
        sem += [f"- {x}" for x in apr.get("recomendacoes", [])] or ["- ainda sem dados suficientes"]
        (PASTA / "semanal.md").write_text("\n".join(sem), encoding="utf-8")
    log.info("Relatório atualizado (reels/relatorio.md).")


# =================================================================== auditoria
def auditoria():
    ok = lambda b: "✅" if b else "❌"
    print(f"{ok(bool(os.environ.get('GEMINI_API_KEY')))} Chave do Gemini (pesquisa e roteiro)")
    try:
        print(f"   Modelos disponíveis: {', '.join(ia.disponiveis()[:5])}")
        t, f = ia.pesquisar("Diga em uma frase o que é um polvo e cite a fonte.", carregar_config()["gemini"]["modelo_texto"])
        print(f"✅ Pesquisa no Google funcionando ({len(f)} fontes): {t[:80]}")
    except Exception as e:  # noqa: BLE001
        print(f"⚠️ Pesquisa no Google sem cota agora ({str(e)[:120]}); a reserva é a Wikipédia.")
    txt, fonte = ia.wikipedia("polvo")
    print(f"{ok(bool(txt))} Wikipédia (fonte de reserva): {fonte['url'] if fonte else 'indisponível'}")
    try:
        r = ia.gerar("Responda só: ok", carregar_config()["gemini"]["modelo_texto"])
        print(f"✅ Roteirista (Gemini) respondendo: {r.strip()[:20]}")
    except Exception as e:  # noqa: BLE001
        print(f"❌ Roteirista (Gemini): {str(e)[:200]}")
    print(f"{ok(bool(shutil.which('rsvg-convert')))} Desenhista de SVG  ·  {ok(bool(shutil.which('ffmpeg')))} ffmpeg")
    c = op.controle()
    print(f"{'⏸️' if c['pausado'] else '▶️'} Automação {'PAUSADA' if c['pausado'] else 'ativa'} · horários {', '.join(horarios())}")
    import instagram_upload as ig
    if not ig.conectado():
        print("❌ Instagram: falta o segredo INSTAGRAM_TOKEN (os Reels ficam prontos em Releases para postar à mão).")
        return
    try:
        info = ig.verificar_conta()
        cta = info["conta"]
        print(f"✅ Instagram conectado: @{cta.get('username')} ({cta.get('account_type', 'profissional')}), "
              f"{cta.get('followers_count')} seguidores")
        print(f"   Limite de publicação: {info['limite']}")
        try:
            m = ig.recentes(1)
            if m:
                print(f"✅ Leitura de posts OK; estatísticas do último: {ig.insights(m[0]['id']) or 'sem permissão de estatísticas'}")
        except Exception as e:  # noqa: BLE001
            print(f"⚠️ Estatísticas: {e}")
    except Exception as e:  # noqa: BLE001
        print(f"❌ Instagram: {e}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("acao", choices=["produzir", "publicar", "analisar", "auditoria", "pausar", "retomar",
                                     "reagendar", "cancelar", "horarios", "painel", "pacote"])
    ap.add_argument("--quantos", type=int, default=2)
    ap.add_argument("--tema", default="")
    ap.add_argument("--id", default="")
    ap.add_argument("--quando", default="")
    a = ap.parse_args()
    if a.acao == "pacote":
        try:
            produzir_pacote(a.quantos if a.quantos != 2 else 14)
        finally:
            op.painel(ler_registro())
    elif a.acao == "produzir":
        produzir(a.quantos, a.tema or None)
    elif a.acao == "publicar":
        publicar()
    elif a.acao == "analisar":
        analisar()
    elif a.acao == "auditoria":
        auditoria()
        op.painel(ler_registro())
    elif a.acao == "painel":
        op.painel(ler_registro())
    else:
        registro = ler_registro()
        try:
            msg = op.comando(a.acao, registro, a.id, a.quando, proximos_horarios)
            salvar_registro(registro)
            print(f"::notice::{msg}")
        except ValueError as e:
            print(f"::error::{e}")
            sys.exit(1)
        finally:
            op.painel(registro)
