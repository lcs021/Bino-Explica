"""
Operação automática de Reels do Bino Explica (Instagram), 100% grátis, rodando no GitHub Actions.

    python reels.py produzir [--quantos 2] [--tema "..."]   # 08:00  pesquisa, roteiro, revisão, vídeo, capa, legenda
    python reels.py publicar                                # 12:30 e 19:30  publica o próximo Reel da vez
    python reels.py analisar                                # 22:00  resultados + relatório (semanal aos domingos)
    python reels.py auditoria                               # confere o que está conectado

Tudo fica registrado em reels/registro.json (um id único por vídeo: nunca publica o mesmo duas vezes).
Os vídeos prontos ficam na aba Releases do GitHub (reel-<id>), com a capa e a legenda.
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
from zoneinfo import ZoneInfo

import ia_gemini as ia
from util import RAIZ, carregar_config, configurar_log, duracao, slug

log = configurar_log()
FUSO = ZoneInfo("America/Sao_Paulo")
PASTA = RAIZ / "reels"
REGISTRO = PASTA / "registro.json"
APRENDIZADOS = PASTA / "aprendizados.json"
HORARIOS = ["12:30", "19:30"]
CATEGORIAS = ["curiosidades sobre animais", "corpo humano", "ciência", "psicologia", "história", "espaço",
              "mistérios", "fenômenos naturais", "conhecimentos gerais", "fatos surpreendentes"]


def agora():
    return datetime.now(FUSO)


def ler_registro():
    if REGISTRO.exists():
        return json.loads(REGISTRO.read_text(encoding="utf-8"))
    return []


def salvar_registro(reg):
    PASTA.mkdir(exist_ok=True)
    REGISTRO.write_text(json.dumps(reg, ensure_ascii=False, indent=2), encoding="utf-8")


def horarios():
    cfg = carregar_config()
    return cfg.get("reels", {}).get("horarios") or HORARIOS


def proximos_horarios(reg, n):
    """Os próximos n horários livres (12:30 / 19:30), a partir de agora + 20 min."""
    ocupados = {r["horario"] for r in reg if r.get("status") in ("pronto", "publicando", "publicado")}
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


# =================================================================== 1. pesquisa
def escolher_temas(reg, quantos, modelo):
    feitos = [r["tema"] for r in reg][-80:]
    apr = json.loads(APRENDIZADOS.read_text(encoding="utf-8")) if APRENDIZADOS.exists() else {}
    dicas = ""
    if apr.get("melhores"):
        dicas = ("Desempenho real do perfil (use como guia, sem repetir os temas): os que mais deram certo foram "
                 f"{json.dumps(apr['melhores'][:5], ensure_ascii=False)}; categorias fortes: {apr.get('categorias_fortes', [])}; "
                 f"ganchos que funcionaram: {apr.get('ganchos', [])[:3]}.")
    prompt = f"""Você é o pesquisador de pauta do perfil "Bino Explica" (Reels de curiosidades desenhadas à mão, Brasil).
Data de hoje: {agora():%d/%m/%Y}. Pesquise no Google assuntos com alto potencial de viralizar no Instagram brasileiro
nestas categorias: {", ".join(CATEGORIAS)}.
Priorize o que desperta curiosidade e vontade de compartilhar ("parece mentira, mas é verdade"), com fatos bem
documentados por fontes confiáveis (museus, universidades, revistas científicas, enciclopédias, grandes veículos).
Nada de pessoas vivas, tragédias recentes, política, saúde arriscada ou boatos. Não copie roteiros de outros criadores.
{dicas}
Não repita estes temas: {json.dumps(feitos, ensure_ascii=False)}.
Responda SÓ um JSON: {{"temas":[{{"tema":"assunto específico em uma frase","categoria":"uma das categorias",
"porque":"por que viraliza, 1 frase",
"artigos":["1 a 3 títulos EXATOS de artigos da Wikipédia em português que comprovam o tema (ex.: \"Vênus (planeta)\")"]}}]}} com 6 opções de categorias diferentes, da melhor para a pior."""
    try:
        texto, _ = ia.pesquisar(prompt, modelo)
        opcoes = ia.extrair_json(texto).get("temas", [])
    except Exception as e:  # noqa: BLE001  (busca do Google sem cota hoje: a IA sugere e a Wikipédia confirma depois)
        log.warning(f"Pesquisa de pauta no Google indisponível ({e}); sugerindo temas sem busca.")
        opcoes = ia.gerar_json(prompt.replace("Pesquise no Google assuntos", "Sugira assuntos"), modelo).get("temas", [])
    escolhidos, cats = [], set()
    for o in opcoes:
        if o.get("tema") and o.get("categoria") not in cats:
            escolhidos.append(o)
            cats.add(o.get("categoria"))
    return escolhidos[:quantos + 2]               # 2 reservas, caso algum seja reprovado na revisão


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
    fonte = {"titulo": " + ".join(f["titulo"] for f in fontes)}
    dados = ia.gerar_json(f"""Leia o artigo abaixo e extraia de 6 a 9 fatos curtos, precisos e surpreendentes sobre: {tema}.
Use SOMENTE o que está escrito no artigo (números, datas e nomes exatos). Se o artigo não fala do tema, devolva fatos vazios.
Artigo ({fonte['titulo']}):
{artigo}
Responda SÓ JSON: {{"fatos":["..."],"mais_surpreendente":"..."}}""", modelo)
    if len(dados.get("fatos") or []) < 4:
        raise RuntimeError("a fonte encontrada não tem fatos suficientes sobre o tema")
    return dados, fontes


# =================================================================== 2. roteiro e revisão
def prompt_roteiro(tema, fatos, correcoes=""):
    import main_gratis as mg
    return f"""{mg.REGRAS_VIRAL}

Formato: INSTAGRAM REELS de 40 a 55 segundos (110 a 140 palavras no total), EXATAMENTE 6 cenas.
Use SOMENTE estes fatos pesquisados (não acrescente nenhum fato, número ou data que não esteja aqui):
{json.dumps(fatos, ensure_ascii=False)}
Estrutura obrigatória:
- Cena 1 = GANCHO (0 a 3 s): pergunta ou afirmação surpreendente, até 10 palavras. Nunca "Olá".
- Cenas 2 a 4 = DESENVOLVIMENTO: explique de forma simples, um fato por cena.
- Cena 5 = REVELAÇÃO: comece com uma frase curta de suspense e revele o fato mais surpreendente.
- Cena 6 = ENCERRAMENTO: conclusão curta + pergunta que faça a pessoa comentar + "segue o Bino Explica".
{"Corrija estes problemas apontados pela revisão: " + correcoes if correcoes else ""}
"visual": a cena EM INGLÊS, rabisco de quadro branco simples (1 a 3 bonequinhos de palito, uma ação clara).
"personagens": aparência fixa de cada personagem, em inglês. "legenda_tela": 2 a 4 palavras, funciona sem som.
"destaques": 1 a 3 palavras EXATAS da narração da cena (números, nomes, a palavra mais surpreendente).
Responda SÓ JSON:
{{"titulo":"curto, curioso e honesto","texto_capa":"2 a 4 palavras em MAIÚSCULAS, terminando em ? ou !",
"personagens":"...","surpresa":4,
"cenas":[{{"narracao":"...","legenda_tela":"...","visual":"...","destaques":["..."]}}],
"legenda":"legenda do post: gancho + 2 frases que contam um pouco mais + uma pergunta para os comentários + chamada para seguir o @binoexplica",
"hashtags":["5 a 8 hashtags ESPECÍFICAS do assunto, sem #, poucas genéricas"]}}"""


def revisar(r, fatos, modelo):
    texto = json.dumps({"titulo": r["titulo"], "capa": r.get("texto_capa"), "narracao": [c["narracao"] for c in r["cenas"]],
                        "legenda": r.get("legenda")}, ensure_ascii=False)
    prompt = f"""Você é o revisor final antes de publicar um Reel. Fatos pesquisados (com fontes):
{json.dumps(fatos, ensure_ascii=False)}
Roteiro: {texto}
Reprove se: (1) algum fato, número ou data do roteiro NÃO está nos fatos pesquisados ou foi exagerado/distorcido;
(2) erro de português ou de ortografia; (3) título enganoso; (4) a 1ª frase não prende; (5) conteúdo impróprio,
pessoa viva, política ou saúde arriscada; (6) falta pergunta final para os comentários.
Responda SÓ JSON: {{"aprovado": true|false, "problemas": "vazio se aprovado", "nota": 0-10}}"""
    return ia.gerar_json(prompt, modelo)


def criar_roteiro(tema, fatos, modelo):
    obs = ""
    for tentativa in range(3):
        log.info(f"Roteiro (tentativa {tentativa + 1}): {tema}")
        r = ia.gerar_json(prompt_roteiro(tema, fatos, obs), modelo)
        cenas = [c for c in r.get("cenas", []) if c.get("narracao")]
        if len(cenas) < 5:
            obs = "o roteiro precisa ter exatamente 6 cenas com narração"
            continue
        r["cenas"] = cenas[:7]
        palavras = sum(len(c["narracao"].split()) for c in r["cenas"])
        if not 85 <= palavras <= 175:
            obs = f"o roteiro tem {palavras} palavras; precisa ter entre 110 e 140"
            continue
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
        if t and t.lower() not in [x.lower() for x in tags]:
            tags.append(t)
    tags = tags[:8] or ["curiosidades", "voce sabia"]
    dominios = []
    for f in fontes:
        d = re.sub(r"^www\.", "", (f.get("titulo") or "").strip())
        if d and d not in dominios:
            dominios.append(d)
    texto = (r.get("legenda") or r["titulo"]).strip()
    if "@binoexplica" not in texto.lower():
        texto += "\n\nSegue o @binoexplica pra uma curiosidade nova todo dia!"
    if dominios:
        texto += "\n\nFontes: " + ", ".join(dominios[:4])
    texto += "\n\n" + " ".join("#" + t for t in tags)
    return texto[:2200]


def verificar_video(mp4):
    """Checagem de qualidade antes de publicar: formato, duração, áudio presente e no volume certo."""
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
    pasta = RAIZ / "saida" / f"reel_{vid}_{slug(tema)[:40]}"
    pasta.mkdir(parents=True, exist_ok=True)
    log.info(f"===== Reel {vid}: {tema} =====")
    fatos, fontes = pesquisar_fatos(tema, modelo_txt, tema_info.get("artigos"))
    log.info(f"Pesquisa: {len(fatos.get('fatos', []))} fatos, {len(fontes)} fontes")
    r = criar_roteiro(tema, fatos, modelo_txt)
    if not r:
        log.warning("Roteiro reprovado na revisão; este tema foi descartado.")
        return None
    r["tema"] = tema
    (pasta / "roteiro.json").write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")
    cenas = mg.desenhar_cenas(cfg, r, pasta)
    brancos = sum(1 for c in cenas if not c.with_suffix(".svg").exists())
    if brancos > 1:
        log.warning(f"{brancos} desenhos falharam; vídeo descartado (não publica com falhas).")
        return None
    auds = narracao.narrar_cenas(cfg, r["cenas"], pasta, "reel")
    titulos = [re.sub(r"[^\w\s:?!,.\-]", "", r.get("texto_capa") or r["titulo"]).strip()] + \
              [c.get("legenda_tela", "") for c in r["cenas"][1:]]
    marca = cfg["canal"].get("marca", "@binoexplica")
    mp4 = animacao.montar_tiktok(cfg, r, cenas, auds, titulos, pasta, marca, minimo=0, nome="reel")
    i_capa = int(r.get("surpresa") or 0) if str(r.get("surpresa", "")).isdigit() else 0
    i_capa = min(max(i_capa, 0), len(cenas) - 1)
    svg = cenas[i_capa].with_suffix(".svg")
    capa = animacao.capa(cenas[i_capa], r.get("texto_capa") or r["titulo"], pasta / "capa.jpg", marca,
                         svg.read_text(encoding="utf-8") if svg.exists() else None)
    capa_ms = _capa_no_fim(mp4, capa)
    problemas = verificar_video(mp4)
    if problemas:
        log.warning(f"Reprovado na checagem de qualidade: {problemas}")
        return None
    legenda = montar_legenda(r, fontes)
    (pasta / "legenda.txt").write_text(legenda, encoding="utf-8")
    nome = f"{slug(r['titulo'])[:50]}"
    arqs = {pasta / f"{nome}.mp4": mp4, pasta / f"{nome}-capa.jpg": capa, pasta / f"{nome}-legenda.txt": pasta / "legenda.txt"}
    for dst, src in arqs.items():
        shutil.copyfile(src, dst)
    quando = datetime.fromisoformat(horario)
    tag = f"reel-{vid}"
    notas = (f"Reel programado para {quando:%d/%m às %H:%M}.\n\n"
             f"Tema: {tema}\nRevisão: aprovado (nota {r['revisao'].get('nota')})\n\n"
             "Fontes da pesquisa:\n" + "\n".join(f"- {f['titulo']}" for f in fontes[:8]))
    subprocess.run(["gh", "release", "create", tag, *map(str, arqs), "--title", f"📱 {r['titulo']}",
                    "--notes", notas, "--latest=false"], check=True)
    item = {"id": vid, "criado": agora().isoformat(timespec="minutes"), "tema": tema,
            "categoria": tema_info.get("categoria"), "titulo": r["titulo"], "texto_capa": r.get("texto_capa"),
            "gancho": r["cenas"][0]["narracao"], "roteiro": [c["narracao"] for c in r["cenas"]],
            "legenda": legenda, "hashtags": [t for t in legenda.split() if t.startswith("#")],
            "fontes": fontes[:8], "duracao": round(duracao(mp4), 1), "capa_ms": capa_ms,
            "release": tag, "arquivo": f"{nome}.mp4", "horario": horario, "status": "pronto",
            "tentativas": 0, "erros": [], "media_id": None, "link": None, "resultados": {}}
    reg.append(item)
    salvar_registro(reg)
    log.info(f"Reel {vid} pronto e programado para {quando:%d/%m %H:%M}.")
    return item


def produzir(quantos=2, tema=None):
    cfg = carregar_config()
    reg = ler_registro()
    pendentes_hoje = [r for r in reg if r["status"] == "pronto" and r["horario"][:10] >= agora().date().isoformat()]
    quantos = max(0, quantos - len(pendentes_hoje)) if not tema else quantos
    if quantos == 0:
        log.info("Já há Reels prontos para os próximos horários; nada a produzir.")
        return
    modelo = cfg["gemini"]["modelo_texto"]
    temas = [{"tema": tema, "categoria": "manual"}] if tema else escolher_temas(reg, quantos, modelo)
    log.info("Temas escolhidos: " + " | ".join(t["tema"] for t in temas))
    feitos = []
    for t in temas:
        if len(feitos) >= quantos:
            break
        horario = proximos_horarios(reg, 1)[0]
        try:
            item = produzir_um(cfg, t, reg, horario, modelo)
            if item:
                feitos.append(item)
        except Exception as e:  # noqa: BLE001
            log.error(f"Falhou o tema '{t['tema']}': {e}")
        time.sleep(5)
    if len(feitos) < quantos:
        print(f"::warning::Só {len(feitos)} de {quantos} Reels ficaram prontos hoje (os outros foram reprovados ou falharam).")
        if not feitos:
            sys.exit(1)


# =================================================================== 4. publicação
def publicar():
    import instagram_upload as ig
    reg = ler_registro()
    da_vez = sorted([r for r in reg if r["status"] in ("pronto", "publicando") and
                     datetime.fromisoformat(r["horario"]) <= agora()], key=lambda r: r["horario"])
    if not da_vez:
        log.info("Nenhum Reel na hora de publicar.")
        return
    item = da_vez[0]
    if datetime.fromisoformat(item["horario"]) < agora() - timedelta(hours=5) and item["status"] == "pronto":
        # perdeu o horário (robô atrasado/fora do ar): reprograma para o próximo horário livre, sem duplicar
        item["horario"] = proximos_horarios(reg, 1)[0]
        salvar_registro(reg)
        log.warning(f"Reel {item['id']} perdeu o horário; reprogramado para {item['horario']}.")
        return
    if not ig.conectado():
        print(f"::warning::Instagram não conectado (falta o segredo INSTAGRAM_TOKEN). O Reel '{item['titulo']}' "
              f"está pronto em Releases ({item['release']}) para postar manualmente.")
        return
    try:
        ig.renovar_token()
        existente = ig.ja_publicado(item["legenda"])
        if existente:                                   # já foi (tentativa anterior que caiu no meio)
            item.update(status="publicado", media_id=existente["id"], link=existente.get("permalink"),
                        publicado=agora().isoformat(timespec="minutes"))
            salvar_registro(reg)
            log.info(f"Reel {item['id']} já estava no ar: {item['link']}")
            return
        pasta = RAIZ / "saida" / "publicar"
        shutil.rmtree(pasta, ignore_errors=True)
        pasta.mkdir(parents=True)
        subprocess.run(["gh", "release", "download", item["release"], "-p", "*.mp4", "-D", str(pasta)], check=True)
        mp4 = next(pasta.glob("*.mp4"))
        problemas = verificar_video(mp4)
        if problemas:
            raise RuntimeError(f"checagem de qualidade reprovou: {problemas}")
        item["status"] = "publicando"
        salvar_registro(reg)
        mid = ig.publicar(mp4, item["legenda"], item.get("capa_ms"))
        item.update(status="publicado", media_id=mid, link=ig.permalink(mid),
                    publicado=agora().isoformat(timespec="minutes"))
        salvar_registro(reg)
        log.info(f"✅ Publicado: {item['link']}")
        print(f"::notice::Reel publicado: {item['titulo']} → {item['link']}")
    except Exception as e:  # noqa: BLE001
        item["tentativas"] = item.get("tentativas", 0) + 1
        item["erros"].append(f"{agora():%d/%m %H:%M} {str(e)[:300]}")
        item["status"] = "erro" if item["tentativas"] >= 3 else "pronto"
        salvar_registro(reg)
        print(f"::error::Falha ao publicar '{item['titulo']}' (tentativa {item['tentativas']}/3): {e}")
        sys.exit(1)


# =================================================================== 5. análise
def _pontuar(r):
    res = r.get("resultados") or {}
    views = res.get("views") or 0
    if not views:
        return 0
    ret = min(1.0, ((res.get("ig_reels_avg_watch_time") or 0) / 1000) / max(r.get("duracao") or 45, 1))
    eng = ((res.get("shares") or 0) * 3 + (res.get("saved") or 0) * 2 + (res.get("comments") or 0) +
           (res.get("likes") or 0) * 0.5) / views
    return round(min(100, 25 * min(views / 1000, 2) + 30 * ret + 600 * eng), 1)


def analisar():
    import instagram_upload as ig
    reg = ler_registro()
    if not ig.conectado():
        log.warning("Instagram não conectado: sem resultados para analisar.")
        _relatorio(reg, None)
        return
    ig.renovar_token()
    limite = agora() - timedelta(days=30)
    for r in reg:
        if r.get("media_id") and datetime.fromisoformat(r.get("publicado") or r["horario"]) > limite:
            try:
                r["resultados"] = {**ig.insights(r["media_id"]), "atualizado": agora().isoformat(timespec="minutes")}
                r["nota"] = _pontuar(r)
            except Exception as e:  # noqa: BLE001
                log.warning(f"Resultados de {r['id']} indisponíveis: {e}")
    salvar_registro(reg)
    seg = None
    try:
        seg = ig.seguidores()
        arq = PASTA / "seguidores.json"
        hist = json.loads(arq.read_text(encoding="utf-8")) if arq.exists() else []
        hist.append({"data": agora().date().isoformat(), "seguidores": seg})
        arq.write_text(json.dumps(hist[-400:], ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        log.warning(f"Seguidores indisponíveis: {e}")
    _relatorio(reg, seg)


def _relatorio(reg, seguidores):
    pub = [r for r in reg if r.get("status") == "publicado"]
    hoje = agora()
    linhas = [f"# Relatório Bino Explica — {hoje:%d/%m/%Y %H:%M}", ""]
    if seguidores is not None:
        linhas.append(f"**Seguidores:** {seguidores}")
    linhas += [f"**Reels publicados:** {len(pub)} · **prontos na fila:** {sum(r['status'] == 'pronto' for r in reg)} · "
               f"**com erro:** {sum(r['status'] == 'erro' for r in reg)}", "",
               "| Data | Reel | Views | Alcance | Curtidas | Coment. | Compart. | Salvos | Retenção | Nota | Link |",
               "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in sorted(pub, key=lambda x: x.get("publicado") or "", reverse=True)[:30]:
        x = r.get("resultados") or {}
        ret = ((x.get("ig_reels_avg_watch_time") or 0) / 1000) / max(r.get("duracao") or 45, 1)
        linhas.append(f"| {(r.get('publicado') or r['horario'])[:16].replace('T', ' ')} | {r['titulo']} | {x.get('views', '–')} | "
                      f"{x.get('reach', '–')} | {x.get('likes', '–')} | {x.get('comments', '–')} | {x.get('shares', '–')} | "
                      f"{x.get('saved', '–')} | {ret:.0%} | {r.get('nota', '–')} | [abrir]({r.get('link') or ''}) |")
    fila = [r for r in reg if r["status"] in ("pronto", "erro")]
    if fila:
        linhas += ["", "## Fila e pendências"]
        for r in sorted(fila, key=lambda x: x["horario"]):
            extra = f" — erro: {r['erros'][-1]}" if r["status"] == "erro" and r.get("erros") else ""
            linhas.append(f"- {r['horario'][:16].replace('T', ' ')} · {r['titulo']} ({r['status']}){extra}")
    # aprendizados (usados pela pesquisa de amanhã) e análise semanal
    notados = [r for r in pub if r.get("nota")]
    if notados:
        top = sorted(notados, key=lambda r: r["nota"], reverse=True)
        cats = {}
        for r in notados:
            cats.setdefault(r.get("categoria") or "?", []).append(r["nota"])
        fortes = sorted(cats, key=lambda c: -sum(cats[c]) / len(cats[c]))
        por_hora = {}
        for r in notados:
            por_hora.setdefault(r["horario"][11:16], []).append((r.get("resultados") or {}).get("views") or 0)
        APRENDIZADOS.write_text(json.dumps({
            "melhores": [r["tema"] for r in top[:6]], "piores": [r["tema"] for r in top[-3:]],
            "categorias_fortes": fortes[:3], "ganchos": [r["gancho"] for r in top[:4]],
            "views_por_horario": {h: round(sum(v) / len(v)) for h, v in por_hora.items()},
            "atualizado": hoje.isoformat(timespec="minutes")}, ensure_ascii=False, indent=2), encoding="utf-8")
        if hoje.weekday() == 6 or not (PASTA / "semanal.md").exists():
            sem = [f"# Análise semanal — {hoje:%d/%m/%Y}", "",
                   "**Temas que mais funcionaram** (nota combina views, retenção, compartilhamentos, salvos e comentários):"]
            sem += [f"{k + 1}. {r['titulo']} — nota {r['nota']} ({(r.get('resultados') or {}).get('views', 0)} views)"
                    for k, r in enumerate(top[:5])]
            sem += ["", f"**Categorias mais fortes:** {', '.join(fortes[:3])}", "",
                    "**Ganchos que prenderam:**"] + [f"- \"{r['gancho']}\"" for r in top[:3]]
            sem += ["", "**Média de views por horário:** " +
                    ", ".join(f"{h} → {round(sum(v) / len(v))}" for h, v in sorted(por_hora.items()))]
            if len(por_hora) == 2 and len(notados) >= 10:
                (h1, v1), (h2, v2) = sorted(por_hora.items(), key=lambda kv: -sum(kv[1]) / len(kv[1]))
                if sum(v1) / len(v1) > 1.3 * (sum(v2) / max(len(v2), 1)):
                    sem.append(f"\n> Sugestão: o horário {h1} rende bem mais que {h2}. Para testar outro horário no lugar "
                               f"de {h2}, mude `reels: horarios:` no config.yaml.")
            (PASTA / "semanal.md").write_text("\n".join(sem), encoding="utf-8")
    (PASTA / "relatorio.md").write_text("\n".join(linhas), encoding="utf-8")
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
    import instagram_upload as ig
    if not ig.conectado():
        print("❌ Instagram: falta o segredo INSTAGRAM_TOKEN (os Reels ficam prontos em Releases para postar à mão).")
        return
    try:
        info = ig.verificar_conta()
        c = info["conta"]
        print(f"✅ Instagram conectado: @{c.get('username')} ({c.get('account_type', 'profissional')}), "
              f"{c.get('followers_count')} seguidores")
        print(f"   Limite de publicação: {info['limite']}")
    except Exception as e:  # noqa: BLE001
        print(f"❌ Instagram: {e}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("acao", choices=["produzir", "publicar", "analisar", "auditoria"])
    ap.add_argument("--quantos", type=int, default=2)
    ap.add_argument("--tema", default="")
    a = ap.parse_args()
    if a.acao == "produzir":
        produzir(a.quantos, a.tema or None)
    elif a.acao == "publicar":
        publicar()
    elif a.acao == "analisar":
        analisar()
    else:
        auditoria()
