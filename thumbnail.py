"""Thumbnail automática no estilo do Bino Explica (1280x720).

Fundo amarelo com faixas, frase curta gigante (com ? ou ! em vermelho), selo vermelho
(QUIZ, TOP 5, DESAFIO...), frase de apoio e a cena mais forte num cartão de papel.
"""
import re
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

from util import RAIZ

W, H = 1280, 720
AMARELO, FAIXA, PRETO, VERMELHO = "#FFC93C", "#FFD25C", "#1A1A1A", "#E0312B"
SELO_POR_FORMATO = {"quiz": "QUIZ", "top5": "TOP 5", "mito_ou_verdade": "MITO?", "explicacao": "CURIOSIDADE"}


def _fonte(tam):
    for p in [RAIZ / "assets/fontes/Poppins-Black.ttf", "/usr/share/fonts/opentype/inter/InterDisplay-Black.otf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]:
        try:
            return ImageFont.truetype(str(p), tam)
        except OSError:
            continue
    return ImageFont.load_default()


def _limpar(t):
    t = re.sub(r"[\U0001F000-\U0001FFFF☀-➿️]", "", t or "")
    return re.sub(r"\s+", " ", t).strip()


def texto_padrao(rot) -> str:
    """Quando o roteiro não traz a frase da thumbnail: usa o título curto, cortado em até 4 palavras."""
    base = _limpar(rot.get("curto", {}).get("titulo") or rot.get("titulo", ""))
    base = re.split(r"[|:\-–(]", base)[0].strip() or base
    palavras = base.split()
    if len(palavras) > 4:
        fim = "?" if base.endswith("?") else ""
        base = " ".join(palavras[:4]) + fim
    return base.upper()


def cena_mais_forte(cenas: list) -> int:
    """Escolhe a cena com mais desenho (mais 'tinta'), evitando a primeira se houver opção."""
    melhor, idx = -1, 0
    for i, p in enumerate(cenas):
        try:
            img = Image.open(p).convert("L").resize((160, 90))
        except OSError:
            continue
        tinta = sum(1 for v in img.getdata() if v < 200)
        if i == 0:
            tinta *= 0.8
        if tinta > melhor:
            melhor, idx = tinta, i
    return idx


def _quebrar_em_2(texto, f, d, largura):
    if d.textlength(texto, font=f) <= largura or " " not in texto:
        return [texto]
    palavras = texto.split()
    melhor = None
    for k in range(1, len(palavras)):
        a, b = " ".join(palavras[:k]), " ".join(palavras[k:])
        pior = max(d.textlength(a, font=f), d.textlength(b, font=f))
        if melhor is None or pior < melhor[0]:
            melhor = (pior, [a, b])
    return melhor[1]


def gerar(cena_png: Path, texto: str, destino: Path, selo: str = "", frase: str = "") -> Path:
    # desenho recortado (tira as bordas brancas)
    cena = Image.open(cena_png).convert("RGBA")
    fundo = Image.new("RGBA", cena.size, "white")
    fundo.alpha_composite(cena)
    cena = fundo.convert("RGB")
    caixa = ImageChops.difference(cena, Image.new("RGB", cena.size, "white")).convert("L") \
        .point(lambda x: 255 if x > 20 else 0).getbbox()
    if caixa:
        m = 50
        cena = cena.crop((max(0, caixa[0] - m), max(0, caixa[1] - m),
                          min(cena.width, caixa[2] + m), min(cena.height, caixa[3] + m)))

    img = Image.new("RGB", (W, H), AMARELO)
    d = ImageDraw.Draw(img)
    for k in range(0, W + H, 90):
        d.line([(k, 0), (k - H, H)], fill=FAIXA, width=34)

    # cartão de papel com o desenho
    cx0, cy0, cx1, cy1 = 650, 70, 1240, 650
    sombra = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(sombra).rounded_rectangle((cx0 + 14, cy0 + 16, cx1 + 14, cy1 + 16), 28, fill=(0, 0, 0, 110))
    img = Image.alpha_composite(img.convert("RGBA"), sombra.filter(ImageFilter.GaussianBlur(6))).convert("RGB")
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((cx0, cy0, cx1, cy1), 28, fill="white", outline=PRETO, width=8)
    aw, ah = cx1 - cx0 - 36, cy1 - cy0 - 36
    esc = min(aw / cena.width, ah / cena.height)
    c = cena.resize((max(1, int(cena.width * esc)), max(1, int(cena.height * esc))), Image.LANCZOS)
    img.paste(c, (cx0 + 18 + (aw - c.width) // 2, cy0 + 18 + (ah - c.height) // 2))
    d = ImageDraw.Draw(img)

    # frase principal: até 2 linhas, o maior tamanho que caiba
    X, LARG = 44, 570
    texto = _limpar(texto).upper() or "VOCÊ SABIA?"
    tam = 150
    while tam > 60:
        f = _fonte(tam)
        linhas = _quebrar_em_2(texto, f, d, LARG)
        if len(linhas) <= 2 and all(d.textlength(l, font=f) <= LARG for l in linhas):
            break
        tam -= 4
    f = _fonte(tam)
    linhas = _quebrar_em_2(texto, f, d, LARG)[:2]
    y = 80 if len(linhas) == 2 else 150
    for i, ln in enumerate(linhas):
        fim = ln[-1] if ln[-1:] in "?!" and i == len(linhas) - 1 else ""
        corpo = ln[:-1].rstrip() if fim else ln
        d.text((X, y), corpo, font=f, fill=PRETO, stroke_width=10, stroke_fill="white")
        if fim:
            d.text((X + d.textlength(corpo + " ", font=f) - tam * 0.12, y), fim, font=f, fill=VERMELHO,
                   stroke_width=10, stroke_fill="white")
        y += int(tam * 1.02)

    # selo vermelho
    y += 18
    if selo:
        fs = _fonte(52)
        tw = int(d.textlength(selo, font=fs))
        sl = Image.new("RGBA", (tw + 70, 104), (0, 0, 0, 0))
        ds = ImageDraw.Draw(sl)
        ds.rounded_rectangle((8, 8, tw + 62, 96), 22, fill=VERMELHO, outline=PRETO, width=7)
        ds.text((35, 18), selo, font=fs, fill="white")
        sl = sl.rotate(5, expand=True, resample=Image.BICUBIC)
        img.paste(sl, (X, y), sl)
        d = ImageDraw.Draw(img)
        y += 128
    if frase and y < H - 60:
        ff = _fonte(40)
        for ln in _quebrar_em_2(_limpar(frase), ff, d, LARG)[:2]:
            d.text((X + 4, y), ln, font=ff, fill=PRETO)
            y += 48

    destino = Path(destino)
    img.save(destino, quality=92) if destino.suffix.lower() in (".jpg", ".jpeg") else img.save(destino, optimize=True)
    return destino


def para_roteiro(rot: dict, cenas: list, destino: Path) -> Path:
    """Monta a thumbnail a partir do roteiro (usa rot['miniatura'] se a IA mandou)."""
    mini = rot.get("miniatura") or {}
    try:
        idx = int(mini.get("cena"))
        if not 0 <= idx < len(cenas):
            raise ValueError
    except (TypeError, ValueError):
        idx = cena_mais_forte(cenas)
    texto = mini.get("texto") or texto_padrao(rot)
    selo = mini.get("selo") or SELO_POR_FORMATO.get(rot.get("formato") or "", "")
    frase = mini.get("frase", "")
    return gerar(cenas[idx], texto, destino, selo=selo.upper()[:14], frase=frase)
