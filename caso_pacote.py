"""Caso Ao Vivo — pacote de produção em Markdown: as 15 entregas do editor-chefe, auditoria e anexos de pesquisa."""
from datetime import date
from urllib.parse import quote

NOMES_PLANO = {
    "apresentador": "Apresentador virtual",
    "numero": "Arte: número em destaque", "cartao": "Arte: cartão de evidência", "local": "Arte: mapa ilustrativo com alvo",
    "data": "Arte: linha do tempo", "documento": "Arte: documento (reconstrução ilustrativa)",
    "revelacao": "Arte: revelação em tipografia", "pergunta": "Arte: pergunta final", "foto": "Foto de arquivo",
    "3d": "Reconstrução 3D (dramatização)",
}
ENQ = {"aberto": "plano aberto", "medio": "plano médio", "fechado": "close"}
INFO = {"fato": "Fato", "alegacao": "Alegação", "testemunho": "Testemunho", "hipotese": "Hipótese", "nao_verificado": "Não verificado"}
CONFIANCA = {"Confirmado na referência": "Alta (datas/números batem no mesmo trecho da referência)",
             "Sem dado conferível": "— (sem data, número ou nome para conferir)",
             "Parcial: confira o detalhe": "Média (parte bate; confira o detalhe)",
             "Não verificado": "Baixa (não encontrado; confirme antes de postar)"}
SFX = {"passagem": "whoosh suave", "impacto": "impacto grave", "subida": "riser (subida de tensão)", "carimbo": "carimbo",
       "digitar": "máquina de escrever", "pulso": "pulso eletrônico"}
CAMERA = {"numero": "número em contagem, zoom suave de aproximação", "cartao": "cartão entra deslizando, zoom suave",
          "local": "mapa ilustrativo com zoom até o alvo", "data": "linha do tempo deslizando até a data",
          "documento": "documento datilografado, aproximação no trecho destacado",
          "revelacao": "tipografia cinética: palavras batem na tela com tremor curto",
          "pergunta": "cartão final com zoom lento", "foto": "Ken Burns: zoom lento de até 7% sobre a foto em preto e branco"}


def _t(s):
    s = max(0, s)
    return f"{int(s // 60):02d}:{s % 60:04.1f}"


def _cel(t):
    return str(t or "").replace("|", "/").replace("\n", " ").strip()


def _camera(p, i):
    if p["tipo"] == "apresentador":
        mov = "push-in lento" if p.get("push", 1) > 0 else "pull-out lento"
        return f"{ENQ.get(p.get('enq'), 'plano')}, {mov} com parallax do cenário"
    if p["tipo"] == "3d":
        lado = "para a direita" if (i + p.get("var", 0)) % 2 else "para a esquerda"
        return (f"plano geral, zoom in lento (1,00→1,08) e pan {lado}" if p.get("var", 0) == 0
                else f"corte fechado no centro da ação, zoom in lento e pan {lado}")
    return CAMERA.get(p["tipo"], "zoom suave")


def _transicao(p, k):
    if k == 0:
        return "abertura (sem transição)"
    if p["tipo"] == "revelacao":
        return "flash branco + separação de cores (RGB split)"
    if p["tipo"] == "apresentador":
        return "corte seco"
    return "corte com leve clarão"


def gerar(caso, pesquisa, info, falas, pags, nome_video):
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
    if caso.get("duracao_max") and total > caso["duracao_max"] + 0.5:
        lim.append(f"O vídeo tem {total:.0f} s, acima do limite de {caso['duracao_max']:.0f} s do formato: encurte o roteiro.")

    def texto_tela(p, i):
        ap = apoios[i] if i < len(apoios) else None
        if p["tipo"] == "3d":
            return "selo “DRAMATIZAÇÃO”"
        if p["tipo"] == "foto" and i in imagens:
            return f"crédito: {imagens[i]['autor']}, {imagens[i]['licenca']}"
        if p["tipo"] == "apresentador":
            c = cenas[i]
            return f"cartão “{c['tela_titulo']}”" if (not ap and c.get("tela_titulo")) else "só legendas"
        return f"“{(ap or {}).get('valor', '')}”" + (f" — {ap['rotulo']}" if ap and ap.get("rotulo") else "")

    def imagem(p, i):
        if p["tipo"] == "3d":
            return f"`imagens/cena_{i + 1:02d}_3d.jpg` (reconstrução 3D enviada pelo criador)"
        if p["tipo"] == "foto" and i in imagens:
            return f"Foto de arquivo: {imagens[i]['titulo']}"
        if p["tipo"] == "apresentador":
            return f"Apresentador virtual em {ENQ.get(p.get('enq'), 'plano')}"
        return NOMES_PLANO.get(p["tipo"], p["tipo"]) + " (gerada pelo robô)"

    def sfx(p):
        return ", ".join(f"{SFX.get(n, n)} ({_t(t)})" for t, n, *_ in eventos if p["ini"] - 0.2 <= t < p["fim"] - 0.2) or "—"

    L = [f"# Pacote de produção — {titulo}", "",
         f"Gerado em {date.today().strftime('%d/%m/%Y')} · TikTok 9:16 (1080×1920, 30 fps) · duração {_t(total)} · arquivo `{nome_video}`", ""]
    if lim:
        L += ["> **Limitações desta produção**"] + [f"> - {x}" for x in lim] + [""]

    # 1 ─ análise
    n3d = sum(1 for p in planos if p["tipo"] == "3d")
    revel = [i + 1 for i, a in enumerate(apoios) if a and a.get("tipo") == "revelacao"]
    tipos = {}
    for c in cenas:
        tipos[INFO.get(c.get("info", ""), "Não classificado")] = tipos.get(INFO.get(c.get("info", ""), "Não classificado"), 0) + 1
    gancho = tempos[0][1] - tempos[0][0] if tempos else 0
    L += ["## 1. Análise do roteiro", "",
          f"- **{len(cenas)} cenas**, {len(palavras)} palavras narradas, {_t(total)} de vídeo.",
          f"- **Gancho:** “{cenas[0]['fala']}” — {gancho:.1f} s de fala " + ("(bom: cabe nos 3 primeiros segundos)." if gancho <= 3.6 else "(longo: tente deixar o gancho com até 3 segundos)."),
          f"- **Revelações:** " + (", ".join(f"cena {r}" for r in revel) if revel else "nenhuma marcada como revelação; o ponto alto é a cena final."),
          f"- **Encerramento:** “{cenas[-1]['fala']}”",
          "- **Tipo das afirmações:** " + ", ".join(f"{k}: {v}" for k, v in tipos.items()) + ".",
          f"- **Visual:** {len(planos)} planos — {sum(1 for p in planos if p['tipo'] == 'apresentador')} do apresentador, " + (f"{n3d} de reconstrução 3D, " if n3d else "") +
          f"{sum(1 for p in planos if p['tipo'] == 'foto')} de foto de arquivo e {sum(1 for p in planos if p['tipo'] not in ('apresentador', '3d', 'foto'))} de artes.", ""]

    # 2 ─ retenção
    blocos = [(0, 3, "Gancho"), (3, 10, "Contexto"), (10, 25, "Desenvolvimento"), (25, 45, "Tensão"), (45, 9999, "Revelação e final")]
    durs = [p["fim"] - p["ini"] for p in planos]
    L += ["## 2. Estratégia de retenção", "", "| Trecho | Função | Cenas | Clima da trilha |", "|---|---|---|---|"]
    for a, b, nome in blocos:
        if a >= total:
            break
        cs = [i for i, (x, y) in enumerate(tempos) if x < min(b, total) and y > a]
        L.append(f"| {_t(a)}–{_t(min(b, total))} | {nome} | {', '.join(str(i + 1) for i in cs) or '—'} | "
                 f"{', '.join(sorted({climas[i] for i in cs})) or '—'} |")
    L += ["", f"- Troca de imagem a cada {sum(durs) / max(1, len(durs)):.1f} s em média; plano mais longo: {max(durs or [0]):.1f} s.",
          "- O apresentador aparece na abertura, nas transições e no fechamento; artes e fotos de arquivo carregam os fatos.",
          "- Palavras-chave em vermelho na legenda e efeitos só nas entradas de arte e nas revelações, para não cansar.", ""]

    # 3 ─ roteiro de edição
    L += ["## 3. Roteiro de edição por cenas", "",
          "| Entrada–Saída | Cena | Narração | Imagem |" + (" Prompt |" if n3d else "") + " Câmera | Efeito sonoro | Trilha | Texto na tela | Transição |",
          "|---|---|---|---|" + ("---|" if n3d else "") + "---|---|---|---|---|"]
    for k, p in enumerate(planos):
        i = p["cena"]
        fala = " ".join(w["texto"] for w in palavras if p["ini"] - 0.05 <= w["ini"] < p["fim"] - 0.05)
        prompt = (cenas[i].get("prompt_3d", "")[:90] + "…") if p["tipo"] == "3d" and cenas[i].get("prompt_3d") else "—"
        L.append(f"| {_t(p['ini'])}–{_t(p['fim'])} | {i + 1} | {_cel(fala) or '(pausa)'} | {_cel(imagem(p, i))} | " + (f"{_cel(prompt)} | " if n3d else "") +
                 f"{_camera(p, i)} | {sfx(p)} | {climas[i]} | {_cel(texto_tela(p, i))} | {_transicao(p, k)} |")
    L.append("")

    # 4 ─ imagens necessárias
    L += ["## 4. Imagens necessárias", "", "| Cena | O que precisa | Situação |", "|---|---|---|"]
    tem3d = {p["cena"] for p in planos if p["tipo"] == "3d"}
    for i, c in enumerate(cenas):
        if i in tem3d:
            L.append(f"| {i + 1} | Reconstrução 3D | ✅ enviada (`imagens/cena_{i + 1:02d}_3d.jpg`) |")
        elif c.get("prompt_3d"):
            L.append(f"| {i + 1} | Reconstrução 3D (prompt na seção 5) | ⚠️ não enviada — a cena saiu com apresentador e artes |")
        elif i in imagens:
            L.append(f"| {i + 1} | Foto de arquivo | ✅ {_cel(imagens[i]['titulo'])} |")
        else:
            L.append(f"| {i + 1} | Apresentador e arte gerada pelo robô | ✅ não precisa de imagem |")
    L.append("")

    # 5 ─ imagens de apoio
    if any(c.get("prompt_3d") for c in cenas):
        L += ["## 5. Prompts para gerar as imagens", "",
              "Gere uma imagem por vez, vertical 9:16. Use o mesmo personagem em todas para manter a consistência.", ""]
        for i, c in enumerate(cenas):
            if c.get("prompt_3d"):
                L += [f"**Cena {i + 1}**", "", "```", c["prompt_3d"], "```", ""]
    else:
        L += ["## 5. Imagens de apoio", "",
              "O vídeo não usa imagens geradas por IA: o visual vem do apresentador, das artes do robô e de fotos de arquivo com licença livre. "
              "Para trocar ou acrescentar uma foto de arquivo, use as buscas da seção 6 e respeite a licença.", ""]

    # 6 ─ materiais históricos
    L += ["## 6. Vídeos e materiais históricos sugeridos", ""]
    for a in artigos:
        L.append(f"- Wikipédia ({a['lang']}): [{a['titulo']}]({a['url']})")
    for f in fontes[:12]:
        L.append(f"- {f['tipo']}: {f['url']}")
    buscas = [c.get("busca_imagem") for c in cenas if c.get("busca_imagem")] or [titulo]
    for b in dict.fromkeys(buscas):
        L.append(f"- Buscar no Wikimedia Commons: https://commons.wikimedia.org/w/index.php?search={quote(b)}")
    L.append(f"- Buscar vídeos de arquivo: https://www.youtube.com/results?search_query={quote(titulo + ' documentário')}"
             " (use só trechos com permissão ou licença Creative Commons)")
    L.append("")

    # 7 ─ câmera
    L += ["## 7. Movimentos de câmera", "",
          "- **Apresentador:** alterna plano aberto, médio e close; push-in ou pull-out lento com parallax entre fundo e personagem.",
          "- **Fotos de arquivo:** Ken Burns lento (até 7%), sem distorcer a foto.",
          *(["- **Reconstruções 3D:** plano geral com zoom lento e pan lateral, alternando com corte fechado no centro da ação."] if n3d else []),
          "- **Artes:** mapa com zoom até o alvo, linha do tempo deslizando, número em contagem, documento com aproximação no destaque.", ""]

    # 8 ─ efeitos sonoros
    L += ["## 8. Efeitos sonoros", "", "| Tempo | Efeito |", "|---|---|"]
    L += [f"| {_t(t)} | {SFX.get(n, n)} |" for t, n, *_ in eventos] or ["| — | nenhum |"]
    L += ["", "Todos os efeitos são gerados pelo robô (sem direitos de terceiros).", ""]

    # 9 ─ trilha
    L += ["## 9. Trilha sonora", "", "| Cena | Clima |", "|---|---|"]
    L += [f"| {i + 1} | {climas[i]} |" for i in range(len(cenas))]
    L += ["", ("Trilha: música da pasta `assets/caso/musicas` (confira a licença). " if info.get("musica_propria") else
               "Trilha original gerada pelo robô: grave pulsante no suspense, relógio e coração acelerado na tensão e na revelação, "
               "acorde que resolve no encerramento. ")
          + "Ducking automático: a trilha abaixa sempre que a voz fala.", ""]

    # 10 ─ legendas
    L += ["## 10. Legendas sincronizadas", "",
          "Arquivo `legendas.srt` (tempo de cada palavra vem da própria voz). No vídeo: até 3 palavras por vez, fonte condensada, "
          "palavra falada em caixa vermelho-escura, palavras-chave em vermelho claro, longe dos 20% de baixo e da coluna de ícones.", "", "```"]
    L += [f"{_t(p['ini'])}  {' '.join(w['texto'] for w in p['palavras'])}" for p in pags[:10]]
    L += ["```", ""]

    # 11 ─ transições
    L += ["## 11. Transições", "",
          "- Corte seco para o apresentador (ritmo de conversa).",
          "- Leve clarão na entrada de artes e fotos.",
          "- Flash branco com separação de cores só nas revelações, com impacto grave no mesmo quadro.",
          "- Nenhuma transição chamativa (cubo, giro, glitch longo).", ""]

    # 12 ─ efeitos visuais
    L += ["## 12. Efeitos visuais", "",
          "- Paleta preto, cinza, branco e vermelho-escuro; color grading frio na investigação e quente nos cartões de pergunta.",
          "- Grão de filme leve, vinheta e sombras profundas.",
          "- Fotos de arquivo em preto e branco com crédito do autor visível.",
          ("- Selo “DRAMATIZAÇÃO” em toda reconstrução 3D; " if n3d else "- ") + "“MAPA ILUSTRATIVO” e “Reconstrução ilustrativa” nas artes.",
          f"- Barra de progresso no topo, selo “CASO REAL” e a marca {marca}.", ""]

    # 13 ─ timeline
    L += ["## 13. Montagem na timeline (CapCut ou Premiere)", "",
          f"O `{nome_video}` já sai montado. Para refazer à mão:", "",
          "1. Projeto 9:16, 1080×1920, 30 fps.",
          "2. **V1:** apresentador, " + ("reconstruções 3D, " if n3d else "") + "fotos e artes, seguindo a seção 3 linha por linha.",
          "3. **V2:** selos (CASO REAL, créditos" + (", DRAMATIZAÇÃO" if n3d else "") + ") e barra de progresso.",
          "4. **V3:** legendas (importe `legendas.srt`).",
          "5. **A1:** narração (voz grave, EQ e compressão). **A2:** trilha com ducking, 18 a 22 dB abaixo da voz. **A3:** efeitos da seção 8.",
          "6. Normalize em -14 LUFS (pico -1,5 dB).", ""]

    # 14 ─ exportação
    L += ["## 14. Configurações de exportação", "",
          "- Vídeo: MP4, H.264, 1080×1920, 30 fps, taxa alta (12 a 16 Mbps no CapCut: “Alta” ou 4K desmarcado, 1080p).",
          "- Áudio: AAC 48 kHz estéreo, 192 kbps ou mais, -14 LUFS.",
          "- Duração: até 60 s para o TikTok; nome do arquivo sem acentos.", ""]

    # 15 ─ capa e título
    q = caso.get("posts") or {}
    tk = q.get("tiktok") or {}
    capa_cena = (revel[0] - 1) if revel else (min(tem3d) if tem3d else 0)
    frase = (apoios[0] or {}).get("valor") if apoios and apoios[0] else cenas[0].get("tela_titulo") or titulo
    L += ["## 15. Capa e título", "",
          f"- **Capa:** quadro da cena {capa_cena + 1} ({_t(tempos[capa_cena][0] + 0.8)}), com o texto “{frase}” em letras grandes "
          "e uma palavra em vermelho. Na capa do TikTok, escolha esse quadro em “Editar capa”.",
          "- **Títulos:** " + (" · ".join(caso.get("titulos", [])) or titulo),
          f"- **Legenda do post:** {tk.get('legenda') or caso.get('legenda', '')}",
          f"- **Hashtags:** {' '.join(tk.get('hashtags') or caso.get('hashtags') or ['#crimesreais', '#truecrime'])}", ""]

    # auditoria
    n = {s: sum(1 for x in chk if x["status"] == s) for s in CONFIANCA}
    falta3d = [i + 1 for i, c in enumerate(cenas) if c.get("prompt_3d") and i not in tem3d]
    apres = sum(d for p, d in zip(planos, durs) if p["tipo"] == "apresentador") / max(total, 1)
    ok = lambda c: "✅" if c else "⚠️"
    L += ["## Auditoria final", "",
          f"- {ok(gancho <= 3.6)} O início prende a atenção? Gancho de {gancho:.1f} s.",
          f"- {ok(max(durs or [0]) <= 5.5)} Momentos parados? Plano mais longo de {max(durs or [0]):.1f} s.",
          f"- {ok(0.15 <= apres <= 0.6)} Apresentador na medida? Ele ocupa {100 * apres:.0f}% do vídeo.",
          f"- {ok(not falta3d)} Imagens acompanham a narrativa? " + (f"Faltaram as reconstruções das cenas {', '.join(map(str, falta3d))}." if falta3d else "Sim, todas as cenas têm imagem própria."),
          f"- {ok(n['Não verificado'] == 0)} Fatos: {n['Confirmado na referência']} confirmados, {n['Parcial: confira o detalhe']} parciais, {n['Não verificado']} não verificados.",
          f"- {ok(not caso.get('duracao_max') or total <= caso['duracao_max'] + 0.5)} Duração: {_t(total)}.",
          "- ✅ Áudio: voz dominante, trilha com ducking, -14 LUFS.",
          "- ✅ Artes identificadas como ilustração; nenhuma imagem gerada apresentada como prova.",
          "- ✅ Regras do TikTok: sem violência gráfica.",
          "- ⚠️ Antes de postar: confira os itens “Parcial” e “Não verificado” no Anexo A, e use “suspeito” ou “acusado” para quem não foi condenado.", ""]

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
        L.append("")
    if tem3d:
        L.append("Reconstruções 3D: imagens geradas por IA pelo criador, usadas só como dramatização e marcadas na tela.")
    if not imagens and not tem3d:
        L.append("Nenhuma imagem externa: o vídeo usa só o apresentador e artes ilustrativas.")
    L += ["", "## Narração", "", "Voz pt-BR-AntonioNeural, grave e natural" +
          (f", acelerada {100 * (info['fator'] - 1):.0f}% para caber no tempo" if info.get("fator", 1) > 1.001 else "") + ".", ""]
    L += [f["texto"] for f in falas]
    return "\n".join(L)
