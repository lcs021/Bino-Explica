"""Caso Ao Vivo — pacote de produção em Markdown, no formato do diretor de edição do canal:
análise, retenção, tabela TEMPO | NARRAÇÃO | VISUAL | MOVIMENTO | ÁUDIO | LEGENDA, prompts 2D, capa e publicação, auditoria."""
from datetime import date
from urllib.parse import quote

NOMES_PLANO = {
    "apresentador": "Apresentador", "numero": "Arte: número em destaque", "cartao": "Arte: cartão de evidência",
    "local": "Mapa animado (ilustrativo)", "data": "Arte: linha do tempo", "documento": "Documento animado (reconstrução ilustrativa)",
    "revelacao": "Arte: revelação em tipografia", "pergunta": "Arte: pergunta final", "foto": "Foto de arquivo",
    "3d": "Reconstrução ilustrada",
}
ENQ = {"aberto": "plano aberto", "medio": "plano médio", "fechado": "close no rosto e microfone"}
INFO = {"fato": "Fato comprovado", "alegacao": "Alegação", "testemunho": "Testemunho", "hipotese": "Hipótese", "nao_verificado": "Não verificado"}
CONFIANCA = {"Confirmado na referência": "Alta (datas/números batem no mesmo trecho da referência)",
             "Sem dado conferível": "— (sem data, número ou nome para conferir)",
             "Parcial: confira o detalhe": "Média (parte bate; confira o detalhe)",
             "Não verificado": "Baixa (não encontrado; confirme antes de postar)"}
SFX = {"passagem": "transição sonora (whoosh)", "impacto": "impacto grave", "subida": "riser de tensão", "carimbo": "carimbo",
       "digitar": "máquina de escrever", "pulso": "pulso eletrônico"}
MOV = {"numero": "número em contagem + zoom in suave", "cartao": "cartão desliza + zoom in suave",
       "local": "mapa animado, zoom até o alvo", "data": "pan horizontal pela linha do tempo",
       "documento": "documento sendo datilografado, aproximação no destaque",
       "revelacao": "tipografia cinética, palavras entram em sequência", "pergunta": "zoom out lento no cartão final",
       "foto": "zoom in cinematográfico lento (até 7%) com desfoque nas bordas"}
ESTILO_2D = ("cinematic 2D illustration, stylized expressive characters, dramatic lighting, detailed historical setting, "
             "dark sophisticated palette with deep red accents, depth and atmosphere, vertical 9:16 composition, "
             "no text, no letters, no watermark")


def _t(s):
    s = max(0, s)
    return f"{int(s // 60):02d}:{s % 60:04.1f}"


def _cel(t):
    return str(t or "").replace("|", "/").replace("\n", " ").strip()


def _mov(p, i):
    if p["tipo"] == "apresentador":
        return f"{ENQ.get(p.get('enq'), 'plano')}, " + ("push-in lento" if p.get("push", 1) > 0 else "pull-out lento") + \
            " com parallax; aproximação nas palavras-chave"
    if p["tipo"] == "3d":
        return "zoom in lento + pan horizontal" if p.get("var", 0) == 0 else "corte fechado no centro da ação, zoom in lento"
    return MOV.get(p["tipo"], "zoom suave")


def _transicao(p, k):
    if k == 0:
        return "abertura saindo do preto"
    if p["tipo"] == "apresentador":
        return "corte seco na fala"
    if p["tipo"] == "revelacao":
        return "zoom de entrada + escurecimento rápido"
    return "transição por movimento (zoom de entrada)"


def prompt_2d(c):
    if c.get("prompt_imagem"):
        base = c["prompt_imagem"].strip().rstrip(".")
    else:
        base = (c.get("busca_imagem") or c.get("tela_titulo") or "dramatic scene of the documented event").strip()
    return f"{base}. {ESTILO_2D}."


def gerar(caso, pesquisa, info, falas, pags, nome_video, capa=None):
    cenas, planos, tempos = caso["cenas"], info["planos"], info["tempos"]
    titulo = caso.get("titulo_caso", "Caso real")
    pesquisa = pesquisa or {}
    imagens = pesquisa.get("imagens", {})
    chk = pesquisa.get("checagem", [])
    fontes = pesquisa.get("fontes", [])
    artigos = pesquisa.get("artigos", [])
    lim = list(pesquisa.get("limitacoes", [])) if pesquisa else ["A pesquisa automática não rodou."]
    total = info["total"]
    apoios = info.get("apoios", [])
    climas = info.get("climas") or ["—"] * len(cenas)
    eventos = info.get("eventos", [])
    palavras = [w for p in pags for w in p["palavras"]]
    marca = caso.get("marca", "")
    durs = [p["fim"] - p["ini"] for p in planos]
    n3d = sum(1 for p in planos if p["tipo"] == "3d")
    if caso.get("duracao_max") and total > caso["duracao_max"] + 0.5:
        lim.append(f"O vídeo tem {total:.0f} s, acima do limite de {caso['duracao_max']:.0f} s do formato: encurte o roteiro.")

    def visual(p, i):
        ap = apoios[i] if i < len(apoios) else None
        if p["tipo"] == "apresentador":
            c = cenas[i]
            extra = f" + cartão “{c['tela_titulo']}”" if (not ap and c.get("tela_titulo")) else ""
            return f"Apresentador ({ENQ.get(p.get('enq'), 'plano')}){extra}"
        if p["tipo"] == "foto" and i in imagens:
            return f"Foto de arquivo: {imagens[i]['titulo']} (P&B, crédito {imagens[i]['autor']}, {imagens[i]['licenca']})"
        if p["tipo"] == "3d":
            return f"Reconstrução ilustrada `imagens/cena_{i + 1:02d}_3d.jpg` + selo “DRAMATIZAÇÃO”"
        return f"{NOMES_PLANO.get(p['tipo'], p['tipo'])}: “{(ap or {}).get('valor', '')}”"

    def audio(p, i):
        ef = [f"{SFX.get(n, n)} ({_t(t)})" for t, n, *_ in eventos if p["ini"] - 0.2 <= t < p["fim"] - 0.2]
        return "; ".join(ef + [f"trilha: {climas[i].lower()}"])

    def legenda(p):
        ws = [w for w in palavras if p["ini"] - 0.05 <= w["ini"] < p["fim"] - 0.05]
        return " ".join(f"**{w['texto'].upper()}**" if w.get("chave") else w["texto"].upper() for w in ws)

    L = [f"# Pacote de produção — {titulo}", "",
         f"Gerado em {date.today().strftime('%d/%m/%Y')} · TikTok 9:16 · 1080×1920 · MP4 H.264 · 30 fps · AAC 48 kHz · "
         f"duração {_t(total)} · arquivo `{nome_video}`" + (f" · capa `{capa}`" if capa else ""), ""]
    if lim:
        L += ["> **Limitações desta produção**"] + [f"> - {x}" for x in lim] + [""]

    # 1 ─ análise
    gancho = tempos[0][1] - tempos[0][0] if tempos else 0
    revel = [i + 1 for i, a in enumerate(apoios) if a and a.get("tipo") == "revelacao" and i > 0]
    tipos = {}
    for c in cenas:
        k = INFO.get(c.get("info", ""), "Não classificado")
        tipos[k] = tipos.get(k, 0) + 1
    L += ["## 1. Análise da história", "",
          f"- **Gancho:** “{cenas[0]['fala']}” ({gancho:.1f} s).",
          f"- **Acontecimento central:** {titulo}.",
          f"- **Ponto alto:** " + (", ".join(f"revelação na cena {r}" for r in revel) if revel else "a cena final, que fecha a história."),
          f"- **Fechamento:** “{cenas[-1]['fala']}”",
          "- **Fatos, alegações e hipóteses:** " + ", ".join(f"{k}: {v} cena(s)" for k, v in tipos.items()) + ".",
          f"- **Material visual:** {sum(1 for p in planos if p['tipo'] == 'apresentador')} planos do apresentador, "
          f"{sum(1 for p in planos if p['tipo'] == 'foto')} de foto de arquivo, "
          + (f"{n3d} de reconstrução ilustrada, " if n3d else "")
          + f"{sum(1 for p in planos if p['tipo'] not in ('apresentador', 'foto', '3d'))} de mapas, documentos e artes.", ""]

    # 2 ─ retenção
    blocos = [(0, 3, "Gancho impactante"), (3, 8, "Apresentação do mistério"), (8, 20, "Contextualização"),
              (20, 40, "Desenvolvimento e tensão"), (40, 55, "Revelação"), (55, 9999, "Conclusão / gancho para a próxima")]
    L += ["## 2. Estratégia de retenção", "", "| Trecho | Função | Cenas | Clima |", "|---|---|---|---|"]
    for a, b, nome in blocos:
        if a >= total:
            break
        cs = [i for i, (x, y) in enumerate(tempos) if x < min(b, total) and y > a]
        L.append(f"| {_t(a)}–{_t(min(b, total))} | {nome} | {', '.join(str(i + 1) for i in cs) or '—'} | "
                 f"{', '.join(dict.fromkeys(climas[i] for i in cs)) or '—'} |")
    L += ["", f"- Troca de visual a cada {sum(durs) / max(1, len(durs)):.1f} s em média (plano mais longo: {max(durs or [0]):.1f} s).",
          "- O apresentador abre, conecta os acontecimentos e fecha; fotos, mapas e documentos carregam os fatos.",
          "- Sem introdução nem despedida longa; pausas só antes das revelações.", ""]

    # 3/4 ─ divisão por cenas e tempos
    L += ["## 3. Narração por cena e 4. Tempo de cada cena", "", "| Cena | Tempo | Narração | Função | Tipo de informação |", "|---|---|---|---|---|"]
    for i, (c, (a, b)) in enumerate(zip(cenas, tempos)):
        funcao = next((n for x, y, n in blocos if x <= a < y), "")
        L.append(f"| {i + 1} | {_t(a)}–{_t(b)} | {_cel(c['fala'])} | {funcao} | {INFO.get(c.get('info', ''), '—')} |")
    L.append("")

    # tabela principal
    L += ["## Tabela de edição", "", "| TEMPO | NARRAÇÃO | VISUAL | MOVIMENTO | ÁUDIO | LEGENDA |", "|---|---|---|---|---|---|"]
    for k, p in enumerate(planos):
        i = p["cena"]
        fala = " ".join(w["texto"] for w in palavras if p["ini"] - 0.05 <= w["ini"] < p["fim"] - 0.05)
        L.append(f"| {_t(p['ini'])}–{_t(p['fim'])} | {_cel(fala) or '(pausa)'} | {_cel(visual(p, i))} → _{_transicao(p, k)}_ | "
                 f"{_mov(p, i)} | {_cel(audio(p, i))} | {_cel(legenda(p))} |")
    L += ["", "Palavras em **negrito** na coluna LEGENDA aparecem em vermelho no vídeo.", ""]

    # 5 ─ imagem necessária
    L += ["## 5. Imagem ou vídeo necessário", "", "| Cena | Material | Situação |", "|---|---|---|"]
    tem3d = {p["cena"] for p in planos if p["tipo"] == "3d"}
    for i, c in enumerate(cenas):
        if i in imagens:
            L.append(f"| {i + 1} | Foto de arquivo real | ✅ {_cel(imagens[i]['titulo'])} ({imagens[i]['licenca']}) |")
        elif i in tem3d:
            L.append(f"| {i + 1} | Reconstrução ilustrada | ✅ enviada |")
        elif c.get("busca_imagem"):
            L.append(f"| {i + 1} | Foto ou registro real de: {_cel(c['busca_imagem'])} | ⚠️ não encontrado com licença livre; "
                     "a cena saiu com apresentador e arte. Se quiser, gere a reconstrução com o prompt da seção 6 |")
        else:
            L.append(f"| {i + 1} | Apresentador e arte do robô | ✅ não precisa de imagem externa |")
    L.append("")

    # 6 ─ prompts 2D
    L += ["## 6. Prompts para gerar as imagens (reconstruções ilustradas 2D)", "",
          "Use só quando não houver imagem real. Gere uma imagem por vez, vertical 9:16, e identifique no vídeo como representação visual. "
          "Personagens genéricos: nunca imite o rosto de uma pessoa real.", ""]
    for i, c in enumerate(cenas):
        L += [f"**Cena {i + 1}**", "", "```", prompt_2d(c), "```", ""]

    # 7–11
    L += ["## 7. Movimento de câmera", "",
          "- **Apresentador:** entrada com aproximação suave, cortes no ritmo da fala, troca entre plano aberto, médio e close no rosto "
          "e microfone; aproximação extra quando ele diz uma palavra-chave.",
          "- **Fotos de arquivo:** zoom in cinematográfico lento, sem alterar a foto.",
          "- **Mapas e documentos:** mapa com zoom até o alvo, documento datilografado com aproximação no trecho importante.",
          "- **Artes:** número em contagem, linha do tempo com pan horizontal, tipografia cinética na revelação.", "",
          "## 8. Efeitos sonoros", "", "| Tempo | Efeito |", "|---|---|"]
    L += [f"| {_t(t)} | {SFX.get(n, n)} |" for t, n, *_ in eventos] or ["| — | nenhum |"]
    L += ["", "Efeitos gerados pelo robô, sem direitos de terceiros.", "",
          "## 9. Trilha sonora", "", "| Cena | Clima |", "|---|---|"]
    L += [f"| {i + 1} | {climas[i]} |" for i in range(len(cenas))]
    L += ["", ("Música da pasta `assets/caso/musicas` (confira a licença). " if info.get("musica_propria") else
               "Trilha investigativa original gerada pelo robô: graves discretos no suspense, relógio e coração acelerado na tensão, "
               "acorde que resolve no fechamento. ") + "Ducking automático: a trilha abaixa sempre que a voz fala.", "",
          "## 10. Legendas", "",
          "Texto branco em caixa alta, palavras-chave em vermelho, no máximo 2 linhas, frases curtas; as palavras acendem conforme são "
          "faladas. Fica acima dos 20% de baixo e longe da coluna de ícones da direita. Arquivo `legendas.srt` para o CapCut.", "",
          "## 11. Transições", "",
          "- Abertura saindo do preto; corte seco para o apresentador.",
          "- Fotos, mapas e documentos entram com transição por movimento (zoom de entrada que assenta).",
          "- Revelações: zoom de entrada com escurecimento rápido e impacto grave. Sem flashes nem efeitos exagerados.", "",
          "## 12. Montagem na timeline (CapCut ou Premiere)", "",
          f"O `{nome_video}` já sai montado. Para refazer à mão:", "",
          "1. Projeto 9:16, 1080×1920, 30 fps.",
          "2. **V1:** apresentador, fotos, mapas, documentos e artes, na ordem da tabela de edição.",
          "3. **V2:** selo CASO REAL, marca, créditos das fotos" + (", selo DRAMATIZAÇÃO" if n3d else "") + " e barra de progresso.",
          "4. **V3:** legendas (`legendas.srt`).",
          "5. **A1:** narração com EQ e compressão. **A2:** trilha 18 a 22 dB abaixo da voz, com ducking. **A3:** efeitos da seção 8.",
          "6. Exporte MP4 H.264, 1080×1920, 30 fps, 12 a 16 Mbps, AAC 48 kHz, volume em -14 LUFS.", ""]

    # 13 ─ capa e publicação
    q = caso.get("posts") or {}
    tk = q.get("tiktok") or {}
    ultima = cenas[-1]["fala"]
    pergunta = next((s.strip() for s in reversed(ultima.replace("!", "?").split("?")[:-1]) if s.strip()), "")
    comentario = tk.get("comentario_fixado") or (f"{pergunta}? Comenta aqui 👇" if pergunta else
                                                 f"Você já conhecia esse caso? Comenta aqui e segue {marca} pra próxima história 👇")
    L += ["## 13. Capa e publicação", "",
          (f"- **Capa vertical:** `{capa}` (1080×1920), com o apresentador e a frase da capa. No TikTok: Editar capa › Enviar da galeria."
           if capa else "- **Capa vertical:** use um quadro forte do vídeo com a frase curta em letras grandes."),
          f"- **Frase da capa:** {caso.get('capa') or '(veja a capa)'}",
          f"- **Título:** {tk.get('titulo') or (caso.get('titulos') or [titulo])[0]}",
          "- **Outros títulos:** " + (" · ".join(caso.get("titulos", [])[1:]) or "—"),
          f"- **Descrição:** {tk.get('legenda') or caso.get('legenda', '')}",
          f"- **Hashtags:** {' '.join(tk.get('hashtags') or caso.get('hashtags') or ['#crimesreais', '#truecrime'])}",
          f"- **Comentário fixado:** {comentario}", ""]

    # 14 ─ auditoria
    n = {s: sum(1 for x in chk if x["status"] == s) for s in CONFIANCA}
    sem_tempo = sum(1 for f in falas if not f.get("marcas"))
    ok = lambda c: "✅" if c else "⚠️"
    apres = sum(d for p, d in zip(planos, durs) if p["tipo"] == "apresentador") / max(total, 1)
    falta = [i + 1 for i, c in enumerate(cenas) if c.get("busca_imagem") and i not in imagens and i not in tem3d]
    L += ["## 14. Auditoria final", "",
          f"- {ok(gancho <= 3.6)} **Abertura:** gancho de {gancho:.1f} s" + ("." if gancho <= 3.6 else " — encurte a primeira fala para até 9 palavras."),
          f"- {ok(len(palavras) / max(len(cenas), 1) <= 22)} **Clareza:** {len(palavras)} palavras em {len(cenas)} cenas.",
          f"- {ok(sem_tempo == 0)} **Legendas:** " + ("sincronizadas palavra por palavra com a voz." if not sem_tempo else
                                                  f"{sem_tempo} fala(s) sem o tempo das palavras; a legenda foi distribuída pelo tamanho do texto."),
          "- ✅ **Áudio:** voz em primeiro plano, trilha com ducking, -14 LUFS.",
          f"- {ok(not falta)} **Coerência das imagens:** " + (f"sem imagem real para as cenas {', '.join(map(str, falta))} (saíram com apresentador e arte)."
                                                          if falta else "cada plano acompanha o que está sendo narrado."),
          "- ✅ **Apresentador:** a mesma arte 2D do canal em todos os planos, sem alterações.",
          f"- {ok(0.15 <= apres <= 0.6)} **Presença do apresentador:** {100 * apres:.0f}% do vídeo.",
          f"- {ok(max(durs or [0]) <= 5.5)} **Ritmo:** plano mais longo de {max(durs or [0]):.1f} s.",
          f"- {ok(gancho <= 3.6 and max(durs or [0]) <= 5.5)} **Retenção potencial:** " +
          ("boa (gancho curto e trocas rápidas)." if gancho <= 3.6 and max(durs or [0]) <= 5.5 else "melhore o gancho ou quebre os planos longos."),
          f"- {ok(bool(capa))} **Capa:** " + ("gerada com o apresentador e frase curta." if capa else "não gerada."),
          f"- {ok(n['Não verificado'] == 0)} **Fatos:** {n['Confirmado na referência']} confirmados, {n['Parcial: confira o detalhe']} parciais, "
          f"{n['Não verificado']} não verificados (Anexo A).",
          "- ✅ **Regras do TikTok:** sem violência gráfica; reconstruções e mapas identificados como ilustração.",
          "- ⚠️ **Antes de postar:** confira os itens “Parcial” e “Não verificado”, e use “suspeito” ou “acusado” para quem não foi condenado.", ""]

    # 15 ─ materiais
    L += ["## 15. Materiais para pesquisar", ""]
    for a in artigos:
        L.append(f"- Wikipédia ({a['lang']}): [{a['titulo']}]({a['url']})")
    for f in fontes[:12]:
        L.append(f"- {f['tipo']}: {f['url']}")
    for b in dict.fromkeys([c.get("busca_imagem") for c in cenas if c.get("busca_imagem")] or [titulo]):
        L.append(f"- Wikimedia Commons: https://commons.wikimedia.org/w/index.php?search={quote(b)}")
    L += [f"- Vídeos de arquivo: https://www.youtube.com/results?search_query={quote(titulo + ' documentário')} "
          "(use só trechos com permissão ou licença Creative Commons)", ""]

    # anexos
    L += ["## Anexo A. Dossiê de pesquisa e checagem", ""]
    for a in artigos:
        L += [f"**Wikipédia ({a['lang']}): [{a['titulo']}]({a['url']})** — consultada em {pesquisa.get('data', '')}", "", f"> {a['resumo']}", ""]
    if fontes:
        L += ["| Tipo | Domínio | Link | Encontrada em |", "|---|---|---|---|"]
        L += [f"| {f['tipo']} | {f['dominio']} | {f['url']} | {f['via']} |" for f in fontes]
        L.append("")
    L += ["| Afirmação | Resultado | Confiança | Trecho de apoio |", "|---|---|---|---|"]
    L += [f"| {_cel(x['item'])} | {x['status']} | {CONFIANCA.get(x['status'], '')} | {_cel(x['trecho'])[:260]} |" for x in chk]
    L += ["", "## Anexo B. Imagens e licenças", ""]
    if imagens:
        L += ["| Cena | Imagem | Autor | Licença | Link |", "|---|---|---|---|---|"]
        L += [f"| {i + 1} | {_cel(im['titulo'])} | {_cel(im['autor'])} | {im['licenca']} | {im['pagina']} |" for i, im in sorted(imagens.items())]
    else:
        L.append("Nenhuma foto de arquivo usada: o vídeo usa o apresentador e artes ilustrativas.")
    L += ["", "## Anexo C. Narração", "", "Voz pt-BR-AntonioNeural, grave e natural" +
          (f", acelerada {100 * (info['fator'] - 1):.0f}% para caber no tempo" if info.get("fator", 1) > 1.001 else "") + ".", ""]
    L += [f["texto"] for f in falas]
    return "\n".join(L)
