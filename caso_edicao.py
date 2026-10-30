"""
Caso Ao Vivo — edição profissional no estilo dos canais dark de investigação.

O que este módulo faz com as falas narradas:
- planos alternados do apresentador (aberto, médio e fechado), com movimento de câmera e paralaxe;
- cenas de apoio em motion graphics: número que conta, mapa com alvo, linha do tempo,
  documento datilografado, revelação em tipografia cinética e cartão final;
- cortes com flash e separação de cores, color grading frio/quente, grão de filme e vinheta;
- legendas por palavra sincronizadas com a voz, com palavras-chave em destaque e áreas seguras;
- trilha atmosférica com ducking, efeitos sonoros nos cortes e volume normalizado (-14 LUFS).

Tudo é desenhado aqui (Pillow + ffmpeg). Nenhuma imagem de terceiros é usada.
"""
import array
import math
import multiprocessing
import os
import random
import re
import subprocess
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

RAIZ = Path(__file__).resolve().parent
ASSETS = RAIZ / "assets" / "caso"
FONTES = RAIZ / "assets" / "fontes"
FPS = 30

OURO = (214, 175, 98)
OURO_VIVO = (247, 201, 96)
VERMELHO = (226, 48, 62)
TEXTO = (242, 239, 232)
APAGADO = (150, 158, 172)
TIPOS = ("numero", "local", "data", "documento", "revelacao", "pergunta", "cartao")


# =====================================================================
# utilidades
# =====================================================================
def clamp(x, a=0.0, b=1.0):
    return a if x < a else b if x > b else x


def ease_out(x):
    x = clamp(x)
    return 1 - (1 - x) ** 3


def suave(x):
    x = clamp(x)
    return x * x * (3 - 2 * x)


def _h(n):
    n = (int(n) * 2654435761) & 0xFFFFFFFF
    return (n ^ (n >> 13)) & 0xFFFFFFFF


_cache_fontes = {}


def _fonte(nomes, tam, variacao=None):
    tam = max(8, int(tam))
    chave = (tuple(nomes), tam, variacao)
    if chave in _cache_fontes:
        return _cache_fontes[chave]
    fonte = None
    for n in nomes:
        for base in (FONTES, Path("/usr/share/fonts/truetype/dejavu")):
            p = base / n
            if p.exists():
                try:
                    fonte = ImageFont.truetype(str(p), tam)
                    if variacao:
                        try:
                            fonte.set_variation_by_name(variacao)
                        except Exception:  # noqa: BLE001
                            pass
                    break
                except OSError:
                    fonte = None
        if fonte:
            break
    fonte = fonte or ImageFont.load_default(tam)
    _cache_fontes[chave] = fonte
    return fonte


def f_impacto(t): return _fonte(["Anton-Regular.ttf", "DejaVuSans-Bold.ttf"], t)
def f_serif(t): return _fonte(["DMSerifDisplay-Regular.ttf", "DejaVuSerif.ttf"], t)
def f_mono(t): return _fonte(["JetBrainsMono-Bold.ttf", "DejaVuSansMono-Bold.ttf"], t, "Bold")
def f_texto(t): return _fonte(["Rubik[wght].ttf", "Rubik-Medium.ttf", "DejaVuSans.ttf"], t, "Medium")
def f_maquina(t): return _fonte(["JetBrainsMono-Bold.ttf", "DejaVuSansMono.ttf"], t, "Regular")


_D = ImageDraw.Draw(Image.new("RGB", (1, 1)))


def largura(texto, fonte, esp=0):
    return _D.textlength(texto, font=fonte) + esp * max(0, len(texto) - 1)


def quebrar(texto, fonte, larg, esp=0):
    linhas, cur = [], ""
    for p in str(texto).split():
        t = f"{cur} {p}".strip()
        if largura(t, fonte, esp) > larg and cur:
            linhas.append(cur)
            cur = p
        else:
            cur = t
    if cur:
        linhas.append(cur)
    return linhas


def ajustar(fabrica, texto, tam_max, larg, tam_min=24):
    tam = tam_max
    while tam > tam_min and largura(texto, fabrica(tam)) > larg:
        tam -= 4
    return fabrica(tam)


class Sprite:
    """Texto pronto para colar: imagem RGBA e a posição da linha de base dentro dela."""

    def __init__(self, texto, fonte, cor, esp=0, contorno=0, cor_contorno=(0, 0, 0, 255), sombra=0, alfa_sombra=160):
        asc, desc = fonte.getmetrics()
        pad = contorno + sombra * 3 + 4
        self.larg_texto = largura(texto, fonte, esp)
        w = int(self.larg_texto) + 2 * pad
        h = asc + desc + 2 * pad
        self.img = Image.new("RGBA", (max(1, w), max(1, h)), (0, 0, 0, 0))
        self.base = pad + asc
        self.pad = pad

        def escrever(d, y, fill, stroke, sfill):
            x = pad
            if esp:
                for ch in texto:
                    d.text((x, y), ch, font=fonte, fill=fill, anchor="ls", stroke_width=stroke, stroke_fill=sfill)
                    x += _D.textlength(ch, font=fonte) + esp
            else:
                d.text((x, y), texto, font=fonte, fill=fill, anchor="ls", stroke_width=stroke, stroke_fill=sfill)

        if sombra:
            s = Image.new("RGBA", self.img.size, (0, 0, 0, 0))
            escrever(ImageDraw.Draw(s), self.base + sombra, (0, 0, 0, alfa_sombra), contorno, (0, 0, 0, alfa_sombra))
            self.img.alpha_composite(s.filter(ImageFilter.GaussianBlur(sombra)))
        escrever(ImageDraw.Draw(self.img), self.base, cor if len(cor) == 4 else cor + (255,), contorno, cor_contorno)

    def colar(self, base, x, y_base, alinhar="m", alfa=1.0):
        """x é o centro (m), a esquerda (l) ou a direita (r) do texto; y_base é a linha de base."""
        if alinhar == "m":
            x0 = x - self.larg_texto / 2 - self.pad
        elif alinhar == "r":
            x0 = x - self.larg_texto - self.pad
        else:
            x0 = x - self.pad
        colar(base, self.img, x0, y_base - self.base, alfa)


def colar(base, camada, x, y, alfa=1.0):
    if alfa <= 0.01:
        return
    x, y = int(round(x)), int(round(y))
    if base.mode == "RGB":
        mascara = camada.getchannel("A")
        if alfa < 0.99:
            mascara = mascara.point(lambda v, a=alfa: int(v * a))
        base.paste(camada, (x, y), mascara)
        return
    if alfa < 0.99:
        camada = camada.copy()
        camada.putalpha(camada.getchannel("A").point(lambda v, a=alfa: int(v * a)))
    bx0, by0 = max(0, x), max(0, y)
    bx1, by1 = min(base.width, x + camada.width), min(base.height, y + camada.height)
    if bx1 <= bx0 or by1 <= by0:
        return
    if (bx0, by0, bx1, by1) != (x, y, x + camada.width, y + camada.height):
        camada = camada.crop((bx0 - x, by0 - y, bx1 - x, by1 - y))
    base.alpha_composite(camada, (bx0, by0))


def gradiente_v(w, h, topo, base):
    g = Image.linear_gradient("L").resize((w, h))
    return Image.merge("RGB", [g.point(lambda v, a=a, b=b: int(a + (b - a) * v / 255)) for a, b in zip(topo, base)])


def brilho(w, h, cx, cy, r, cor, alfa):
    """Camada RGBA com luz radial (alfa máximo no centro)."""
    g = Image.radial_gradient("L").resize((max(2, int(r * 2)), max(2, int(r * 2))))
    g = g.point(lambda v: int(alfa * clamp(1 - v / 255) ** 1.6))
    camada = Image.new("RGBA", (w, h), cor + (0,))
    a = Image.new("L", (w, h), 0)
    a.paste(g, (int(cx - r), int(cy - r)))
    camada.putalpha(a)
    return camada


def _lut():
    canais = ([], [], [])
    for v in range(256):
        x = v / 255
        c = 0.62 * x + 0.38 * (x * x * (3 - 2 * x))       # curva em S (contraste)
        sombra, luz = (1 - c) ** 2, c ** 3
        canais[0].append(int(clamp(c - 0.014 * sombra + 0.040 * luz) * 255))
        canais[1].append(int(clamp(c + 0.012 * sombra + 0.006 * luz) * 255))
        canais[2].append(int(clamp(c + 0.045 * sombra - 0.035 * luz) * 255))
    return canais[0] + canais[1] + canais[2]


LUT = _lut()


def graduar(img):
    """Color grading: sombras levemente azuladas, luzes quentes, contraste de cinema."""
    return img.convert("RGB").point(LUT).convert("RGBA")


def vinheta(w, h, forca=175):
    g = Image.radial_gradient("L").resize((int(w * 1.45), int(h * 1.45)))
    g = g.crop(((g.width - w) // 2, (g.height - h) // 2, (g.width - w) // 2 + w, (g.height - h) // 2 + h))
    g = g.point(lambda v: int(forca * clamp((v - 85) / 170) ** 1.5))
    camada = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    camada.putalpha(g)
    return camada


def grao(img, forca=11):
    """Grão de filme fixo (leve na compressão do vídeo)."""
    w, h = img.size
    r = Image.frombytes("L", (w // 2, h // 2), random.Random(5).randbytes((w // 2) * (h // 2))).resize((w, h), Image.NEAREST)
    camada = Image.merge("RGBA", (r, r, r, Image.new("L", (w, h), forca)))
    base = img.convert("RGBA")
    base.alpha_composite(camada)
    return base.convert("RGB")


def painel(w, h, raio=16, fundo=(9, 12, 18, 205), borda=(214, 175, 98, 70)):
    img = Image.new("RGBA", (max(1, int(w)), max(1, int(h))), (0, 0, 0, 0))
    ImageDraw.Draw(img).rounded_rectangle([0, 0, img.width - 1, img.height - 1], raio, fill=fundo, outline=borda, width=2)
    return img


# =====================================================================
# layout (1080x1920 vertical, 1920x1080 horizontal)
# =====================================================================
def layout(vertical, reels=False):
    if vertical:
        W, H = 1080, 1920
        return dict(W=W, H=H, vertical=True, M=150,
                    topo=int(H * (0.15 if reels else 0.105)),        # abaixo das abas do app
                    leg_x=int(W * 0.47), leg_y=int(H * (0.60 if reels else 0.655)), leg_larg=W * 0.76, leg_tam=84,
                    gx=int(W * 0.47), gy=int(H * 0.40), gw=W * 0.78,  # área das artes (longe dos ícones da direita)
                    chao=int(H * 0.915), alt=int(H * 0.56), cx=W * 0.5,
                    chip=(60, int(H * (0.15 if reels else 0.105)) + 64, int(W * 0.74)))
    W, H = 1920, 1080
    return dict(W=W, H=H, vertical=False, M=150, topo=48,
                leg_x=W // 2, leg_y=int(H * 0.87), leg_larg=W * 0.70, leg_tam=74,
                gx=W // 2, gy=int(H * 0.42), gw=W * 0.70,
                chao=int(H * 0.90), alt=int(H * 0.82), cx=W * 0.30,
                chip=(int(W * 0.55), int(H * 0.20), int(W * 0.38)))


# =====================================================================
# cenário do apresentador
# =====================================================================
def placa_estudio(L, semente):
    """Estúdio de investigação: mural de evidências fora de foco, contraluz, feixe de refletor e palco."""
    W, H, M = L["W"], L["H"], L["M"]
    PW, PH = W + 2 * M, H + 2 * M
    rnd = random.Random(semente)
    img = gradiente_v(PW, PH, (14, 18, 26), (8, 9, 13)).convert("RGBA")

    # mural (desfocado: profundidade de campo)
    mural = Image.new("RGBA", (PW, PH), (0, 0, 0, 0))
    d = ImageDraw.Draw(mural)
    if L["vertical"]:
        x0, x1, y0, y1 = M - 60, M + W + 60, M + int(H * 0.03), M + int(H * 0.64)
        cols, rows = 4, 5
    else:
        x0, x1, y0, y1 = M + int(W * 0.04), M + W + 60, M + int(H * 0.04), M + int(H * 0.80)
        cols, rows = 7, 3
    d.rectangle([x0, y0, x1, y1], fill=(46, 35, 28, 255))
    for _ in range(1400):
        x, y = rnd.randint(x0, x1), rnd.randint(y0, y1)
        d.point((x, y), fill=(66, 50, 38, 255))
    base = min(W, H)
    pins = []
    cw, rh = (x1 - x0) / cols, (y1 - y0) / rows
    for r in range(rows):
        for c in range(cols):
            if rnd.random() < 0.18:
                continue
            cx = x0 + cw * (c + 0.5) + rnd.uniform(-cw * 0.2, cw * 0.2)
            cy = y0 + rh * (r + 0.5) + rnd.uniform(-rh * 0.2, rh * 0.2)
            tipo = rnd.choice(["foto", "foto", "recorte", "recorte", "nota", "ficha", "mapa"])
            if tipo == "foto":
                w, h = base * 0.15, base * 0.18
                d.rectangle([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2], fill=(222, 218, 208, 255))
                d.rectangle([cx - w / 2 + 10, cy - h / 2 + 10, cx + w / 2 - 10, cy + h / 2 - 34], fill=(36, 42, 52, 255))
                d.ellipse([cx - w * 0.16, cy - h * 0.30, cx + w * 0.16, cy - h * 0.02], fill=(66, 74, 88, 255))
                d.pieslice([cx - w * 0.32, cy - h * 0.02, cx + w * 0.32, cy + h * 0.42], 180, 360, fill=(66, 74, 88, 255))
            elif tipo == "recorte":
                w, h = base * 0.20, base * 0.15
                d.rectangle([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2], fill=(204, 196, 176, 255))
                d.rectangle([cx - w / 2 + 12, cy - h / 2 + 12, cx + w / 2 - 12, cy - h / 2 + 30], fill=(60, 56, 50, 255))
                for k in range(5):
                    yy = cy - h / 2 + 44 + k * 16
                    d.rectangle([cx - w / 2 + 12, yy, cx + w / 2 - 12 - rnd.randint(0, 40), yy + 5], fill=(140, 134, 120, 255))
            elif tipo == "nota":
                w = h = base * 0.10
                d.rectangle([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2], fill=(214, 182, 86, 255))
                for k in range(3):
                    yy = cy - h / 4 + k * 18
                    d.line([cx - w / 3, yy, cx + w / 3 - k * 10, yy + 3], fill=(110, 84, 30, 255), width=3)
            elif tipo == "ficha":
                w, h = base * 0.17, base * 0.11
                d.rectangle([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2], fill=(232, 230, 224, 255))
                d.line([cx - w / 2, cy - h / 2 + 22, cx + w / 2, cy - h / 2 + 22], fill=(190, 60, 60, 255), width=3)
                for k in range(3):
                    yy = cy - h / 2 + 40 + k * 16
                    d.line([cx - w / 2 + 10, yy, cx + w / 2 - 10, yy], fill=(150, 170, 190, 255), width=2)
            else:
                w, h = base * 0.22, base * 0.16
                d.rectangle([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2], fill=(58, 76, 82, 255))
                for k in range(6):
                    xa = cx - w / 2 + rnd.uniform(0, w)
                    d.line([xa, cy - h / 2, xa + rnd.uniform(-30, 30), cy + h / 2], fill=(84, 104, 110, 255), width=3)
                d.ellipse([cx - 8, cy - 8, cx + 8, cy + 8], fill=(200, 50, 50, 255))
            pins.append((cx, cy - (h / 2 if tipo != "mapa" else 0) + 6))
    for _ in range(min(9, len(pins) // 2 + 2)):
        a, b = rnd.sample(pins, 2) if len(pins) >= 2 else (pins[0], pins[0])
        d.line([a, b], fill=(186, 36, 44, 255), width=4)
    for x, y in pins:
        d.ellipse([x - 7, y - 7, x + 7, y + 7], fill=(206, 40, 48, 255))
    mural = mural.filter(ImageFilter.GaussianBlur(9))
    img.alpha_composite(mural)
    img.alpha_composite(Image.new("RGBA", (PW, PH), (6, 8, 12, 120)))      # mural mais escuro que o apresentador

    cx, chao, alt = M + L["cx"], M + L["chao"], L["alt"]
    # contraluz atrás do apresentador (separa ele do fundo)
    img.alpha_composite(brilho(PW, PH, cx, chao - alt * 0.62, alt * 0.55, (255, 214, 160), 80))
    # feixe do refletor (luz volumétrica)
    feixe = Image.new("RGBA", (PW, PH), (0, 0, 0, 0))
    meia = alt * 0.40
    ImageDraw.Draw(feixe).polygon([(cx - 40, 0), (cx + 40, 0), (cx + meia, chao), (cx - meia, chao)], fill=(255, 232, 200, 34))
    img.alpha_composite(feixe.filter(ImageFilter.GaussianBlur(28)))
    # chão e palco
    chao_img = gradiente_v(PW, PH - chao, (14, 15, 20), (6, 7, 10)).convert("RGBA")
    img.alpha_composite(chao_img, (0, chao))
    rx, ry = alt * 0.36, alt * 0.05
    palco = Image.new("RGBA", (PW, PH), (0, 0, 0, 0))
    ImageDraw.Draw(palco).ellipse([cx - rx, chao - ry, cx + rx, chao + ry], fill=(255, 228, 190, 46))
    img.alpha_composite(palco.filter(ImageFilter.GaussianBlur(14)))
    aro = Image.new("RGBA", (PW, PH), (0, 0, 0, 0))
    ImageDraw.Draw(aro).ellipse([cx - rx, chao - ry, cx + rx, chao + ry], outline=OURO + (130,), width=2)
    img.alpha_composite(aro)
    img = graduar(img)
    img.alpha_composite(vinheta(PW, PH, 150))
    return grao(img)


def fundo_grafico(L, estudio, tom="ouro"):
    """Fundo das artes: o estúdio bem desfocado e escuro, grade fina e uma luz de cor."""
    W, H, M = L["W"], L["H"], L["M"]
    img = estudio.crop((M, M, M + W, M + H)).filter(ImageFilter.GaussianBlur(22)).convert("RGBA")
    img.alpha_composite(Image.new("RGBA", (W, H), (5, 7, 11, 175)))
    grade = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(grade)
    for x in range(0, W, 72):
        d.line([x, 0, x, H], fill=(255, 255, 255, 9))
    for y in range(0, H, 72):
        d.line([0, y, W, y], fill=(255, 255, 255, 9))
    img.alpha_composite(grade)
    cor = {"ouro": (214, 160, 80), "frio": (70, 130, 170), "vermelho": (200, 40, 50)}[tom]
    img.alpha_composite(brilho(W, H, L["gx"], L["gy"], max(W, H) * 0.45, cor, 60))
    img = graduar(img)
    img.alpha_composite(vinheta(W, H, 190))
    return grao(img)


class _Zoom:
    def __init__(self, L):
        self.L = L
        self._cz = {}

    def zoom(self, img, z, foco=None):
        chave = (id(img), round(z * 250) / 250)
        z = chave[1]
        if chave not in self._cz:
            W, H = img.size
            fx, fy = foco or (W / 2, H / 2)
            box = (fx - fx / z, fy - fy / z, fx - fx / z + W / z, fy - fy / z + H / z)
            self._cz[chave] = img.resize((self.L["W"], self.L["H"]), Image.BILINEAR, box=box)
            if len(self._cz) > 50:
                self._cz.pop(next(iter(self._cz)))
        return self._cz[chave].copy()


# =====================================================================
# apresentador
# =====================================================================
ENQUADRAMENTOS = {
    # zoom, ponto de foco (fração da altura do corpo, a partir do chão), posição na tela (fração)
    "aberto": (1.00, None, None),
    "medio": (1.55, 0.64, (0.50, 0.47)),
    "fechado": (2.10, 0.84, (0.50, 0.40)),
}


class Apresentador:
    def __init__(self, L, estudio):
        self.L, self.estudio = L, estudio
        self.fig = Image.open(ASSETS / "apresentador.png").convert("RGBA")
        self.boca = Image.open(ASSETS / "boca_fechada.png").convert("RGBA")
        self.s0 = L["alt"] / self.fig.height
        self._cf, self._cb, self._cbg = {}, {}, {}

    def _geometria(self, enq, z_extra):
        L = self.L
        Z, f_alt, ancora = ENQUADRAMENTOS[enq]
        if f_alt is None:
            foco = (L["cx"], L["chao"] - L["alt"] * 0.5)
            ancora_px = foco
        else:
            foco = (L["cx"], L["chao"] - L["alt"] * f_alt)
            ax = ancora[0] if L["vertical"] else ancora[0] - 0.14     # no horizontal ele fica à esquerda
            ancora_px = (L["W"] * ax, L["H"] * ancora[1])
        return Z * z_extra, foco, ancora_px

    def quadro(self, enq, z_extra, bob, boca_fechada):
        L, M = self.L, self.L["M"]
        Ze, (fx, fy), (ax, ay) = self._geometria(enq, z_extra)
        # fundo com paralaxe (o mural se move menos que o apresentador)
        Zb = round((1 + (Ze - 1) * 0.30) * 500) / 500
        kb = (enq, Zb)
        if kb not in self._cbg:
            bw, bh = L["W"] / Zb, L["H"] / Zb
            bx = min(max(0.0, M + fx - ax / Zb), self.estudio.width - bw)
            by = min(max(0.0, M + fy - ay / Zb), self.estudio.height - bh)
            box = (bx, by, bx + bw, by + bh)
            self._cbg[kb] = self.estudio.resize((L["W"], L["H"]), Image.BILINEAR, box=box)
            if len(self._cbg) > 40:
                self._cbg.pop(next(iter(self._cbg)))
        fr = self._cbg[kb].copy()
        # corpo
        S = round(self.s0 * Ze * 200) / 200
        if S not in self._cf:
            self._cf[S] = self.fig.resize((max(1, int(self.fig.width * S)), max(1, int(self.fig.height * S))), Image.BICUBIC)
            self._cb[S] = self.boca.resize((max(1, int(self.boca.width * S)), max(1, int(self.boca.height * S))), Image.BICUBIC)
            if len(self._cf) > 30:
                k = next(iter(self._cf))
                self._cf.pop(k)
                self._cb.pop(k)
        wx = L["cx"] - self.fig.width * self.s0 / 2
        wy = L["chao"] - L["alt"] + bob
        sx, sy = (wx - fx) * Ze + ax, (wy - fy) * Ze + ay
        colar(fr, self._cf[S], sx, sy)
        if boca_fechada:
            colar(fr, self._cb[S], sx + 225 * S, sy + 191 * S)
        return fr


# =====================================================================
# artes de apoio
# =====================================================================
def _num_br(v, dec, milhar):
    s = f"{v:,.{dec}f}"
    s = s.replace(",", "X").replace(".", ",").replace("X", ".")
    return s if milhar else s.replace(".", "")


class GNumero(_Zoom):
    """Número que conta até o valor (ou um título forte, quando não há número)."""

    def __init__(self, L, fundo, valor, rotulo, idx):
        super().__init__(L)
        self.fundo = fundo
        W = L["W"]
        self.kicker = Sprite(f"EVIDÊNCIA {idx + 1:02d}", f_mono(24), OURO, esp=5)
        m = re.search(r"\d[\d.]*(,\d+)?", valor)
        self.conta = None
        if m:
            bruto = m.group()
            dec = len(m.group(1)) - 1 if m.group(1) else 0
            try:
                v = float(bruto.replace(".", "").replace(",", "."))
            except ValueError:
                v = None
            ano = dec == 0 and v is not None and 1800 <= v <= 2100 and "." not in bruto
            if v is not None and v >= 10 and not ano:
                self.conta = (v, dec, "." in bruto)
            self.linha1 = (valor[:m.start()] + bruto).upper().strip()
            self.pre = valor[:m.start()].upper()
            self.linha2 = valor[m.end():].strip(" .,").upper()
        else:
            self.linha1, self.pre, self.linha2 = valor.upper(), "", ""
        self.f1 = ajustar(f_impacto, self.linha1 + "0", 230, L["gw"])
        if not m and len(self.linha1) > 16:
            self.f1 = ajustar(f_serif, valor, 120, L["gw"])
            self.linha1 = valor
        self.s2 = Sprite(self.linha2, ajustar(f_mono, self.linha2, 46, L["gw"]), TEXTO, esp=8) if self.linha2 else None
        self.rot = [Sprite(l, f_texto(36), APAGADO) for l in quebrar(rotulo, f_texto(36), L["gw"])[:2]]
        self._cache = {}

    def _s1(self, txt):
        if txt not in self._cache:
            self._cache[txt] = Sprite(txt, self.f1, TEXTO, sombra=12, alfa_sombra=200)
            if len(self._cache) > 80:
                self._cache.pop(next(iter(self._cache)))
        return self._cache[txt]

    def quadro(self, tl, dur):
        L = self.L
        fr = self.zoom(self.fundo, 1 + 0.05 * suave(tl / max(dur, 0.1)), (L["gx"], L["gy"]))
        gx, gy = L["gx"], L["gy"]
        asc = self.f1.getmetrics()[0]
        y_num = gy + asc * 0.35
        self.kicker.colar(fr, gx, y_num - asc - 40, alfa=ease_out(tl / 0.3))
        if self.conta:
            v, dec, mil = self.conta
            txt = self.pre + _num_br(v * ease_out((tl - 0.08) / 1.1), dec, mil)
        else:
            txt = self.linha1
        s = self._s1(txt)
        a = ease_out(tl / 0.28)
        s.colar(fr, gx, y_num + (1 - a) * 30, alfa=a)
        y = y_num + 40
        if self.s2:
            self.s2.colar(fr, gx, y + 46, alfa=ease_out((tl - 0.35) / 0.35))
            y += 70
        larg = 260 * ease_out((tl - 0.3) / 0.6)
        if larg > 2:
            ImageDraw.Draw(fr).rectangle([gx - larg / 2, y + 22, gx + larg / 2, y + 26], fill=OURO + (255,))
        for k, sp in enumerate(self.rot):
            sp.colar(fr, gx, y + 84 + k * 46, alfa=ease_out((tl - 0.6) / 0.4))
        return fr


def _mapa(w, h, semente):
    rnd = random.Random(semente)
    img = Image.new("RGB", (w, h), (15, 22, 28))
    d = ImageDraw.Draw(img)
    for _ in range(14):        # quarteirões e áreas verdes
        x, y = rnd.randint(0, w), rnd.randint(0, h)
        d.rectangle([x, y, x + rnd.randint(80, 260), y + rnd.randint(80, 260)], fill=rnd.choice([(19, 30, 34), (20, 36, 30)]))
    pts = []                   # rio
    y = rnd.uniform(h * 0.15, h * 0.35)
    for x in range(-50, w + 100, 60):
        y += rnd.uniform(-25, 25)
        pts.append((x, y + math.sin(x / 210) * 70))
    d.line(pts, fill=(16, 38, 56), width=74, joint="curve")
    d.line(pts, fill=(22, 50, 70), width=56, joint="curve")
    ang = rnd.uniform(-0.5, 0.5)
    for fam in (0, 1):         # malha de ruas em duas direções
        a = ang + fam * math.pi / 2
        dx, dy = math.cos(a), math.sin(a)
        nx, ny = -dy, dx
        diag = math.hypot(w, h)
        off = -diag
        while off < diag:
            off += rnd.uniform(46, 120)
            cx, cy = w / 2 + nx * off, h / 2 + ny * off
            larga = rnd.random() < 0.12
            d.line([cx - dx * diag, cy - dy * diag, cx + dx * diag, cy + dy * diag],
                   fill=(52, 70, 78) if larga else (33, 46, 54), width=12 if larga else rnd.choice([3, 4, 5]))
    return img.filter(ImageFilter.GaussianBlur(0.8))


class GLocal(_Zoom):
    """Mapa ilustrativo (não é o mapa real) com alvo pulsando e o nome do lugar."""

    def __init__(self, L, valor, rotulo, semente):
        super().__init__(L)
        W, H = L["W"], L["H"]
        mapa = graduar(_mapa(W, H, semente).convert("RGBA"))
        mapa.alpha_composite(vinheta(W, H, 210))
        self.mapa = grao(mapa)
        self.alvo = (L["gx"], int(L["gy"] + H * (0.06 if L["vertical"] else 0.02)))
        larg = min(L["gw"], max(largura(valor, f_serif(64)), largura(rotulo, f_texto(32))) + 96)
        linhas = quebrar(valor, f_serif(64), larg - 96)[:2]
        sub = quebrar(rotulo, f_texto(32), larg - 96)[:2]
        h = 132 + (len(linhas) - 1) * 70 + len(sub) * 42 + 40
        self.card = painel(larg, h)
        Sprite("LOCAL DO CASO", f_mono(22), OURO, esp=5).colar(self.card, 48, 62, "l")
        for k, l in enumerate(linhas):
            Sprite(l, f_serif(64), TEXTO).colar(self.card, 48, 132 + k * 70, "l")
        for k, l in enumerate(sub):
            Sprite(l, f_texto(32), APAGADO).colar(self.card, 48, 132 + (len(linhas) - 1) * 70 + 48 + 42 * k, "l")
        self.card_pos = (L["gx"] - larg / 2, L["topo"] + (90 if L["vertical"] else 20))
        if not L["vertical"]:
            self.card_pos = (W * 0.08, H * 0.16)
            self.alvo = (int(W * 0.62), int(H * 0.46))
        pino = Image.new("RGBA", (90, 120), (0, 0, 0, 0))
        d = ImageDraw.Draw(pino)
        d.ellipse([10, 4, 80, 74], fill=VERMELHO + (255,))
        d.polygon([(16, 52), (74, 52), (45, 112)], fill=VERMELHO + (255,))
        d.ellipse([31, 25, 59, 53], fill=(250, 240, 236, 255))
        self.pino = pino.resize((126, 168), Image.BICUBIC)

    def quadro(self, tl, dur):
        L = self.L
        z = 1 + 0.16 * suave(tl / max(dur, 0.1))
        fr = self.zoom(self.mapa, z, self.alvo)
        d = ImageDraw.Draw(fr)
        ax, ay = self.alvo
        d.line([0, ay, L["W"], ay], fill=(70, 110, 120, 255), width=1)
        d.line([ax, 0, ax, L["H"]], fill=(70, 110, 120, 255), width=1)
        aneis = Image.new("RGBA", (520, 520), (0, 0, 0, 0))
        da = ImageDraw.Draw(aneis)
        for k in range(3):
            f = ((tl * 0.7 + k / 3) % 1.0)
            r = 20 + f * 230
            da.ellipse([260 - r, 260 - r, 260 + r, 260 + r], outline=VERMELHO + (int(200 * (1 - f)),), width=4)
        colar(fr, aneis, ax - 260, ay - 260, alfa=ease_out((tl - 0.3) / 0.3))
        q = ease_out((tl - 0.25) / 0.35)
        colar(fr, self.pino, ax - 63, ay - 157 - (1 - q) * 160, alfa=q)
        e = ease_out((tl - 0.1) / 0.4)
        colar(fr, self.card, self.card_pos[0] - (1 - e) * 60, self.card_pos[1], alfa=e)
        return fr


class GData(_Zoom):
    """Linha do tempo com a data em destaque."""

    def __init__(self, L, fundo, valor, rotulo):
        super().__init__(L)
        self.fundo = fundo
        ano = re.search(r"\b(1[89]|20)\d\d\b", valor + " " + rotulo)
        self.marca = Sprite(ano.group(), f_impacto(int(L["H"] * (0.30 if L["vertical"] else 0.46))), (255, 255, 255, 14)) if ano else None
        self.kicker = Sprite("LINHA DO TEMPO", f_mono(24), OURO, esp=5)
        fd = ajustar(f_serif, valor, 120, L["gw"])
        self.datas = [Sprite(l, fd, TEXTO, sombra=10, alfa_sombra=200) for l in quebrar(valor, fd, L["gw"])[:2]]
        self.fd = fd
        self.rot = [Sprite(l, f_texto(36), APAGADO) for l in quebrar(rotulo, f_texto(36), L["gw"])[:3]]

    def quadro(self, tl, dur):
        L = self.L
        fr = self.zoom(self.fundo, 1 + 0.04 * suave(tl / max(dur, 0.1)))
        gx, gy, W = L["gx"], L["gy"], L["W"]
        if self.marca:
            self.marca.colar(fr, gx - 30 * suave(tl / max(dur, 0.1)), gy + self.marca.base * 0.32)
        y_linha = gy + 60
        x0, x1 = W * 0.07, W * (0.87 if L["vertical"] else 0.93)
        p = ease_out(tl / 0.6)
        d = ImageDraw.Draw(fr)
        xp = x0 + (x1 - x0) * p
        d.rectangle([x0, y_linha - 1, xp, y_linha + 1], fill=(200, 205, 215, 255))
        x = x0
        while x < xp:
            d.rectangle([x, y_linha - 8, x + 2, y_linha + 8], fill=(120, 126, 140, 255))
            x += 54
        if tl > 0.42:
            k = ease_out((tl - 0.42) / 0.25)
            r = 13 * k
            d.ellipse([gx - r, y_linha - r, gx + r, y_linha + r], fill=OURO + (255,))
            f = (tl - 0.42) % 1.2 / 1.2
            rr = 16 + 50 * f
            anel = Image.new("RGBA", (140, 140), (0, 0, 0, 0))
            ImageDraw.Draw(anel).ellipse([70 - rr, 70 - rr, 70 + rr, 70 + rr], outline=OURO + (int(220 * (1 - f)),), width=3)
            colar(fr, anel, gx - 70, y_linha - 70)
        a = ease_out((tl - 0.45) / 0.4)
        alt = self.fd.getmetrics()[0]
        topo_data = y_linha - 70 - (len(self.datas) - 1) * alt * 1.05
        self.kicker.colar(fr, gx, topo_data - alt - 30, alfa=ease_out(tl / 0.3))
        for k, s in enumerate(self.datas):
            s.colar(fr, gx, topo_data + k * alt * 1.05 + (1 - a) * 34, alfa=a)
        for k, s in enumerate(self.rot):
            s.colar(fr, gx, y_linha + 80 + k * 48, alfa=ease_out((tl - 0.75) / 0.4))
        return fr


class GDocumento(_Zoom):
    """Folha datilografada com o resumo de um fato noticiado e um carimbo de fonte."""

    def __init__(self, L, valor, rotulo, idx):
        super().__init__(L)
        W, H = L["W"], L["H"]
        mesa = gradiente_v(W, H, (34, 25, 20), (12, 9, 8)).convert("RGBA")
        veios = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(veios)
        rnd = random.Random(idx)
        for y in range(0, H, 11):
            d.line([0, y + rnd.randint(-3, 3), W, y + rnd.randint(-3, 3)], fill=(0, 0, 0, rnd.randint(10, 26)), width=2)
        mesa.alpha_composite(veios)
        mesa.alpha_composite(brilho(W, H, W * 0.5, H * 0.32, max(W, H) * 0.55, (255, 196, 130), 70))
        mesa = graduar(mesa)
        mesa.alpha_composite(vinheta(W, H, 200))
        self.mesa = grao(mesa)
        pw = int(W * (0.80 if L["vertical"] else 0.44))
        self.fonte = f_maquina(46 if L["vertical"] else 38)
        self.linhas = quebrar(valor, self.fonte, pw - 120)[:8]
        ph = int(340 + len(self.linhas) * 64)
        self.y_carimbo = 176 + (len(self.linhas) - 1) * 64 + 78
        papel = Image.new("RGBA", (pw, ph), (228, 220, 200, 255))
        dp = ImageDraw.Draw(papel)
        for _ in range(int(pw * ph / 90)):
            x, y = rnd.randrange(pw), rnd.randrange(ph)
            c = rnd.randint(196, 226)
            dp.point((x, y), fill=(c, c - 8, c - 26, 255))
        dp.line([0, ph * 0.52, pw, ph * 0.52 + 4], fill=(200, 190, 168, 255), width=2)
        Sprite("ARQUIVO DO CASO", f_mono(24), (60, 52, 44), esp=5).colar(papel, 60, 76, "l")
        Sprite(f"Nº {idx + 1:02d}", f_mono(24), (60, 52, 44)).colar(papel, pw - 60, 76, "r")
        dp.line([60, 100, pw - 60, 100], fill=(60, 52, 44, 255), width=2)
        Sprite("Resumo do que foi noticiado", f_texto(22), (120, 110, 96)).colar(papel, 60, ph - 44, "l")
        self.papel = papel
        sombra = Image.new("RGBA", (pw + 120, ph + 120), (0, 0, 0, 0))
        ImageDraw.Draw(sombra).rectangle([60, 70, pw + 60, ph + 70], fill=(0, 0, 0, 170))
        self.sombra = sombra.filter(ImageFilter.GaussianBlur(26))
        rotulo = (rotulo or "Segundo a imprensa").upper()
        fs = f_mono(30)
        lw = int(largura(rotulo, fs, 3)) + 60
        car = Image.new("RGBA", (lw, 84), (0, 0, 0, 0))
        dc = ImageDraw.Draw(car)
        dc.rectangle([3, 3, lw - 4, 80], outline=(176, 34, 40, 255), width=5)
        Sprite(rotulo, fs, (176, 34, 40), esp=3).colar(car, lw / 2, 54)
        self.carimbo = car.rotate(-7, expand=True, resample=Image.BICUBIC)
        self.n_total = sum(len(l) for l in self.linhas)
        self.y0 = 0

    def quadro(self, tl, dur):
        L = self.L
        W, H = L["W"], L["H"]
        fr = self.zoom(self.mesa, 1 + 0.05 * suave(tl / max(dur, 0.1)))
        t_digitar = min(2.6, max(0.8, dur * 0.55))
        n = int(self.n_total * clamp((tl - 0.25) / t_digitar))
        pg = self.papel.copy()
        d = ImageDraw.Draw(pg)
        y = 176
        resto = n
        for l in self.linhas:
            parte = l[:max(0, resto)]
            if parte:
                d.text((60, y), parte, font=self.fonte, fill=(40, 34, 30, 255), anchor="ls")
            if 0 <= resto < len(l):
                if int(tl * 3) % 2 == 0:
                    xc = 60 + largura(parte, self.fonte)
                    d.rectangle([xc + 2, y - 40, xc + 22, y + 4], fill=(40, 34, 30, 255))
                break
            resto -= len(l)
            y += 64
        z = 1.0
        cx, cy = L["gx"], L["gy"] + (0 if L["vertical"] else 10)
        colar(fr, self.sombra, cx - self.sombra.width / 2, cy - self.sombra.height / 2)
        e = ease_out(tl / 0.35)
        colar(fr, pg, cx - pg.width / 2, cy - pg.height / 2 + (1 - e) * 60, alfa=e)
        t_car = 0.25 + t_digitar + 0.15
        if tl >= t_car:
            k = ease_out((tl - t_car) / 0.14)
            esc = 1.6 - 0.6 * k
            c = self.carimbo.resize((int(self.carimbo.width * esc), int(self.carimbo.height * esc)), Image.BILINEAR)
            colar(fr, c, cx + self.papel.width * z * 0.46 - c.width, cy + (self.y_carimbo - self.papel.height / 2) * z - c.height / 2, alfa=0.9 * k)
        return fr

    def tempos(self, dur):
        t_digitar = min(2.6, max(0.8, dur * 0.55))
        return 0.25, t_digitar, 0.25 + t_digitar + 0.15


class GRevelacao(_Zoom):
    """Tipografia cinética: as palavras entram batendo, uma por vez."""

    def __init__(self, L, valor):
        super().__init__(L)
        W, H = L["W"], L["H"]
        fundo = Image.new("RGBA", (W, H), (7, 6, 9, 255))
        fundo.alpha_composite(brilho(W, H, L["gx"], H * 0.75, max(W, H) * 0.6, (190, 30, 40), 90))
        fundo = graduar(fundo)
        fundo.alpha_composite(vinheta(W, H, 200))
        self.fundo = grao(fundo)
        palavras = valor.upper().replace(".", "").split()[:4]
        fonte = f_impacto(220 if L["vertical"] else 200)
        self.linhas = []
        cur = []
        for p in palavras:
            if cur and largura(" ".join(cur + [p]), fonte) > L["gw"]:
                self.linhas.append(cur)
                cur = []
            cur.append(p)
        if cur:
            self.linhas.append(cur)
        maior = max(largura(" ".join(l), fonte) for l in self.linhas) if self.linhas else 1
        if maior > L["gw"]:
            fonte = f_impacto(int(fonte.size * L["gw"] / maior))
        self.fonte = fonte
        self.sprites = []
        esp = largura(" ", fonte)
        alt = fonte.getmetrics()[0] * 1.02
        total_h = alt * len(self.linhas)
        y = L["gy"] - total_h / 2 + alt * 0.85
        for linha in self.linhas:
            ws = [largura(p, fonte) for p in linha]
            x = L["gx"] - (sum(ws) + esp * (len(linha) - 1)) / 2
            for p, w in zip(linha, ws):
                brilho_txt = Sprite(p, fonte, (226, 48, 62, 140), sombra=18, alfa_sombra=0)
                brilho_txt.img = brilho_txt.img.filter(ImageFilter.GaussianBlur(16))
                self.sprites.append((Sprite(p, fonte, TEXTO, sombra=10, alfa_sombra=210), brilho_txt, x + w / 2, y))
                x += w + esp
            y += alt
        self.y_fim = y - alt + 40

    def impactos(self):
        return [0.08 + i * 0.24 for i in range(len(self.sprites))]

    def quadro(self, tl, dur):
        L = self.L
        fr = self.zoom(self.fundo, 1 + 0.06 * suave(tl / max(dur, 0.1)))
        tremor_x = tremor_y = 0.0
        for i, ti in enumerate(self.impactos()):
            if tl >= ti:
                k = math.exp(-22 * (tl - ti))
                tremor_x += 16 * k * math.sin(91 * tl + i)
                tremor_y += 12 * k * math.cos(77 * tl + i)
        for i, ((s, b, x, y), ti) in enumerate(zip(self.sprites, self.impactos())):
            if tl < ti:
                continue
            k = ease_out((tl - ti) / 0.12)
            esc = 1.5 - 0.5 * k
            if esc > 1.001:
                img = s.img.resize((int(s.img.width * esc), int(s.img.height * esc)), Image.BILINEAR)
                colar(fr, img, x - img.width / 2 + tremor_x, y - s.base * esc + tremor_y, alfa=k)
            else:
                colar(fr, b.img, x - b.img.width / 2 + tremor_x, y - b.base + tremor_y, alfa=0.8)
                s.colar(fr, x + tremor_x, y + tremor_y)
        fim = self.impactos()[-1] if self.sprites else 0
        larg = 300 * ease_out((tl - fim - 0.1) / 0.4)
        if larg > 2:
            ImageDraw.Draw(fr).rectangle([L["gx"] - larg / 2, self.y_fim + 10, L["gx"] + larg / 2, self.y_fim + 18], fill=VERMELHO + (255,))
        return fr


class GPergunta(_Zoom):
    """Cartão final: a pergunta para os comentários e o convite para seguir."""

    def __init__(self, L, fundo, valor, marca):
        super().__init__(L)
        self.fundo = fundo
        fs = f_serif(84 if L["vertical"] else 78)
        self.linhas = [Sprite(l, fs, TEXTO, sombra=10, alfa_sombra=200) for l in quebrar(valor, fs, L["gw"])[:4]]
        self.alt = fs.getmetrics()[0] * 1.12
        self.kicker = Sprite("E VOCÊ?", f_mono(26), OURO, esp=6)
        fp = f_mono(30)
        txt = "COMENTA AQUI  ↓"
        pw = int(largura(txt, fp, 3)) + 80
        pill = painel(pw, 84, raio=42, fundo=(214, 175, 98, 255), borda=(214, 175, 98, 255))
        Sprite(txt, fp, (20, 16, 10), esp=3).colar(pill, pw / 2, 54)
        self.pill = pill
        self.seguir = Sprite(f"Segue {marca} pro próximo caso" if marca else "Segue pro próximo caso", f_texto(34), APAGADO)

    def quadro(self, tl, dur):
        L = self.L
        fr = self.zoom(self.fundo, 1 + 0.04 * suave(tl / max(dur, 0.1)))
        gx = L["gx"]
        y = L["gy"] - (len(self.linhas) - 1) * self.alt / 2 - (40 if L["vertical"] else 70)
        self.kicker.colar(fr, gx, y - self.alt * 0.95, alfa=ease_out(tl / 0.3))
        for k, s in enumerate(self.linhas):
            a = ease_out((tl - 0.1 - k * 0.08) / 0.35)
            s.colar(fr, gx, y + k * self.alt + (1 - a) * 26, alfa=a)
        yb = y + (len(self.linhas) - 1) * self.alt + 70
        a = ease_out((tl - 0.6) / 0.35)
        pulso = 1 + 0.03 * math.sin(tl * 5) * a
        p = self.pill.resize((int(self.pill.width * pulso), int(self.pill.height * pulso)), Image.BILINEAR) if abs(pulso - 1) > 0.002 else self.pill
        colar(fr, p, gx - p.width / 2, yb, alfa=a)
        self.seguir.colar(fr, gx, yb + 150, alfa=ease_out((tl - 0.9) / 0.35))
        return fr


# =====================================================================
# narração: tempo de cada palavra e roteiro de cortes
# =====================================================================
def apoio_da_cena(c, i, n):
    a = c.get("apoio") if isinstance(c.get("apoio"), dict) else {}
    tipo = str(a.get("tipo", "")).lower().strip()
    tipo = {"número": "numero", "revelação": "revelacao", "citacao": "documento", "citação": "documento"}.get(tipo, tipo)
    valor, rotulo = str(a.get("valor", "")).strip(), str(a.get("rotulo", "")).strip()
    if tipo in TIPOS and valor:
        return {"tipo": tipo, "valor": valor, "rotulo": rotulo}
    if tipo == "nenhum":
        return None
    tt, tx = c.get("tela_titulo", ""), c.get("tela_texto", "")
    if i == n - 1 and "?" in c["fala"]:
        perg = [p for p in re.split(r"(?<=[.!?])\s+", c["fala"]) if p.strip().endswith("?")]
        return {"tipo": "pergunta", "valor": perg[-1] if perg else c["fala"], "rotulo": ""}
    if tt and re.search(r"\d", tt) and i > 0:
        return {"tipo": "numero", "valor": tt, "rotulo": tx}
    if tt and i % 2 == 1:
        return {"tipo": "cartao", "valor": tt, "rotulo": tx}
    return None


def tempos_palavras(texto, marcas, ini, fim):
    """Início e fim de cada palavra: pelas marcas da voz (exato) ou proporcional ao texto."""
    toks = [(m.group(), m.start(), m.end()) for m in re.finditer(r"\S+", texto)]
    if not toks:
        return []
    ancoras, cur, low = [], 0, texto.lower()
    for mk in marcas or []:
        w = str(mk.get("texto", "")).strip().lower()
        if not w:
            continue
        p = low.find(w, cur)
        if p < 0 or p - cur > 40:
            continue
        ancoras.append((p, ini + mk["ini"]))
        cur = p + len(w)
    if len(ancoras) >= max(2, len(toks) // 3):
        xs, ts = [a[0] for a in ancoras], [a[1] for a in ancoras]

        def t_em(pos):
            if pos <= xs[0]:
                return max(ini, ts[0] - (xs[0] - pos) * 0.055)
            for k in range(1, len(xs)):
                if pos <= xs[k]:
                    f = (pos - xs[k - 1]) / max(1, xs[k] - xs[k - 1])
                    return ts[k - 1] + f * (ts[k] - ts[k - 1])
            return min(fim - 0.05, ts[-1] + (pos - xs[-1]) * 0.055)
        inicios = [t_em(s) for _, s, _ in toks]
    else:
        inicios = [ini + (fim - ini) * s / len(texto) for _, s, _ in toks]
    out = []
    for k, (w, s, e) in enumerate(toks):
        a = inicios[k]
        b = inicios[k + 1] if k + 1 < len(toks) else fim
        out.append({"texto": w, "ini": a, "fim": max(a + 0.06, b)})
    return out


def _limpa(p):
    return re.sub(r"[^\wÀ-ÿ$%]", "", p.lower())


def marcar_chaves(palavras, cenas):
    for p in palavras:
        c = cenas[p["cena"]]
        chaves = {_limpa(x) for d in c.get("destaques", []) for x in str(d).split()}
        lp = _limpa(p["texto"])
        p["chave"] = bool(lp and (lp in chaves or re.search(r"\d", lp) or "r$" in p["texto"].lower()))


def paginas(palavras):
    pags, cur = [], []
    for p in palavras:
        if cur:
            ant = cur[-1]
            chars = sum(len(x["texto"]) + 1 for x in cur)
            if (len(cur) >= 3 or chars + len(p["texto"]) > 19 or p["cena"] != ant["cena"]
                    or re.search(r"[.!?;:]$", ant["texto"]) or (ant["texto"].endswith(",") and len(cur) >= 2)
                    or p["ini"] - ant["fim"] > 0.45):
                pags.append(cur)
                cur = []
        cur.append(p)
    if cur:
        pags.append(cur)
    res = []
    for i, pg in enumerate(pags):
        a, b = pg[0]["ini"] - 0.04, pg[-1]["fim"] + 0.25
        if i + 1 < len(pags) and pags[i + 1][0]["ini"] - pg[-1]["fim"] < 0.6:
            b = pags[i + 1][0]["ini"] - 0.04
        res.append({"palavras": pg, "ini": a, "fim": max(b, a + 0.3)})
    return res


class Legendas:
    """Legenda em blocos de até 3 palavras, palavra falada em caixa vermelha, palavras-chave em dourado."""

    def __init__(self, L, pags):
        self.L, self.pags, self.cache, self.i = L, pags, {}, 0

    def _sprite(self, pi, ativo):
        chave = (pi, ativo)
        if chave in self.cache:
            return self.cache[chave]
        L = self.L
        pg = self.pags[pi]["palavras"]
        partes = [re.sub(r"[,.;:…]+$", "", w["texto"]).upper() for w in pg]
        tam = L["leg_tam"]
        while True:
            f = f_impacto(tam)
            esp = largura(" ", f) * 1.15
            total = sum(largura(p, f) for p in partes) + esp * (len(partes) - 1)
            if total <= L["leg_larg"] or tam <= 44:
                break
            tam -= 4
        asc, desc = f.getmetrics()
        pad = 40
        w, h = int(total) + 2 * pad, asc + desc + 2 * pad
        base = pad + asc
        sombra = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        ds, d = ImageDraw.Draw(sombra), ImageDraw.Draw(img)
        x = pad
        for k, p in enumerate(partes):
            pw = largura(p, f)
            if k == ativo:
                bx = [x - 14, base - asc * 0.80 - 10, x + pw + 14, base + 12]
                ds.rounded_rectangle([bx[0], bx[1] + 8, bx[2], bx[3] + 8], 10, fill=(0, 0, 0, 170))
                d.rounded_rectangle(bx, 10, fill=VERMELHO + (255,))
                d.text((x, base), p, font=f, fill=(255, 255, 255, 255), anchor="ls")
            else:
                cor = OURO_VIVO if pg[k].get("chave") else (255, 255, 255)
                ds.text((x, base + 7), p, font=f, fill=(0, 0, 0, 190), anchor="ls", stroke_width=7, stroke_fill=(0, 0, 0, 190))
                d.text((x, base), p, font=f, fill=cor + (255,), anchor="ls", stroke_width=6, stroke_fill=(0, 0, 0, 255))
            x += pw + esp
        sombra = sombra.filter(ImageFilter.GaussianBlur(8))
        sombra.alpha_composite(img)
        self.cache[chave] = (sombra, base)
        if len(self.cache) > 200:
            self.cache.pop(next(iter(self.cache)))
        return self.cache[chave]

    def desenhar(self, fr, t):
        while self.i < len(self.pags) - 1 and t >= self.pags[self.i + 1]["ini"]:
            self.i += 1
        pg = self.pags[self.i] if self.pags else None
        if not pg or not (pg["ini"] <= t <= pg["fim"]):
            return
        ativo = -1
        for k, w in enumerate(pg["palavras"]):
            if w["ini"] <= t:
                ativo = k
        img, base = self._sprite(self.i, ativo)
        e = ease_out((t - pg["ini"]) / 0.1)
        colar(fr, img, self.L["leg_x"] - img.width / 2, self.L["leg_y"] - base + (1 - e) * 16, alfa=e)


def planejar(cenas, apoios, inicios, total, palavras):
    """Decide os cortes: quando entra a arte de apoio e qual enquadramento do apresentador usar."""
    ciclo = ["medio", "aberto", "fechado", "medio", "fechado", "aberto"]
    planos = []
    inicios_palavras = [p["ini"] for p in palavras]

    def no_corte(t, a, b):
        perto = [x for x in inicios_palavras if a + 0.9 < x - 0.05 < b - 0.9 and abs(x - t) < 0.7]
        return min(perto, key=lambda x: abs(x - t)) - 0.05 if perto else t

    def apresentador(a, b, i, enq=None):
        seg = sum(1 for p in planos if p["cena"] == i)
        enq = enq or ciclo[(2 * i + seg) % len(ciclo)]
        push = 1 if (i + seg) % 2 == 0 else -1
        planos.append({"ini": a, "fim": b, "cena": i, "tipo": "apresentador", "enq": enq, "push": push})

    def arte(a, b, i):
        planos.append({"ini": a, "fim": b, "cena": i, "tipo": apoios[i]["tipo"]})

    for i in range(len(cenas)):
        a = inicios[i]
        b = inicios[i + 1] if i + 1 < len(cenas) else total
        dur = b - a
        ap = apoios[i]
        if i == 0:
            if ap and ap["tipo"] == "revelacao":
                corte = no_corte(min(a + 1.8, a + dur * 0.5), a, b)
                arte(a, corte, i)
                apresentador(corte, b, i, "fechado")
            elif ap and dur > 3.2:
                corte = no_corte(a + dur * 0.5, a, b)
                apresentador(a, corte, i, "fechado")
                arte(corte, b, i)
            else:
                apresentador(a, b, i, "fechado")
        elif ap and ap["tipo"] == "pergunta":
            arte(a, b, i)
        elif ap:
            if dur < 3.2:
                arte(a, b, i)
            else:
                corte = no_corte(a + max(2.2, dur * (0.45 if ap["tipo"] == "revelacao" else 0.55)), a, b)
                arte(a, corte, i)
                apresentador(corte, b, i)
        elif dur > 6.5:
            corte = no_corte(a + dur / 2, a, b)
            apresentador(a, corte, i)
            apresentador(corte, b, i)
        else:
            apresentador(a, b, i)
    return planos


# =====================================================================
# áudio
# =====================================================================
def _ff(*args):
    subprocess.run(["ffmpeg", "-y", "-v", "error", *args], check=True)


def duracao(arq):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(arq)],
                       capture_output=True, text=True)
    return float(r.stdout.strip() or 0)


def juntar_narracao(falas, cenas, apoios, pasta):
    """Junta as falas com pausas (maiores antes de uma revelação). Devolve (wav, [(ini, fim)])."""
    lista, tempos, t = [], [], 0.0
    for i, f in enumerate(falas):
        pausa = 0.12 if i == 0 else (0.75 if (apoios[i] and apoios[i]["tipo"] == "revelacao") or cenas[i].get("pausa") else 0.32)
        sil = pasta / f"_pausa_{i:02d}.wav"
        _ff("-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono", "-t", f"{pausa:.2f}", str(sil))
        wav = pasta / f"_fala_{i:02d}.wav"
        _ff("-i", str(f["arquivo"]), "-ar", "48000", "-ac", "1", str(wav))
        t += pausa
        dur = duracao(wav)
        tempos.append((t, t + dur))
        t += dur
        lista += [sil, wav]
    txt = pasta / "_lista.txt"
    txt.write_text("".join(f"file '{p.resolve()}'\n" for p in lista), encoding="utf-8")
    saida = pasta / "_narracao.wav"
    _ff("-f", "concat", "-safe", "0", "-i", str(txt), "-c", "copy", str(saida))
    return saida, tempos


def envelope(wav, total_quadros):
    taxa = 8000
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(wav), "-ac", "1", "-ar", str(taxa), "-f", "s16le", "-"],
                         capture_output=True, check=True).stdout
    amostras = array.array("h")
    amostras.frombytes(raw[: len(raw) // 2 * 2])
    por = taxa // FPS
    env = []
    for q in range(total_quadros):
        bloco = amostras[q * por:(q + 1) * por]
        env.append(math.sqrt(sum(v * v for v in bloco) / len(bloco)) if bloco else 0.0)
    ref = sorted(env)[int(len(env) * 0.9)] if env else 1
    return [min(1.0, v / (ref or 1)) for v in env]


SFX = {
    "passagem": "anoisesrc=color=pink:d=0.7:a=0.6,highpass=f=500,lowpass=f=5000,afade=t=in:d=0.3,afade=t=out:st=0.3:d=0.4",
    "impacto": "aevalsrc='0.9*sin(2*PI*(62-30*t)*t)*exp(-3.2*t)':s=48000:d=1.6,lowpass=f=900",
    "subida": "aevalsrc='0.25*sin(2*PI*(180+520*t*t)*t)*(t/1.3)':s=48000:d=1.3,afade=t=out:st=1.2:d=0.1",
    "carimbo": "aevalsrc='0.9*sin(2*PI*95*t)*exp(-16*t)+0.3*sin(2*PI*1800*t)*exp(-60*t)':s=48000:d=0.6",
    "pulso": "aevalsrc='0.45*sin(2*PI*660*t)*exp(-9*t)+0.3*sin(2*PI*330*t)*exp(-6*t)':s=48000:d=0.8",
}


def _sfx_arquivo(pasta, nome, dur=None):
    p = pasta / f"_sfx_{nome}{'_' + str(round(dur, 2)) if dur else ''}.wav"
    if p.exists():
        return p
    if nome == "digitar":
        expr = f"aevalsrc='0.5*sin(2*PI*2600*t)*exp(-260*mod(t,0.062))*lt(mod(t,0.062),0.03)':s=48000:d={dur:.2f}"
        _ff("-f", "lavfi", "-i", expr, "-ac", "1", str(p))
    else:
        _ff("-f", "lavfi", "-i", SFX[nome], "-ac", "1", "-ar", "48000", str(p))
    return p


def trilha_sombria(pasta, total):
    """Trilha atmosférica gerada aqui (sem direitos autorais): grave pulsante, textura e batida de coração."""
    p = pasta / "_trilha.wav"
    expr = ("0.11*sin(2*PI*55*t)*(0.65+0.35*sin(2*PI*0.06*t))"
            "+0.07*sin(2*PI*82.41*t+0.8*sin(2*PI*0.04*t))"
            "+0.04*sin(2*PI*110*t)*(0.5+0.5*sin(2*PI*0.09*t+1))"
            "+0.025*sin(2*PI*164.8*t)*(0.5+0.5*sin(2*PI*0.13*t))"
            "+0.13*sin(2*PI*48*t)*exp(-13*mod(t,1.6))"
            "+0.08*sin(2*PI*45*t)*exp(-13*mod(t+1.32,1.6))")
    _ff("-f", "lavfi", "-i", f"aevalsrc='{expr}':s=48000:d={total + 1:.2f}",
        "-f", "lavfi", "-i", f"anoisesrc=color=brown:a=0.05:d={total + 1:.2f}",
        "-filter_complex", f"[1:a]lowpass=f=260[n];[0:a][n]amix=inputs=2:normalize=0,aecho=0.8:0.6:70|140:0.22|0.12,"
                           f"afade=t=in:d=1.2,afade=t=out:st={max(0, total - 1.5):.2f}:d=1.5",
        "-ac", "1", "-ar", "48000", str(p))
    return p


def mixar(voz, eventos, total, pasta, musica=None, volume_musica=0.12):
    """Voz tratada + trilha com ducking + efeitos, normalizado em -14 LUFS."""
    if musica and Path(musica).exists():
        entradas = ["-i", str(voz), "-stream_loop", "-1", "-i", str(musica)]
        vol_trilha = min(0.9, volume_musica * 2.5)
    else:
        entradas = ["-i", str(voz), "-i", str(trilha_sombria(pasta, total))]
        vol_trilha = 0.9
    grupos = {}
    for t, nome, vol, dur in eventos:
        if t < 0 or t > total:
            continue
        arq = _sfx_arquivo(pasta, nome, dur)
        grupos.setdefault(arq, []).append((t, vol))
    filtros = [f"[0:a]highpass=f=75,equalizer=f=250:t=q:w=1:g=-2,equalizer=f=3200:t=q:w=1:g=2.5,"
               f"acompressor=threshold=0.1:ratio=3:attack=8:release=150:makeup=2,apad=whole_dur={total:.2f},asplit=2[voz][chave]",
               f"[1:a]atrim=0:{total:.2f},volume={vol_trilha}[tr0]",
               "[tr0][chave]sidechaincompress=threshold=0.025:ratio=9:attack=15:release=380[trilha]"]
    rotulos = ["[voz]", "[trilha]"]
    for gi, (arq, usos) in enumerate(grupos.items()):
        entradas += ["-i", str(arq)]
        idx = 2 + gi
        nomes = [f"s{gi}_{u}" for u in range(len(usos))]
        if len(usos) > 1:
            filtros.append(f"[{idx}:a]asplit={len(usos)}" + "".join(f"[{n}r]" for n in nomes))
            fontes = [f"[{n}r]" for n in nomes]
        else:
            fontes = [f"[{idx}:a]"]
        for (t, vol), src, n in zip(usos, fontes, nomes):
            ms = int(t * 1000)
            filtros.append(f"{src}adelay={ms}|{ms},volume={vol}[{n}]")
            rotulos.append(f"[{n}]")
    filtros.append("".join(rotulos) + f"amix=inputs={len(rotulos)}:normalize=0:duration=first:dropout_transition=0,"
                   f"alimiter=limit=0.95,loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000[saida]")
    saida = pasta / "_mix.wav"
    _ff(*entradas, "-filter_complex", ";".join(filtros), "-map", "[saida]", "-ac", "2", "-t", f"{total:.2f}", str(saida))
    return saida


# =====================================================================
# montagem
# =====================================================================
def montar(caso, falas, destino, vertical=True, musica=None, volume_musica=0.12, reels=False):
    """
    caso: roteiro (cenas com fala, tela_titulo, tela_texto, apoio, destaques).
    falas: [{"arquivo": mp3, "texto": texto narrado, "marcas": [{"ini","fim","texto"}]}], uma por cena.
    Devolve (destino, paginas_de_legenda).
    """
    pasta = Path(destino).parent
    pasta.mkdir(parents=True, exist_ok=True)
    cenas = caso["cenas"]
    n = len(cenas)
    titulo = caso.get("titulo_caso") or "Caso real"
    marca = caso.get("marca") or ""
    L = layout(vertical, reels)
    W, H = L["W"], L["H"]
    apoios = [apoio_da_cena(c, i, n) for i, c in enumerate(cenas)]

    voz, tempos = juntar_narracao(falas, cenas, apoios, pasta)
    total = tempos[-1][1] + 1.4
    nq = int(total * FPS)
    env = envelope(voz, nq)
    palavras = []
    for i, (f, (a, b)) in enumerate(zip(falas, tempos)):
        for p in tempos_palavras(f["texto"], f.get("marcas"), a, b):
            p["cena"] = i
            palavras.append(p)
    marcar_chaves(palavras, cenas)
    pags = paginas(palavras)
    inicios = [0.0] + [max(0.0, tempos[i][0] - 0.12) for i in range(1, n)]
    planos = planejar(cenas, apoios, inicios, total, palavras)

    semente = sum(ord(ch) for ch in titulo)
    estudio = placa_estudio(L, semente)
    fundos = {tom: fundo_grafico(L, estudio, tom) for tom in ("ouro", "frio")}
    apresentador = Apresentador(L, estudio)
    artes = {}
    for i, ap in enumerate(apoios):
        if not ap:
            continue
        t, v, r = ap["tipo"], ap["valor"], ap["rotulo"]
        if t in ("numero", "cartao"):
            artes[i] = GNumero(L, fundos["ouro"], v, r, i)
        elif t == "local":
            artes[i] = GLocal(L, v, r, semente + i)
        elif t == "data":
            artes[i] = GData(L, fundos["frio"], v, r)
        elif t == "documento":
            artes[i] = GDocumento(L, v, r, i)
        elif t == "revelacao":
            artes[i] = GRevelacao(L, v)
        elif t == "pergunta":
            artes[i] = GPergunta(L, fundos["ouro"], v, marca)

    # efeitos sonoros no ritmo da edição
    eventos = [(0.0, "impacto", 0.7, None)]
    for pl in planos:
        a, b, i = pl["ini"], pl["fim"], pl["cena"]
        if a > 0.05:
            eventos.append((max(0, a - 0.18), "passagem", 0.28, None))
        tipo = pl["tipo"]
        if tipo == "revelacao" and i in artes:
            if a > 1.4:
                eventos.append((a - 1.3, "subida", 0.5, None))
            for k, ti in enumerate(artes[i].impactos()):
                eventos.append((a + ti, "impacto", 0.85 if k == 0 else 0.45, None))
        elif tipo == "documento" and i in artes:
            t0, td, tc = artes[i].tempos(b - a)
            eventos.append((a + t0, "digitar", 0.22, td))
            eventos.append((a + tc, "carimbo", 0.7, None))
        elif tipo in ("local", "data"):
            eventos.append((a + 0.45, "pulso", 0.35, None))
        elif tipo in ("numero", "cartao", "pergunta"):
            eventos.append((a + 1.15 if tipo == "numero" else a + 0.3, "pulso", 0.3, None))
    mix = mixar(voz, eventos, total, pasta, musica, volume_musica)

    # elementos fixos da tela
    chips = {}
    for i, c in enumerate(cenas):
        if apoios[i] or not c.get("tela_titulo"):
            continue
        x, y, lmax = L["chip"]
        ft, fx = f_serif(54), f_texto(30)
        lt = quebrar(c["tela_titulo"], ft, lmax - 80)[:2]
        lx = quebrar(c.get("tela_texto", ""), fx, lmax - 80)[:2]
        larg = int(min(lmax, max([largura(s, ft) for s in lt] + [largura(s, fx) for s in lx] + [260]) + 80))
        alt = 70 + len(lt) * 62 + len(lx) * 40 + 26
        img = Image.new("RGBA", (larg, alt), (0, 0, 0, 0))
        ImageDraw.Draw(img).rectangle([0, 0, larg, alt], fill=(9, 12, 18, 205))
        ImageDraw.Draw(img).rectangle([0, 0, 6, alt], fill=OURO + (255,))
        Sprite(f"EVIDÊNCIA {i + 1:02d}", f_mono(22), OURO, esp=5).colar(img, 40, 50, "l")
        for k, s in enumerate(lt):
            Sprite(s, ft, TEXTO).colar(img, 40, 112 + k * 62, "l")
        for k, s in enumerate(lx):
            Sprite(s, fx, APAGADO).colar(img, 40, 112 + (len(lt) - 1) * 62 + 46 + k * 40, "l")
        chips[i] = img
    selo = Sprite("CASO REAL", f_mono(24), OURO, esp=5)
    selo_marca = Sprite(marca, f_texto(26), (200, 204, 214)) if marca else None
    branco = Image.new("RGB", (W, H), (255, 255, 255))

    def quadro(q, estado):
        t = q / FPS
        while estado["pi"] < len(planos) - 1 and t >= planos[estado["pi"] + 1]["ini"]:
            estado["pi"] += 1
            apresentador._cbg.clear()
        pl = planos[estado["pi"]]
        tl, dur = t - pl["ini"], max(0.1, pl["fim"] - pl["ini"])
        i = pl["cena"]
        if pl["tipo"] == "apresentador":
            falando = any(a - 0.05 <= t <= b for a, b in tempos[max(0, i - 1):i + 2])
            prog = suave(tl / dur)
            m = (1 + 0.05 * prog) if pl["push"] > 0 else (1.05 - 0.05 * prog)
            punch = 1 + 0.03 * max(0.0, 1 - tl / 0.25)
            bob = (math.sin(t * 3.2) * L["alt"] * 0.004) if falando else math.sin(t * 1.2) * L["alt"] * 0.002
            fr = apresentador.quadro(pl["enq"], m * punch, bob, not (falando and env[q] > 0.3))
            if fr.mode != "RGB":
                fr = fr.convert("RGB")
            if i in chips:
                e = ease_out((tl - 0.15) / 0.35)
                x, y, _ = L["chip"]
                colar(fr, chips[i], x - (1 - e) * 50, y, alfa=e)
        else:
            fr = artes[i].quadro(tl, dur)
            if fr.mode != "RGB":
                fr = fr.convert("RGB")
        # selo do canal e barra de progresso
        d = ImageDraw.Draw(fr)
        x0, y0 = (60, L["topo"]) if L["vertical"] else (56, L["topo"])
        pulsar = 0.55 + 0.45 * abs(math.sin(t * 2.6))
        d.ellipse([x0, y0 - 22, x0 + 16, y0 - 6], fill=(int(226 * pulsar), int(48 * pulsar), int(62 * pulsar)))
        selo.colar(fr, x0 + 30, y0, "l")
        if selo_marca:
            selo_marca.colar(fr, x0 + 30 + selo.larg_texto + 24, y0, "l", alfa=0.85)
        yb = (L["topo"] - 46) if L["vertical"] else 0
        xb0, xb1 = (60, W - 60) if L["vertical"] else (0, W)
        d.rectangle([xb0, yb, xb1, yb + 4], fill=(48, 52, 62))
        d.rectangle([xb0, yb, xb0 + (xb1 - xb0) * t / total, yb + 4], fill=OURO)
        estado["leg"].desenhar(fr, t)
        if tl < 0.22 and pl["ini"] > 0.05:
            k = 1 - tl / 0.22
            forte = pl["tipo"] == "revelacao"
            dd = int((16 if forte else 10) * k)
            if dd > 0:
                r, g, b = fr.split()
                fr = Image.merge("RGB", (ImageChops.offset(r, dd, 0), g, ImageChops.offset(b, -dd, 0)))
            fr = Image.blend(fr, branco, (0.5 if forte else 0.18) * k * k)
        elif q < 6:
            fr = Image.blend(fr, branco, 0.4 * (1 - q / 6) ** 2)
        return fr

    def faixa(q0, q1, saida, rotulo):
        """Desenha os quadros [q0, q1) e grava um pedaço de vídeo (sem som). """
        cmd = ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
               "-i", "-", "-c:v", "libx264", "-preset", "veryfast", "-crf", "19",
               "-profile:v", "high", "-pix_fmt", "yuv420p", str(saida)]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
        estado = {"pi": 0, "leg": Legendas(L, pags)}
        passo = max(1, (q1 - q0) // 5)
        try:
            for q in range(q0, q1):
                proc.stdin.write(quadro(q, estado).tobytes())
                if (q - q0) % passo == 0 and q > q0:
                    print(f"  {rotulo}: {100 * (q - q0) // (q1 - q0)}%", flush=True)
        finally:
            proc.stdin.close()
        if proc.wait() != 0:
            raise RuntimeError("O ffmpeg falhou ao gravar um pedaço do vídeo.")

    # divide o vídeo entre os núcleos da máquina (cada parte vira um pedaço e no fim tudo é juntado)
    nucleos = int(os.environ.get("NUCLEOS_VIDEO") or os.cpu_count() or 1)
    partes = max(1, min(nucleos, 6, nq // (FPS * 8)))
    limites = [round(nq * k / partes) for k in range(partes + 1)]
    pedacos = [pasta / f"_parte_{k:02d}.mp4" for k in range(partes)]
    print(f"  Desenhando {nq} quadros em {partes} parte(s) ao mesmo tempo…", flush=True)
    if partes == 1:
        faixa(0, nq, pedacos[0], "parte 1/1")
    else:
        ctx = multiprocessing.get_context("fork")

        def trabalho(k):
            try:
                faixa(limites[k], limites[k + 1], pedacos[k], f"parte {k + 1}/{partes}")
            except Exception as e:  # noqa: BLE001
                print(f"  Falha na parte {k + 1}: {e}", flush=True)
                os._exit(1)
            os._exit(0)
        procs = [ctx.Process(target=trabalho, args=(k,)) for k in range(partes)]
        for pr in procs:
            pr.start()
        for pr in procs:
            pr.join()
        if any(pr.exitcode != 0 for pr in procs):
            raise RuntimeError("Uma das partes do vídeo falhou ao ser desenhada.")
    lista = pasta / "_partes.txt"
    lista.write_text("".join(f"file '{p.resolve()}'\n" for p in pedacos), encoding="utf-8")
    _ff("-f", "concat", "-safe", "0", "-i", str(lista), "-i", str(mix), "-map", "0:v", "-map", "1:a", "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k", "-t", f"{total:.2f}", "-movflags", "+faststart", str(destino))
    for p in pedacos:
        p.unlink(missing_ok=True)
    return destino, pags


def srt(pags):
    def f(s):
        ms = int(round(max(0, s) * 1000))
        return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"
    return "\n".join(f"{k + 1}\n{f(p['ini'])} --> {f(p['fim'])}\n{' '.join(w['texto'] for w in p['palavras'])}\n"
                     for k, p in enumerate(pags))
