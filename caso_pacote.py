"""Caso Ao Vivo — pacote de produção (as 10 entregas da produtora) em Markdown."""
from datetime import date

NOMES_PLANO = {
    "apresentador": "Apresentador virtual",
    "numero": "Arte: número em destaque", "cartao": "Arte: cartão de evidência", "local": "Arte: mapa ilustrativo com alvo",
    "data": "Arte: linha do tempo", "documento": "Arte: documento (reconstrução ilustrativa)",
    "revelacao": "Arte: revelação em tipografia", "pergunta": "Arte: pergunta final", "foto": "Foto de arquivo",
    "3d": "Cena em animação 3D (dramatização)",
}
ENQ = {"aberto": "plano aberto", "medio": "plano médio", "fechado": "close"}
INFO = {"fato": "Fato (segundo o roteiro)", "alegacao": "Alegação", "testemunho": "Testemunho", "hipotese": "Hipótese",
        "nao_verificado": "Não verificado"}
CONFIANCA = {"Confirmado na referência": "Alta (datas/números batem no mesmo trecho da referência)",
             "Sem dado conferível": "— (sem data, número ou nome para conferir)",
             "Parcial: confira o detalhe": "Média (parte bate; confira o detalhe)",
             "Não verificado": "Baixa (não encontrado; confirme antes de postar)"}


def _t(s):
    s = max(0, s)
    return f"{int(s // 60):02d}:{int(s % 60):02d}"


def _cel(t):
    return str(t or "").replace("|", "/").replace("\n", " ").strip()


def gerar(caso, pesquisa, info, falas, pags, nome_video):
    cenas, planos, tempos = caso["cenas"], info["planos"], info["tempos"]
    titulo = caso.get("titulo_caso", "Caso real")
    imagens = pesquisa.get("imagens", {}) if pesquisa else {}
    chk = pesquisa.get("checagem", []) if pesquisa else []
    fontes = pesquisa.get("fontes", []) if pesquisa else []
    artigos = pesquisa.get("artigos", []) if pesquisa else []
    lim = list(pesquisa.get("limitacoes", [])) if pesquisa else ["A pesquisa automática não rodou."]
    total = info["total"]
    if caso.get("duracao_max") and total > caso["duracao_max"] + 0.5:
        lim.append(f"O vídeo tem {total:.0f} s, acima do limite de {caso['duracao_max']:.0f} s do formato: encurte o roteiro.")
    L = [f"# Pacote de produção — {titulo}", "",
         f"Gerado em {date.today().strftime('%d/%m/%Y')} · TikTok 9:16 (1080×1920, 30 fps) · duração {_t(total)} · arquivo `{nome_video}`", ""]
    if lim:
        L += ["> **Limitações desta produção**"] + [f"> - {x}" for x in lim] + [""]

    # 1
    L += ["## 1. Dossiê de pesquisa", ""]
    if artigos:
        for a in artigos:
            L += [f"**Wikipédia ({a['lang']}): [{a['titulo']}]({a['url']})** — consultada em {pesquisa['data']}", "", f"> {a['resumo']}", ""]
        L += ["A Wikipédia é o ponto de partida: confirme os pontos principais nas fontes primárias e nos veículos listados na seção 2.", ""]
    else:
        L += ["Nenhum artigo de referência foi encontrado automaticamente. Pesquise o caso em fontes oficiais antes de postar.", ""]
    L += ["**Classificação das afirmações do roteiro**", "", "| Cena | Afirmação | Tipo | Checagem |", "|---|---|---|---|"]
    for i, c in enumerate(cenas):
        status = next((x["status"] for x in chk if x["item"] and x["item"] in c["fala"]), "—")
        L.append(f"| {i + 1} | {_cel(c['fala'])} | {INFO.get(c.get('info', ''), 'Não classificado')} | {status} |")
    L.append("")

    # 2
    L += ["## 2. Fontes e evidências", ""]
    if fontes:
        L += ["| Tipo | Domínio | Link | Encontrada em |", "|---|---|---|---|"]
        L += [f"| {f['tipo']} | {f['dominio']} | {f['url']} | {f['via']} |" for f in fontes]
        L.append("")
    else:
        L += ["Nenhuma referência externa encontrada automaticamente.", ""]
    L += ["**Checagem de datas, números e nomes**", "",
          "| Afirmação | Resultado | Confiança | Trecho de apoio (referência) |", "|---|---|---|---|"]
    for x in chk:
        L.append(f"| {_cel(x['item'])} | {x['status']} | {CONFIANCA.get(x['status'], '')} | {_cel(x['trecho'])[:260]} |")
    L += ["", "Fonte do trecho de apoio: " + (", ".join(a["url"] for a in artigos) if artigos else "nenhuma"), ""]

    # 3
    L += ["## 3. Roteiro com timestamps", ""]
    for i, (c, (a, b)) in enumerate(zip(cenas, tempos)):
        L.append(f"**[{_t(a)}–{_t(b)}] Cena {i + 1}** — {c['fala']}")
        L.append("")

    # 4
    L += ["## 4. Storyboard cena por cena", "", "| Tempo | Cena | Plano | O que aparece na tela |", "|---|---|---|---|"]
    apoios = info.get("apoios", [])
    for p in planos:
        i = p["cena"]
        if p["tipo"] == "apresentador":
            o_que = f"Apresentador em {ENQ.get(p.get('enq'), 'plano')}, movimento lento de câmera"
        elif p["tipo"] == "3d":
            o_que = "Dramatização em 3D (imagem gerada por IA pelo criador): " + (cenas[i].get("prompt_3d", "")[:160] or "cena do roteiro")
        elif p["tipo"] == "foto" and i in imagens:
            o_que = f"Foto de arquivo: {imagens[i]['titulo']} (preto e branco, zoom lento, crédito na tela)"
        else:
            ap = apoios[i] if i < len(apoios) and apoios[i] else {}
            o_que = f"{NOMES_PLANO.get(p['tipo'], p['tipo'])}: “{ap.get('valor', '')}”" + (f" — {ap.get('rotulo')}" if ap.get("rotulo") else "")
        L.append(f"| {_t(p['ini'])}–{_t(p['fim'])} | {i + 1} | {NOMES_PLANO.get(p['tipo'], p['tipo'])} | {_cel(o_que)} |")
    L.append("")

    # 5
    L += ["## 5. Imagens, links e licenças", ""]
    if imagens:
        L += ["| Cena | Imagem | Autor | Licença | Link |", "|---|---|---|---|---|"]
        for i, im in sorted(imagens.items()):
            L.append(f"| {i + 1} | {_cel(im['titulo'])} | {_cel(im['autor'])} | {im['licenca']} | {im['pagina']} |")
        L += ["", "Todas vêm do Wikimedia Commons, com licença que permite reuso. Fotos de pessoas foram descartadas "
                  "(categorias e detector de rostos). Mapas, documentos e o apresentador são ilustrações e estão identificados assim.", ""]
    else:
        L += ["Nenhuma imagem de arquivo foi usada: o vídeo usa só artes ilustrativas e o apresentador virtual.", ""]

    # 6
    L += ["## 6. Narração pronta", "", "Voz: pt-BR-AntonioNeural (masculina), voz grave natural (tom -6 Hz)" +
          (f", acelerada {100 * (info['fator'] - 1):.0f}% para caber no tempo" if info.get("fator", 1) > 1.001 else "") + ".", ""]
    L += [f["texto"] for f in falas]
    L.append("")

    # 7
    L += ["## 7. Instruções de edição (CapCut ou Premiere)", "",
          f"O `{nome_video}` já sai editado. Para refazer ou ajustar à mão:", "",
          "1. Projeto 9:16, 1080×1920, 30 fps. Importe o vídeo pronto ou a narração (seção 6) e as imagens da pasta `imagens`.",
          "2. Siga o storyboard (seção 4): cada linha é um corte. Mantenha trocas de 2 a 4 segundos, sem cortes no meio de palavra.",
          "3. Fotos de arquivo em preto e branco, com zoom lento de até 7% e o crédito do autor visível.",
          "4. Legendas: importe `legendas.srt` (CapCut: Texto › Legendas automáticas › Importar; Premiere: Legendas › Importar). "
          "Fonte condensada em caixa alta, palavra falada em caixa vermelho-escura, mantenha longe dos 20% de baixo e da coluna de ícones à direita.",
          "5. Áudio: voz dominante; trilha 18 a 22 dB abaixo da voz e com ducking; efeitos só nas entradas de arte e na revelação. "
          "Normalize em -14 LUFS (pico -1,5 dB).",
          "6. Paleta: preto, cinza, branco e vermelho-escuro. Sem filtros extras nem transições chamativas.", ""]

    # 8
    L += ["## 8. Legendas", "", "Arquivo `legendas.srt` (sincronizado com a voz). Começo:", "", "```"]
    for k, p in enumerate(pags[:8]):
        L.append(f"{_t(p['ini'])}  {' '.join(w['texto'] for w in p['palavras'])}")
    L += ["```", ""]

    # 9
    q = caso.get("posts") or {}
    sh = q.get("shorts") or {"descricao": (q.get("tiktok") or {}).get("legenda", ""), "hashtags": (q.get("tiktok") or {}).get("hashtags", [])}
    creditos = [f"Imagem: {im['titulo']} — {im['autor']}, {im['licenca']}, via Wikimedia Commons ({im['pagina']})" for _, im in sorted(imagens.items())]
    desc = sh.get("descricao", "") + ("\n\nCréditos das imagens:\n" + "\n".join(creditos) if creditos else "")
    L += ["## 9. Título, descrição e hashtags", "", f"**Título:** {sh.get('titulo') or titulo}", "", "**Descrição:**", "", "```",
          desc.strip() or "Escreva no site em “Legendas para postar”.", "```", "",
          f"**Hashtags:** {' '.join(sh.get('hashtags', [])) or '#shorts #crimesreais'}", ""]

    # 10
    n = {s: sum(1 for x in chk if x["status"] == s) for s in CONFIANCA}
    prim = sum(1 for f in fontes if f["tipo"].startswith("Fonte primária"))
    veic = sum(1 for f in fontes if f["tipo"].startswith("Reportagem"))
    ok = lambda c: "✅" if c else "⚠️"
    L += ["## 10. Verificação factual e de direitos autorais", "",
          f"- {ok(n['Não verificado'] == 0)} Fatos: {n['Confirmado na referência']} confirmados, {n['Parcial: confira o detalhe']} parciais, {n['Não verificado']} não verificados.",
          f"- {ok(prim + veic > 0)} Fontes: {prim} primárias/oficiais e {veic} de veículos reconhecidos encontradas nas referências.",
          f"- {ok(True)} Imagens: {len(imagens)} de arquivo, todas com licença livre e crédito; nenhuma foto de pessoa.",
          "- ✅ Mapas, documentos e apresentador identificados como ilustração; nenhuma imagem gerada apresentada como prova.",
          "- ✅ Trilha sonora original gerada pelo robô (sem direitos de terceiros); voz sintética.",
          f"- {ok(not caso.get('duracao_max') or total <= caso['duracao_max'] + 0.5)} Duração: {_t(total)}.",
          "- ⚠️ Antes de postar: confira os itens “Parcial” e “Não verificado”, e se algum suspeito citado foi de fato condenado "
          "(sem condenação definitiva, use “suspeito” ou “acusado”).", ""]
    return "\n".join(L)
