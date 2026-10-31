"""Caso Ao Vivo — capa vertical 1080x1920 com a identidade do canal: apresentador 2D, frase curta e palavra-chave em vermelho."""
import re

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageOps

from caso_edicao import CHAVES_CANAL, f_impacto, f_mono, f_texto, largura
from util import RAIZ

W, H = 1080, 1920
VERMELHO = (232, 52, 64)


def frase_da_capa(caso, apoios):
    if caso.get("capa"):
        return str(caso["capa"]).strip()
    ap = apoios[0] if apoios and apoios[0] else None
    if ap and ap.get("valor") and len(ap["valor"]) <= 32:
        return ap["valor"]
    return caso["cenas"][0].get("tela_titulo") or caso.get("titulo_caso", "Caso real")


def _palavra_chave(palavras, caso):
    dest = {re.sub(r"[^\wÀ-ÿ%$]", "", x.lower()) for c in caso["cenas"] for d in c.get("destaques", []) for x in str(d).split()}
    for k, p in enumerate(palavras):
        lp = re.sub(r"[^\wÀ-ÿ%$]", "", p.lower())
        if lp in CHAVES_CANAL or lp in dest or re.search(r"\d", lp):
            return k
    return len(palavras) - 1


def gerar(caso, apoios, destino, foto=None):
    """Desenha a capa. foto: caminho de uma foto de arquivo (fica ao fundo, em preto e branco)."""
    capa = Image.new("RGB", (W, H), (10, 10, 13))
    if foto:
        try:
            f = ImageOps.grayscale(Image.open(foto)).convert("RGB")
            f = ImageOps.fit(f, (W, H), Image.LANCZOS)
            capa = Image.blend(capa, ImageEnhance.Brightness(f).enhance(0.55), 0.55)
        except Exception:  # noqa: BLE001
            pass
    # brilho vermelho atrás do apresentador e vinheta
    luz = Image.new("L", (W, H), 0)
    ImageDraw.Draw(luz).ellipse([W * 0.25, H * 0.42, W * 1.25, H * 1.15], fill=150)
    luz = luz.filter(ImageFilter.GaussianBlur(160))
    capa = Image.composite(Image.new("RGB", (W, H), (120, 14, 24)), capa, luz)
    vin = Image.new("L", (W, H), 0)
    ImageDraw.Draw(vin).rectangle([0, 0, W, H], fill=0)
    ImageDraw.Draw(vin).ellipse([-W * 0.3, -H * 0.15, W * 1.3, H * 1.15], fill=255)
    capa = Image.composite(capa, Image.new("RGB", (W, H), (0, 0, 0)), vin.filter(ImageFilter.GaussianBlur(220)))

    # apresentador (mesma arte do vídeo, sem alterar o personagem)
    ap = Image.open(RAIZ / "assets" / "caso" / "apresentador.png").convert("RGBA")
    alt = int(H * 0.62)
    ap = ap.resize((int(ap.width * alt / ap.height), alt), Image.LANCZOS)
    m = 90
    alfa = Image.new("L", (ap.width + 2 * m, ap.height + 2 * m), 0)
    alfa.paste(ap.getchannel("A").point(lambda a: int(a * 0.6)), (m, m))
    alfa = alfa.filter(ImageFilter.GaussianBlur(26))
    x, y = W - ap.width - 10, H - alt + 40
    capa.paste((0, 0, 0), (x - 24 - m, y + 20 - m), alfa)
    capa.paste(ap, (x, y), ap)

    d = ImageDraw.Draw(capa)
    # selo do canal
    d.ellipse([64, 132, 82, 150], fill=VERMELHO)
    d.text((100, 141), "CASO REAL", font=f_mono(30), fill=(235, 235, 238), anchor="lm")
    marca = caso.get("marca", "")
    if marca:
        d.text((100 + largura("CASO REAL", f_mono(30)) + 26, 141), marca, font=f_texto(30), fill=(200, 204, 214), anchor="lm")

    # frase curta em até 3 linhas, uma palavra-chave em vermelho
    frase = frase_da_capa(caso, apoios).upper()
    palavras = frase.split()
    chave = _palavra_chave(palavras, caso)
    tam = 190
    while True:
        f = f_impacto(tam)
        linhas, cur = [], []
        for k, p in enumerate(palavras):
            teste = cur + [(k, p)]
            if cur and largura(" ".join(x for _, x in teste), f) > W - 140:
                linhas.append(cur)
                cur = [(k, p)]
            else:
                cur = teste
        if cur:
            linhas.append(cur)
        a_, d_ = f.getmetrics()
        if (len(linhas) <= 3 and 260 + len(linhas) * (a_ + d_) * 0.95 <= 800) or tam <= 90:
            break
        tam -= 10
    asc, desc = f.getmetrics()
    y = 260 + asc
    esp = largura(" ", f)
    for ln in linhas:
        xx = 70
        for k, p in ln:
            cor = VERMELHO if k == chave else (255, 255, 255)
            d.text((xx + 6, y + 8), p, font=f, fill=(0, 0, 0), anchor="ls")
            d.text((xx, y), p, font=f, fill=cor, anchor="ls", stroke_width=4, stroke_fill=(0, 0, 0))
            xx += largura(p, f) + esp
        y += int((asc + desc) * 0.95)
    d.rectangle([70, y - asc * 0.25 + 30, 250, y - asc * 0.25 + 38], fill=VERMELHO)
    capa.save(destino, quality=92)
    return destino
