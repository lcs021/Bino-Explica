"""
Bino Explica — motor 100% GRÁTIS na nuvem.

Gemini (grátis) escreve o roteiro, revisa os fatos e desenha as cenas em rabisco (SVG).
edge-tts (grátis) narra com voz neural. ffmpeg (grátis) edita.
Sai em 3 formatos: YouTube 16:9, vertical 9:16 (Shorts/TikTok/Reels) e feed 4:5 (Instagram).
Publica no YouTube e no TikTok quando as autorizações estiverem cadastradas.

Uso:  python main_gratis.py [--tema "..."] [--sem-publicar]
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import ia_gemini as ia
import narracao
import video
from util import RAIZ, carregar_config, configurar_log, ler_historico, salvar_historico, slug

log = configurar_log()

BINO = ("Bino: a stick figure with a big round head, scribbled spiky black hair, two dot eyes, "
        "expressive line mouth, wearing an orange tunic with brown blotches")

ESTILO = """Hand-drawn whiteboard doodle style, like a marker sketch on white paper (explainer-video look):
- Pure white background, lots of white space. No gradients, no shadows, no filters.
- Every shape outlined with a thick black marker stroke (stroke="#1a1a1a", stroke-width 6 to 8,
  stroke-linecap="round", stroke-linejoin="round"), lines slightly wobbly like drawn by hand
  (paths with small irregular curves, never perfect geometric shapes).
- People are simple stick figures: big round head, dot eyes, small line mouth showing emotion,
  spiky scribbled hair, thin stick arms and legs.
- Color only as flat fills on a few key objects (orange tunic with brown blotches, blue water,
  green tree, red heart). Everything else white.
- Thought bubbles and simple symbols (hearts, stars, question marks drawn as shapes) for ideas.
- 1 to 3 characters, big and centered. Keep the TOP 18% and BOTTOM 15% EMPTY."""

REGRAS_VIRAL = f"""Você é roteirista do canal "Bino Explica" (YouTube, TikTok e Instagram @binoexplica):
vídeos desenhados à mão, estilo rabisco de quadro branco, feitos para VIRALIZAR.
Público: geral e família. Português do Brasil FALADO, como uma conversa entre amigos (use "a gente", "tipo", "olha só", "sabe o que é mais louco?"), divertido, frases curtas, ritmo rápido. Escreva para ser falado em voz alta: sem emojis, sem parênteses, sem listas, números por extenso quando curtos.
Retenção obrigatória:
- Primeira frase = GANCHO em até 2 segundos (pergunta intrigante, fato chocante ou situação engraçada). Nunca comece com "Olá".
- Abra uma curiosidade no início e só resolva no final.
- Cada cena traz uma informação nova, uma piada ou uma virada. Sem enrolação.
- Humor leve com o personagem fixo.
- Final: revelação ou piada + pergunta para os comentários + "segue o Bino Explica pra mais curiosidades".
Fatos: só fatos bem estabelecidos e verificáveis; sem notícias recentes, sem pessoas vivas (personagens e fatos históricos bem documentados podem),
sem conselhos de saúde arriscados, nada impróprio. Título curioso mas HONESTO.
Personagem fixo: {BINO}."""


# ------------------------------------------------------------------ roteiro
def escolher_tema(cfg) -> str:
    feitos = {h["tema"] for h in ler_historico(cfg)}
    arq = RAIZ / "temas_virais.txt"
    if arq.exists():
        for t in arq.read_text(encoding="utf-8").splitlines():
            t = t.strip()
            if t and not t.startswith("#") and t not in feitos:
                return t
    log.info("Fila de temas acabou — pedindo um tema novo ao Gemini.")
    r = ia.gerar_json(
        "Sugira UM tema de vídeo curto com alto potencial de viralizar para um canal de curiosidades "
        "desenhadas à mão (público geral/família): curiosidade surpreendente, 'e se...?', 'por que...?', "
        "ciência do dia a dia, história curiosa ou animais. Fatos bem estabelecidos. "
        f"Não repita: {json.dumps(sorted(feitos), ensure_ascii=False)}. Responda JSON: {{\"tema\":\"...\"}}",
        cfg["gemini"]["modelo_texto"])
    return r["tema"]


# Formatos que se alternam a cada vídeo (variedade evita cara de conteúdo repetitivo)
FORMATOS = {
    "explicacao": "EXPLICAÇÃO: conte a curiosidade como uma pequena história, com o Bino descobrindo a resposta aos poucos.",
    "top5": "TOP 5: cinco itens numerados sobre o tema, do menos ao mais surpreendente; o nº 1 é o mais chocante e fica para o final. Diga o número em cada item (\"Número 3...\").",
    "mito_ou_verdade": "MITO OU VERDADE: apresente 3 a 4 afirmações populares sobre o tema; para cada uma, pergunte \"mito ou verdade?\", dê 1 segundo de suspense e revele com explicação curta.",
    "quiz": "QUIZ: desafie o público a adivinhar antes do Bino. Faça uma pergunta, dê 3 opções (A, B, C), crie suspense e revele; repita com 2 ou 3 perguntas e peça para comentarem quantas acertaram.",
}
NOMES_FORMATO = {"explicacao": "Explicação", "top5": "Top 5", "mito_ou_verdade": "Mito ou verdade", "quiz": "Quiz"}


def prompt_roteiro(tema, correcoes="", formato="explicacao"):
    return f"""{REGRAS_VIRAL}

Tema: {tema}
Formato do vídeo: {FORMATOS.get(formato, FORMATOS["explicacao"])}
{"Corrija estes problemas apontados pela revisão: " + correcoes if correcoes else ""}
Crie um vídeo de ~150 segundos (~330 palavras) em EXATAMENTE 8 cenas.
Crie também um corte vertical de ~75 segundos (~190 palavras, 5 cenas) com gancho forte no 1º segundo,
no mesmo formato, reaproveitando as cenas (campo "imagem" = índice de 0 a 7).
O corte vertical PRECISA passar de 1 minuto (o TikTok só paga vídeos com mais de 60 segundos).
O visual é rabisco de quadro branco: cenas SIMPLES, 1 a 3 personagens, uma ação clara.
"visual": descrição da cena EM INGLÊS (personagens, ação, expressão, objetos).
"personagens": aparência fixa de cada personagem, em inglês, estilo bonequinho de palito.
"legenda_tela": título curto e divertido da cena, 2 a 4 palavras (ex.: "MISSÃO: ACHAR O WI-FI?").

Responda SÓ JSON:
{{"titulo":"máx 70 caracteres","descricao":"resumo instigante + pergunta + 3 hashtags","tags":["até 12"],
"personagens":"...","cenas":[{{"narracao":"...","legenda_tela":"...","visual":"..."}}],
"curto":{{"titulo":"com 1-2 emojis","legenda_tiktok":"texto curto + 3 a 5 hashtags",
"legenda_instagram":"gancho + 1-2 frases + 'salva e manda pra alguém' + 3 a 5 hashtags",
"cenas":[{{"imagem":0,"narracao":"..."}}]}},
"miniatura":{{"texto":"2 a 4 palavras em MAIÚSCULAS que dão vontade de clicar, terminando em ? ou ! (ex.: BOCEJO PEGA?)",
"selo":"1 palavra curta para o selo vermelho (ex.: QUIZ, DESAFIO, TOP 5, MITO?)",
"frase":"frase de apoio curta, até 5 palavras (ex.: Duvido você não bocejar!)","cena":"índice 0-7 da cena mais expressiva"}}}}"""


def prompt_revisao(r):
    resumo = {"titulo": r["titulo"], "descricao": r["descricao"],
              "cenas": [c["narracao"] for c in r["cenas"]], "curto": r["curto"]}
    return ("Revise este roteiro de vídeo viral para o público geral antes de publicar. Verifique: "
            "(1) fatos corretos e bem estabelecidos — reprove qualquer fato inventado, exagerado ou duvidoso; "
            "(2) adequado para todas as idades, sem pessoas vivas; (3) título honesto; "
            "(4) primeira frase prende a atenção; (5) português correto.\n"
            f"Roteiro: {json.dumps(resumo, ensure_ascii=False)}\n"
            'Responda SÓ JSON: {"aprovado": true|false, "problemas": "vazio se aprovado"}')


def validar(r):
    assert r.get("titulo") and len(r.get("cenas", [])) >= 4, "roteiro incompleto"
    if not r.get("longo"):
        r["cenas"] = r["cenas"][:8]
    n = len(r["cenas"])
    c = r.setdefault("curto", {})
    c.setdefault("titulo", r["titulo"])
    c.setdefault("legenda_tiktok", r["titulo"])
    c.setdefault("legenda_instagram", c["legenda_tiktok"])
    c["cenas"] = [{"imagem": max(0, min(n - 1, int(x.get("imagem", 0)))), "narracao": str(x.get("narracao", ""))}
                  for x in c.get("cenas", []) if x.get("narracao")] or [{"imagem": 0, "narracao": r["cenas"][0]["narracao"]}]
    r["tags"] = [str(t) for t in r.get("tags", [])][:12]
    return r


def criar_roteiro(cfg, tema, formato="explicacao"):
    m = cfg["gemini"]["modelo_texto"]
    obs = ""
    for tentativa in range(2):
        log.info(f"Escrevendo roteiro (tentativa {tentativa + 1}, formato {NOMES_FORMATO.get(formato)}): {tema}")
        r = validar(ia.gerar_json(prompt_roteiro(tema, obs, formato), m))
        r["formato"] = formato
        rev = ia.gerar_json(prompt_revisao(r), m)
        if rev.get("aprovado"):
            log.info("Roteiro aprovado na revisão.")
            return r
        obs = rev.get("problemas", "")
        log.warning(f"Revisão reprovou: {obs}")
    raise RuntimeError("Roteiro reprovado duas vezes na revisão. Nada foi publicado.")


# ------------------------------------------------------------------ desenhos
def prompt_cena(r, i):
    return f"""Draw ONE illustration as a single SVG for scene {i + 1} of {len(r['cenas'])} of a funny, family-friendly
viral explainer cartoon.
Scene: {r['cenas'][i].get('visual', '')}
Recurring characters (keep exactly this look): {r.get('personagens', '')}. {BINO}.
{ESTILO}
Element ORDER matters (the video draws the SVG stroke by stroke, in document order): ground/background objects
first, then the characters (head, body, arms, legs, face), then small details. As the LAST 1 or 2 elements, add a
hand-drawn red (#E0312B) arrow or loose circle (stroke only, fill="none", stroke-width 7) pointing at or circling
the most important detail of the scene.
Technical rules: viewBox="0 0 1600 900", xmlns="http://www.w3.org/2000/svg", start with
<rect width="1600" height="900" fill="#FFFFFF"/>. No text, letters or numbers. No <image>, <script>,
<filter>, gradients, external links or fonts. Mostly <path> elements. Under 14000 characters.
Reply with ONLY the SVG code, starting with <svg and ending with </svg>."""


def limpar_svg(t):
    m = re.search(r"<svg[\s\S]*</svg>", t, re.I)
    if not m:
        return None
    s = m.group(0)
    s = re.sub(r"<script[\s\S]*?</script>|<foreignObject[\s\S]*?</foreignObject>|<image[^>]*>", "", s, flags=re.I)
    if "xmlns=" not in s[:200]:
        s = s.replace("<svg", '<svg xmlns="http://www.w3.org/2000/svg"', 1)
    return s


def svg_para_png(svg_txt, destino, w=1920, h=1080):
    fonte = destino.with_suffix(".svg")
    fonte.write_text(svg_txt, encoding="utf-8")
    if shutil.which("rsvg-convert"):
        r = subprocess.run(["rsvg-convert", "-w", str(w), "-h", str(h), "-b", "white", "-o", str(destino), str(fonte)],
                           capture_output=True)
    else:
        r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-width", str(w), "-height", str(h),
                            "-i", str(fonte), str(destino)], capture_output=True)
    if r.returncode != 0 or not destino.exists():
        return False
    img = Image.open(destino).convert("RGBA")
    fundo = Image.new("RGBA", img.size, "white")
    fundo.alpha_composite(img)
    fundo.convert("RGB").save(destino)
    return True


def desenhar_cenas(cfg, r, pasta):
    caminhos = []
    for i in range(len(r["cenas"])):
        destino = pasta / f"cena_{i:02d}.png"
        if not destino.exists():
            ok = False
            for tentativa in range(2):
                log.info(f"Desenhando cena {i + 1}/{len(r['cenas'])}")
                svg = limpar_svg(ia.gerar(prompt_cena(r, i), cfg["gemini"]["modelo_desenho"], temperatura=0.7))
                if svg and svg_para_png(svg, destino):
                    ok = True
                    break
            if not ok:   # cena em branco: o título e a narração seguram
                Image.new("RGB", (1920, 1080), "white").save(destino)
            time.sleep(cfg["gemini"].get("pausa_seg", 4))
        caminhos.append(destino)
    return caminhos


# ------------------------------------------------------------------ composição
def fonte(tam):
    for p in [RAIZ / "assets/fontes/GochiHand-Regular.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]:
        try:
            return ImageFont.truetype(str(p), tam)
        except OSError:
            continue
    return ImageFont.load_default()


def _quebrar(draw, texto, f, largura):
    linhas, atual = [], ""
    for p in texto.split():
        t = (atual + " " + p).strip()
        if draw.textlength(t, font=f) > largura and atual:
            linhas.append(atual)
            atual = p
        else:
            atual = t
    linhas.append(atual)
    return linhas


def compor(cena_png, titulo, W, H, marca, destino, selo=None):
    """Monta o quadro final: fundo branco, desenho, título manuscrito em cima e marca d'água."""
    tela = Image.new("RGB", (W, H), "white")
    img = Image.open(cena_png).convert("RGB")
    if W / H > 1.5:                                  # 16:9
        tela.paste(img.resize((W, H), Image.LANCZOS), (0, 0))
        y_tit, tam = 60, 96
    elif H / W > 1.5:                                # 9:16 (TikTok): recorta as bordas e amplia o desenho
        from PIL import ImageChops
        caixa = ImageChops.difference(img, Image.new("RGB", img.size, "white")).convert("L") \
            .point(lambda x: 255 if x > 20 else 0).getbbox()
        if caixa:
            m = int(img.width * 0.03)
            img = img.crop((max(0, caixa[0] - m), max(0, caixa[1] - m),
                            min(img.width, caixa[2] + m), min(img.height, caixa[3] + m)))
        topo, base = (520 if selo else 430), H - 640   # entre o título (em cima) e a legenda (embaixo)
        esc = min((W - 60) / img.width, (base - topo) / img.height)
        nova = img.resize((max(1, int(img.width * esc)), max(1, int(img.height * esc))), Image.LANCZOS)
        tela.paste(nova, ((W - nova.width) // 2, topo + (base - topo - nova.height) // 2))
        y_tit, tam = 170, 104
    else:
        larg = int(W * 1.18)
        alt = int(larg * 9 / 16)
        tela.paste(img.resize((larg, alt), Image.LANCZOS), ((W - larg) // 2, (H - alt) // 2))
        y_tit, tam = 70, 84
    d = ImageDraw.Draw(tela)
    if titulo:
        f = fonte(tam)
        linhas = _quebrar(d, titulo.upper(), f, W - 120)
        for k, ln in enumerate(linhas):
            y = y_tit + k * int(tam * 1.05)
            w = d.textlength(ln, font=f)
            x = (W - w) / 2
            if k == len(linhas) - 1 and ln[-1:] in "?!":
                d.text((x, y), ln[:-1], font=f, fill="#1a1a1a")
                d.text((x + d.textlength(ln[:-1], font=f), y), ln[-1], font=f, fill="#E0312B")
            else:
                d.text((x, y), ln, font=f, fill="#1a1a1a")
    if selo and H / W > 1.5:                         # selo fixo da série: "PARTE 2"
        fs = ImageFont.truetype(str(RAIZ / "assets/fontes/Poppins-Black.ttf"), 52) \
            if (RAIZ / "assets/fontes/Poppins-Black.ttf").exists() else fonte(52)
        tw = d.textlength(selo, font=fs)
        x0, y0 = (W - tw) / 2 - 34, 420
        d.rounded_rectangle((x0, y0, x0 + tw + 68, y0 + 78), 20, fill="#E0312B", outline="#1A1A1A", width=7)
        d.text((W / 2, y0 + 39), selo, font=fs, fill="white", anchor="mm")
    fm = fonte(34)
    if H / W > 1.5:
        w = d.textlength(marca, font=fm)
        d.text(((W - w) / 2, H - 330), marca, font=fm, fill="#8a8a8a")
    else:
        w = d.textlength(marca, font=fm)
        d.text((W - w - 50, H - 90), marca, font=fm, fill="#8a8a8a")
    tela.save(destino)
    return destino


# ------------------------------------------------------------------ principal
def escolher_formato(cfg) -> str:
    """Revezamento: explicação → top 5 → mito ou verdade → quiz → ..."""
    ordem = list(FORMATOS)
    return ordem[len(ler_historico(cfg)) % len(ordem)]


def produzir(cfg, tema, pasta, formato="explicacao"):
    pasta.mkdir(parents=True, exist_ok=True)
    arq = pasta / "roteiro.json"
    if arq.exists():
        r = json.loads(arq.read_text(encoding="utf-8"))
    else:
        r = criar_roteiro(cfg, tema, formato)
        r["tema"] = tema
        arq.write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")

    cenas = desenhar_cenas(cfg, r, pasta)
    marca = cfg["canal"].get("marca", "@binoexplica")
    if r.get("plataforma") == "tiktok":
        return _so_tiktok(cfg, r, cenas, pasta, marca)
    if cfg["publicacao"].get("apenas_tiktok"):
        return _tiktok_do_corte(cfg, r, cenas, pasta, marca)
    textos_longo = [c["narracao"] for c in r["cenas"]]
    textos_curto = [c["narracao"] for c in r["curto"]["cenas"]]

    longo_imgs = [compor(cenas[i], c.get("legenda_tela", ""), 1920, 1080, marca, pasta / f"h_{i:02d}.png")
                  for i, c in enumerate(r["cenas"])]
    titulo_curto = re.sub(r"[^\w\s:?!,.\-]", "", r["curto"]["titulo"]).strip()

    def titulos_curto():
        return [titulo_curto if k == 0 else r["cenas"][c["imagem"]].get("legenda_tela", "")
                for k, c in enumerate(r["curto"]["cenas"])]

    vert_imgs = [compor(cenas[c["imagem"]], t, 1080, 1920, marca, pasta / f"v_{k:02d}.png")
                 for k, (c, t) in enumerate(zip(r["curto"]["cenas"], titulos_curto()))]
    feed_imgs = [compor(cenas[c["imagem"]], t, 1080, 1350, marca, pasta / f"f_{k:02d}.png")
                 for k, (c, t) in enumerate(zip(r["curto"]["cenas"], titulos_curto()))]

    aud_longo = narracao.narrar_cenas(cfg, r["cenas"], pasta, "longo")
    aud_curto = narracao.narrar_cenas(cfg, r["curto"]["cenas"], pasta, "curto")

    longo = video.montar(cfg, longo_imgs, aud_longo, textos_longo, pasta, "youtube_16x9", 1920, 1080)
    # vertical com no mínimo 62s: se a narração ficar curta, segura o último quadro
    curto = video.montar(cfg, vert_imgs, aud_curto, textos_curto, pasta, "vertical_shorts_tiktok_reels", 1080, 1920,
                         minimo=62)
    feed = video.montar(cfg, feed_imgs, aud_curto, textos_curto, pasta, "instagram_feed_4x5", 1080, 1350, minimo=62)

    import thumbnail
    mini = thumbnail.para_roteiro(r, cenas, pasta / "miniatura.jpg")
    log.info("Thumbnail pronta: miniatura.jpg")
    (pasta / "legendas.txt").write_text(
        f"YOUTUBE\n{r['titulo']}\n\n{r['descricao']}\n\nTags: {', '.join(r['tags'])}\n\n"
        f"SHORTS\n{r['curto']['titulo']} #Shorts\n\nTIKTOK\n{r['curto']['legenda_tiktok']}\n\n"
        f"INSTAGRAM\n{r['curto']['legenda_instagram']}\n", encoding="utf-8")
    return {"roteiro": r, "longo": longo, "curto": curto, "feed": feed, "miniatura": mini}


def _animado(cfg, r, cenas_png, auds, titulos, pasta, marca, selo=None):
    """Edição animada (traço a traço, legendas palavra a palavra, trilha e efeitos). Se falhar, volta ao modo simples."""
    if os.environ.get("ANIMACAO", "1") == "0":
        return None
    try:
        import animacao
        return animacao.montar_tiktok(cfg, r, cenas_png, auds, titulos, pasta, marca, selo)
    except Exception as e:  # noqa: BLE001
        import traceback
        log.error(f"Edição animada falhou ({e}); montando no modo simples.\n{traceback.format_exc()[-1500:]}")
        return None


def _so_tiktok(cfg, r, cenas, pasta, marca):
    """Episódio feito só para o TikTok: monta apenas o vertical 9:16 (mín. 62s) com as cenas do roteiro."""
    titulos = [re.sub(r"[^\w\s:?!,.\-]", "", r.get("texto_capa") or r["curto"]["titulo"]).strip() if i == 0
               else c.get("legenda_tela", "") for i, c in enumerate(r["cenas"])]
    serie = r.get("serie") or {}
    selo = f"PARTE {serie['parte']}" if serie.get("parte") else None
    auds = narracao.narrar_cenas(cfg, r["cenas"], pasta, "tiktok")
    vid = _animado(cfg, r, cenas, auds, titulos, pasta, marca, selo)
    if not vid:
        imgs = [compor(cenas[i], t, 1080, 1920, marca, pasta / f"v_{i:02d}.png", selo) for i, t in enumerate(titulos)]
        vid = video.montar(cfg, imgs, auds, [c["narracao"] for c in r["cenas"]], pasta, "tiktok_9x16", 1080, 1920,
                           minimo=62)
    (pasta / "legendas.txt").write_text(f"TIKTOK\n{r['curto']['legenda_tiktok']}\n", encoding="utf-8")
    return {"roteiro": r, "longo": None, "curto": vid, "feed": None, "miniatura": None}


def _tiktok_do_corte(cfg, r, cenas, pasta, marca):
    """Episódios antigos (feitos para o YouTube): monta só o corte vertical de ~75s para o TikTok."""
    cc = r["curto"]["cenas"]
    titulo = re.sub(r"[^\w\s:?!,.\-]", "", r["curto"]["titulo"]).strip()
    titulos = [titulo if k == 0 else r["cenas"][c["imagem"]].get("legenda_tela", "") for k, c in enumerate(cc)]
    auds = narracao.narrar_cenas(cfg, cc, pasta, "tiktok")
    vid = _animado(cfg, {**r, "cenas": cc, "surpresa": None}, [cenas[c["imagem"]] for c in cc], auds, titulos, pasta, marca)
    if not vid:
        imgs = [compor(cenas[c["imagem"]], t, 1080, 1920, marca, pasta / f"v_{k:02d}.png") for k, (c, t) in enumerate(zip(cc, titulos))]
        vid = video.montar(cfg, imgs, auds, [c["narracao"] for c in cc], pasta, "tiktok_9x16", 1080, 1920, minimo=62)
    (pasta / "legendas.txt").write_text(f"TIKTOK\n{r['curto']['legenda_tiktok']}\n", encoding="utf-8")
    return {"roteiro": r, "longo": None, "curto": vid, "feed": None, "miniatura": None}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tema")
    ap.add_argument("--sem-publicar", action="store_true")
    ap.add_argument("--formato", choices=["auto"] + list(FORMATOS), default="auto")
    a = ap.parse_args()
    cfg = carregar_config()
    pub = cfg["publicacao"]
    pub["youtube"] = bool(os.environ.get("YOUTUBE_REFRESH_TOKEN") or os.environ.get("YOUTUBE_TOKEN_JSON")) \
        and not a.sem_publicar
    pub["tiktok"] = bool(os.environ.get("TIKTOK_REFRESH_TOKEN") or
                         ((RAIZ / "tokens/tiktok.enc").exists() and os.environ.get("TIKTOK_CLIENT_SECRET"))) \
        and not a.sem_publicar
    pub["instagram"] = bool(os.environ.get("INSTAGRAM_TOKEN")) and not a.sem_publicar
    log.info(f"Contas conectadas: YouTube={pub['youtube']} TikTok={pub['tiktok']} Instagram={pub['instagram']}")
    pub["feito_para_criancas"] = False      # canal para público geral: monetiza melhor

    tema = a.tema or escolher_tema(cfg)
    formato = escolher_formato(cfg) if a.formato == "auto" else a.formato
    pasta = RAIZ / cfg["pastas"]["saida"] / f"{datetime.now():%Y-%m-%d_%H%M}_{slug(tema)}"
    log.info(f"===== Bino Explica: {tema} =====")
    try:
        res = produzir(cfg, tema, pasta, formato)
    except Exception as e:  # noqa: BLE001
        log.error(f"Produção interrompida: {e}")
        sys.exit(1)

    estado = {}
    if pub["youtube"] or pub["tiktok"] or pub["instagram"]:
        import main as motor
        estado = motor.publicar(cfg, res, pasta)
    else:
        log.info("Sem autorização de postagem cadastrada: vídeos prontos para baixar em Artifacts.")

    if not a.sem_publicar:
        hist = ler_historico(cfg)
        hist.append({"tema": tema, "titulo": res["roteiro"]["titulo"], "data": f"{datetime.now():%Y-%m-%d %H:%M}",
                     "publicacao": estado})
        salvar_historico(cfg, hist)
    log.info(f"===== Concluído: {pasta.name} =====")
    if any(k.endswith("_erro") for k in estado):
        sys.exit(2)


if __name__ == "__main__":
    main()
