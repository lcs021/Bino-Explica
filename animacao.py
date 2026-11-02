"""
Edição animada do Bino Explica (vertical 9:16, 1080x1920, 30 fps).

O que este módulo faz em cada cena:
- desenho sendo construído traço a traço (draw-on) a partir do SVG, preenchimentos surgindo depois do contorno;
- depois de pronto, o traço "respira" (line boil, como animação feita à mão) e a câmera faz um zoom suave;
- título da cena entra deslizando; transição suave (crossfade curto) entre as cenas;
- momento surpreendente: pausa curta, "ding" e zoom de impacto;
- final: chamada discreta para seguir;
- legendas sincronizadas palavra a palavra (até 2 linhas, palavras-chave coloridas);
- trilha própria (gerada aqui, sem direitos autorais), som de rabisco, whoosh nas transições e ding na revelação.
Nada de IA paga: só Python, rsvg-convert e ffmpeg.
"""
import json
import math
import os
import re
import shutil
import subprocess
import unicodedata
import xml.etree.ElementTree as ET
from io import BytesIO
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFont

from util import RAIZ, configurar_log, rodar_ffmpeg

log = configurar_log()

W, H, FPS, SR = 1080, 1920, 30, 44100
SVGNS = "http://www.w3.org/2000/svg"
ET.register_namespace("", SVGNS)
FORMAS = {"path", "circle", "ellipse", "rect", "line", "polyline", "polygon"}
IGNORAR = {"defs", "clipPath", "mask", "marker", "pattern", "symbol", "linearGradient", "radialGradient", "style", "title"}
VERMELHO, AZUL, LARANJA, PRETO = "#E0312B", "#1F5FD6", "#F28C1C", "#1A1A1A"

TOPO, BASE = 440, H - 690          # área do desenho (entre o título e a legenda)
# layout do formato atual (9:16 é o padrão; _formato("16:9") troca para o YouTube horizontal)
TIT_Y, TIT_TAM, TIT_H, TIT_LINHAS = 160, 104, 420, 3
MARCA_XY = None                    # None = centralizado embaixo
SEGUIR_Y = H - 330
LEG_TAM, LEG_MV, LEG_ML = 96, 480, 90
TEXTO_SEGUIR = None


def _formato(fmt):
    """Ajusta tamanho e posições para 9:16 (Reels/TikTok) ou 16:9 (YouTube)."""
    global W, H, TOPO, BASE, TIT_Y, TIT_TAM, TIT_H, TIT_LINHAS, MARCA_XY, SEGUIR_Y, LEG_TAM, LEG_MV, LEG_ML
    if fmt == "16:9":
        W, H = 1920, 1080
        TOPO, BASE = 165, 1080 - 185
        TIT_Y, TIT_TAM, TIT_H, TIT_LINHAS = 34, 80, 170, 2
        MARCA_XY = (1920 - 40, 1080 - 50)
        SEGUIR_Y = 1080 - 150
        LEG_TAM, LEG_MV, LEG_ML = 70, 36, 160
    else:
        W, H = 1080, 1920
        TOPO, BASE = 440, 1920 - 690
        TIT_Y, TIT_TAM, TIT_H, TIT_LINHAS = 160, 104, 420, 3
        MARCA_XY = None
        SEGUIR_Y = 1920 - 330
        LEG_TAM, LEG_MV, LEG_ML = 96, 480, 90
FIM_PAUSA = 0.30                   # respiro depois de cada fala (corte preciso, sem enrolar)
ENTRADA = 0.12                     # a voz entra logo depois do primeiro traço
PAUSA_SURPRESA = 0.65              # suspense antes da revelação
TRANSICAO = 0.22                   # crossfade entre cenas


def _t(nome):
    return RAIZ / "assets/fontes" / nome


def fonte(tam, negrito=False):
    opcoes = ([_t("Poppins-Black.ttf")] if negrito else []) + [
        _t("GochiHand-Regular.ttf"), "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]
    for p in opcoes:
        try:
            return ImageFont.truetype(str(p), tam)
        except OSError:
            continue
    return ImageFont.load_default()


# =================================================================== SVG: traço a traço
def _num(s, padrao=0.0):
    try:
        return float(re.findall(r"-?[\d.]+(?:e-?\d+)?", str(s))[0])
    except (IndexError, ValueError):
        return padrao


def _comprimento_path(d):
    """Comprimento aproximado de um <path> (curvas medidas pelos pontos de controle: basta para a animação)."""
    tokens = re.findall(r"[MmLlHhVvCcSsQqTtAaZz]|-?(?:\d+\.?\d*|\.\d+)(?:[eE]-?\d+)?", d or "")
    x = y = sx = sy = 0.0
    total, cmd, i = 0.0, "M", 0
    tam = {"M": 2, "L": 2, "T": 2, "H": 1, "V": 1, "C": 6, "S": 4, "Q": 4, "A": 7, "Z": 0}

    def ir(nx, ny):
        nonlocal x, y, total
        total += math.hypot(nx - x, ny - y)
        x, y = nx, ny

    while i < len(tokens):
        t = tokens[i]
        if re.match(r"[A-Za-z]", t):
            cmd = t
            i += 1
            if cmd in "Zz":
                ir(sx, sy)
                continue
        n = tam[cmd.upper()]
        vals = []
        for _ in range(n):
            if i >= len(tokens) or re.match(r"[A-Za-z]", tokens[i]):
                break
            vals.append(float(tokens[i]))
            i += 1
        if len(vals) < n:
            break
        rel = cmd.islower()
        bx, by = (x, y) if rel else (0.0, 0.0)
        C = cmd.upper()
        if C == "M":
            x, y = bx + vals[0], by + vals[1]
            sx, sy = x, y
            cmd = "l" if rel else "L"            # coordenadas seguintes viram linha
        elif C in "LT":
            ir(bx + vals[0], by + vals[1])
        elif C == "H":
            ir((x if rel else 0) + vals[0], y)
        elif C == "V":
            ir(x, (y if rel else 0) + vals[0])
        elif C in "CSQ":
            pts = [(bx + vals[k], by + vals[k + 1]) for k in range(0, n, 2)]
            for px, py in pts:
                ir(px, py)
        elif C == "A":
            ir(bx + vals[5], by + vals[6])
    return max(total, 1.0)


def _comprimento(el):
    tag = el.tag.split("}")[-1]
    a = el.attrib
    if tag == "path":
        return _comprimento_path(a.get("d", ""))
    if tag == "circle":
        return 2 * math.pi * _num(a.get("r"), 10)
    if tag == "ellipse":
        return math.pi * (_num(a.get("rx"), 10) + _num(a.get("ry"), 10))
    if tag == "rect":
        return 2 * (_num(a.get("width"), 10) + _num(a.get("height"), 10))
    if tag == "line":
        return math.hypot(_num(a.get("x2")) - _num(a.get("x1")), _num(a.get("y2")) - _num(a.get("y1"))) or 1
    if tag in ("polyline", "polygon"):
        p = [float(v) for v in re.findall(r"-?[\d.]+", a.get("points", ""))]
        pts = list(zip(p[::2], p[1::2]))
        if tag == "polygon" and pts:
            pts.append(pts[0])
        return sum(math.hypot(b[0] - c[0], b[1] - c[1]) for b, c in zip(pts, pts[1:])) or 1
    return 100.0


class Desenho:
    """Um SVG que sabe se desenhar aos poucos: quadro(p) devolve o SVG com a fração p (0 a 1) desenhada."""

    def __init__(self, svg_txt):
        self.raiz = ET.fromstring(svg_txt)
        pais = {c: p for p in self.raiz.iter() for c in p}
        self.formas = []
        for el in self.raiz.iter():
            tag = el.tag.split("}")[-1]
            if tag not in FORMAS:
                continue
            p, pular = pais.get(el), False
            while p is not None:
                if p.tag.split("}")[-1] in IGNORAR:
                    pular = True
                    break
                p = pais.get(p)
            if pular:
                continue
            if tag == "rect" and not self.formas and _num(el.get("width"), 0) >= 1500:
                continue                      # o fundo branco já aparece desde o início
            self.formas.append((el, _comprimento(el), el.get("style", "")))
        self.olhos = [el for el, _, _ in self.formas if _eh_olho(el)]
        # cada traço ganha um pedaço do tempo proporcional ao tamanho (detalhes pequenos não somem)
        pesos = [l ** 0.6 + 8 for _, l, _ in self.formas]
        tot = sum(pesos) or 1
        acum, self.janelas = 0.0, []
        for w_ in pesos:
            ini = 0.86 * acum / tot
            self.janelas.append((ini, max(0.05, 0.86 * w_ / tot) + 0.14))
            acum += w_

    def quadro(self, p, boil=None):
        for (el, L, estilo), (ini, dur) in zip(self.formas, self.janelas):
            q = min(1.0, max(0.0, (p - ini) / dur))
            if q >= 1:
                extra = ""
            elif q <= 0:
                extra = "opacity:0"
            else:
                ease = 1 - (1 - q) ** 2
                extra = (f"stroke-dasharray:{L:.1f} {L * 1.05:.1f};stroke-dashoffset:{L * (1 - ease):.1f};"
                         f"fill-opacity:{max(0.0, (q - 0.55) / 0.45):.2f}")
            novo = ";".join(s for s in (estilo.strip().rstrip(";"), extra) if s)
            if novo:
                el.set("style", novo)
            elif "style" in el.attrib:
                del el.attrib["style"]
        if boil is None:
            return ET.tostring(self.raiz, encoding="unicode")
        # "line boil": o traço treme de leve, como desenho animado feito à mão
        filtro = (f'<filter id="boil" x="-5%" y="-5%" width="110%" height="110%">'
                  f'<feTurbulence type="fractalNoise" baseFrequency="0.018" numOctaves="2" seed="{boil}"/>'
                  f'<feDisplacementMap in="SourceGraphic" scale="5" xChannelSelector="R" yChannelSelector="G"/></filter>')
        corpo = "".join(ET.tostring(c, encoding="unicode") for c in self.raiz)
        attrs = " ".join(f'{k}="{v}"' for k, v in self.raiz.attrib.items() if not k.startswith("{"))
        return f'<svg xmlns="{SVGNS}" {attrs}><defs>{filtro}</defs><g filter="url(#boil)">{corpo}</g></svg>'


def _cor_escura(c):
    c = (c or "").strip().lower()
    if c in ("black", "#000", "#000000"):
        return True
    m = re.fullmatch(r"#([0-9a-f]{3}|[0-9a-f]{6})", c)
    if not m:
        return False
    h = m.group(1)
    h = "".join(ch * 2 for ch in h) if len(h) == 3 else h
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return 0.3 * r + 0.59 * g + 0.11 * b < 70


def _eh_olho(el):
    """Olho de bonequinho: bolinha pequena e escura (círculo ou elipse)."""
    tag = el.tag.split("}")[-1]
    estilo = el.get("style", "")
    m = re.search(r"fill\s*:\s*([^;]+)", estilo)
    cor = m.group(1) if m else el.get("fill")
    if tag == "circle":
        tam = _num(el.get("r"), 99)
        return tam <= 18 and _cor_escura(cor)
    if tag == "ellipse":
        return max(_num(el.get("rx"), 99), _num(el.get("ry"), 99)) <= 20 and _cor_escura(cor)
    return False


def svg_piscando(desenho, boil=None):
    """O mesmo desenho com os olhos fechados (achatados na vertical)."""
    antigos = []
    for el in desenho.olhos:
        tag = el.tag.split("}")[-1]
        cx = _num(el.get("cx"), 0)
        cy = _num(el.get("cy"), 0)
        antigos.append((el, el.get("transform")))
        t = f"translate({cx} {cy}) scale(1 0.12) translate({-cx} {-cy})"
        el.set("transform", (el.get("transform") + " " if el.get("transform") else "") + t)
    try:
        return desenho.quadro(1.0, boil=boil)
    finally:
        for el, t in antigos:
            if t is None:
                el.attrib.pop("transform", None)
            else:
                el.set("transform", t)


_navegador = None


def rasterizar(svg_txt, largura, altura):
    """SVG -> imagem RGB com fundo branco (rsvg-convert; no PC de teste, cai para o Chromium)."""
    if shutil.which("rsvg-convert"):
        r = subprocess.run(["rsvg-convert", "-w", str(largura), "-h", str(altura), "-b", "white"],
                           input=svg_txt.encode("utf-8"), capture_output=True)
        if r.returncode == 0 and r.stdout:
            return Image.open(BytesIO(r.stdout)).convert("RGB")
        raise RuntimeError(r.stderr.decode()[-300:])
    global _navegador
    if _navegador is None:
        from playwright.sync_api import sync_playwright
        pw = sync_playwright().start()
        _navegador = pw.chromium.launch().new_page(viewport={"width": largura, "height": altura})
    _navegador.set_viewport_size({"width": largura, "height": altura})
    tag = '<svg width="%d" height="%d"' % (largura, altura)
    _navegador.set_content('<html><body style="margin:0;background:#fff">' + svg_txt.replace("<svg", tag, 1) + "</body></html>")
    return Image.open(BytesIO(_navegador.screenshot(type="png"))).convert("RGB")


# =================================================================== camadas fixas da cena
def _quebrar(d, texto, f, largura):
    linhas, atual = [], ""
    for p in texto.split():
        t = (atual + " " + p).strip()
        if d.textlength(t, font=f) > largura and atual:
            linhas.append(atual)
            atual = p
        else:
            atual = t
    return linhas + [atual]


def camada_titulo(titulo):
    """Título manuscrito da cena (RGBA), com o ? ou ! final em vermelho."""
    img = Image.new("RGBA", (W, TIT_H), (0, 0, 0, 0))
    if not titulo:
        return img
    d = ImageDraw.Draw(img)
    tam = TIT_TAM
    f = fonte(tam)
    linhas = _quebrar(d, titulo.upper(), f, W - 120)
    while len(linhas) > TIT_LINHAS and tam > 50:
        tam -= 6
        f = fonte(tam)
        linhas = _quebrar(d, titulo.upper(), f, W - 120)
    linhas = linhas[:TIT_LINHAS]
    for k, ln in enumerate(linhas):
        y = TIT_Y + k * int(tam * 1.05)
        x = (W - d.textlength(ln, font=f)) / 2
        if k == len(linhas) - 1 and ln[-1:] in "?!":
            d.text((x, y), ln[:-1], font=f, fill=PRETO)
            d.text((x + d.textlength(ln[:-1], font=f), y), ln[-1], font=f, fill=VERMELHO)
        else:
            d.text((x, y), ln, font=f, fill=PRETO)
    return img


def camada_fundo(marca, selo):
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    if selo:
        fs = fonte(50, negrito=True)
        tw = d.textlength(selo, font=fs)
        x0, y0 = (W - tw) / 2 - 34, 92
        d.rounded_rectangle((x0, y0, x0 + tw + 68, y0 + 74), 20, fill=VERMELHO, outline=PRETO, width=6)
        d.text((W / 2, y0 + 37), selo, font=fs, fill="white", anchor="mm")
    fm = fonte(34)
    if MARCA_XY:
        d.text(MARCA_XY, marca, font=fm, fill="#8a8a8a", anchor="rs")
    else:
        d.text(((W - d.textlength(marca, font=fm)) / 2, H - 300), marca, font=fm, fill="#8a8a8a")
    return img


def camada_seguir(marca):
    """Chamada discreta no final: selinho 'SEGUE O @binoexplica'."""
    txt = TEXTO_SEGUIR or f"+ SEGUE O {marca.upper()}"
    f = fonte(44, negrito=True)
    larg = int(ImageDraw.Draw(Image.new("RGB", (1, 1))).textlength(txt, font=f)) + 80
    img = Image.new("RGBA", (larg, 92), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((3, 3, larg - 3, 89), 46, fill=VERMELHO, outline=PRETO, width=6)
    d.text((larg / 2, 46), txt, font=f, fill="white", anchor="mm")
    return img


def _caixa_conteudo(img):
    caixa = ImageChops.difference(img, Image.new("RGB", img.size, "white")).convert("L") \
        .point(lambda x: 255 if x > 20 else 0).getbbox()
    if not caixa:
        return (0, 0, img.width, img.height)
    m = int(img.width * 0.03)
    return (max(0, caixa[0] - m), max(0, caixa[1] - m), min(img.width, caixa[2] + m), min(img.height, caixa[3] + m))


# =================================================================== uma cena
def _ease(x):
    x = min(1.0, max(0.0, x))
    return x * x * (3 - 2 * x)


class Cena:
    def __init__(self, svg_txt, png, titulo, dur, voz_ini, indice, surpresa=False, ultima=False,
                 movimento=None, efeito=None, base=None):
        self.dur, self.voz_ini, self.i = dur, voz_ini, indice
        self.continua = base is not None
        self.surpresa, self.ultima = surpresa, ultima
        self.movimento = movimento or ("impacto" if surpresa else ["aproximar", "afastar", "panoramica"][indice % 3])
        self.efeito = efeito or ("ding" if surpresa else "nenhum")
        self.desenho = None
        if base is not None:              # mesma ilustração da fala anterior: já entra desenhada, sem redesenhar
            for k in ("desenho", "rw", "rh", "caixa", "esc", "tam", "pos", "final", "boils", "piscar"):
                setattr(self, k, getattr(base, k))
            self.t_desenho = 0.0
            self.titulo = camada_titulo(titulo)
            self._cache = {}
            return
        if svg_txt:
            try:
                self.desenho = Desenho(svg_txt)
                if len(self.desenho.formas) < 2:
                    self.desenho = None
            except ET.ParseError as e:
                log.warning(f"Cena {indice + 1}: SVG inválido para animar ({e}); entra com fade.")
        self.rw, self.rh = 2400, 1350
        if self.desenho:
            final = rasterizar(self.desenho.quadro(1.0), self.rw, self.rh)
        else:
            final = Image.open(png).convert("RGB").resize((self.rw, self.rh), Image.LANCZOS)
        self.caixa = _caixa_conteudo(final)
        cw, ch = self.caixa[2] - self.caixa[0], self.caixa[3] - self.caixa[1]
        self.esc = min((W - 60) / cw, (BASE - TOPO) / ch)
        self.tam = (max(1, int(cw * self.esc)), max(1, int(ch * self.esc)))
        self.pos = ((W - self.tam[0]) // 2, TOPO + (BASE - TOPO - self.tam[1]) // 2)
        self.final = self._encaixar(final)
        # tempo de construção: rápido na abertura, nunca maior que 40% da cena
        self.t_desenho = min(1.1 if indice == 0 else 2.0, 0.4 * dur) + (PAUSA_SURPRESA * 0.6 if surpresa else 0)
        self.boils = []
        if self.desenho:
            for seed in (3, 11, 23):
                try:
                    self.boils.append(self._encaixar(rasterizar(self.desenho.quadro(1.0, boil=seed), self.rw, self.rh)))
                except Exception as e:  # noqa: BLE001
                    log.warning(f"Line boil indisponível ({e}); desenho fica firme.")
                    self.boils = []
                    break
        self.piscar = None                     # personagens piscam a cada ~3 s (quando os olhos são bolinhas)
        if self.desenho and self.desenho.olhos:
            try:
                self.piscar = self._encaixar(rasterizar(svg_piscando(self.desenho, boil=3 if self.boils else None),
                                                        self.rw, self.rh))
            except Exception as e:  # noqa: BLE001
                log.warning(f"Piscar indisponível ({e}).")
        self.titulo = camada_titulo(titulo)
        self._cache = {}

    def _encaixar(self, img):
        return img.crop(self.caixa).resize(self.tam, Image.LANCZOS)

    def desenho_em(self, t):
        if t >= self.t_desenho:
            if self.piscar is not None and ((t - self.t_desenho + 0.9 + self.i * 0.7) % 3.1) < 0.14:
                return self.piscar
            if self.boils:
                return self.boils[int((t - self.t_desenho) * 7.5) % len(self.boils)]
            return self.final
        p = t / self.t_desenho
        if not self.desenho:                         # sem SVG: aparece com fade
            return Image.blend(Image.new("RGB", self.tam, "white"), self.final, _ease(p))
        k = int(p * 15 * self.t_desenho)            # 15 desenhos novos por segundo (o resto repete)
        if k not in self._cache:
            self._cache = {k: self._encaixar(rasterizar(self.desenho.quadro(min(1.0, (k + 1) / (15 * self.t_desenho))),
                                                        self.rw, self.rh))}
        return self._cache[k]

    def zoom_em(self, t):
        """Câmera do storyboard: aproximar, afastar, panorâmica ou impacto (zoom rápido na revelação)."""
        p = t / self.dur
        if self.movimento == "afastar":
            base = 0.05 * (1 - p)
        elif self.movimento == "panoramica":
            base = 0.07
        else:
            base = 0.045 * p
        if self.surpresa or self.movimento == "impacto":
            base += 0.11 * _ease((t - self.voz_ini) / 0.35)
        return 1.0 + base

    def pan_em(self, t):
        """Deslocamento lateral suave (-1 a 1) para a panorâmica."""
        return (-0.8 + 1.6 * _ease(t / self.dur)) if self.movimento == "panoramica" else 0.0

    def quadro(self, t, fundo, anterior=None, seguir=None):
        tela = fundo.copy()
        tela.paste(self.desenho_em(t), self.pos)
        # câmera: o zoom mexe só na faixa do desenho (título, selo e legenda ficam firmes e inteiros)
        z = self.zoom_em(t)
        if z > 1.0005:
            y_a, y_b = TOPO - 20, BASE + 20
            faixa_h = y_b - y_a
            lw, lh = W / z, faixa_h / z
            x0, y0 = (W - lw) / 2 * (1 + self.pan_em(t)), y_a + (faixa_h - lh) / 2
            faixa = tela.resize((W, faixa_h), Image.BILINEAR, box=(x0, y0, x0 + lw, y0 + lh))
            tela.paste(faixa, (0, y_a))
        # título: entra deslizando e aparecendo
        a = _ease(t / 0.28)
        if a > 0:
            tit = self.titulo
            if a < 1:
                tit = tit.copy()
                tit.putalpha(tit.getchannel("A").point(lambda v: int(v * a)))
            tela.paste(tit, (0, int(26 * (1 - a))), tit)
        if seguir is not None and self.ultima:
            b = _ease((t - (self.dur - 3.2)) / 0.3)
            if b > 0:
                s = seguir if b >= 1 else seguir.copy()
                if b < 1:
                    s.putalpha(seguir.getchannel("A").point(lambda v: int(v * b)))
                tela.paste(s, ((W - s.width) // 2, SEGUIR_Y - int(20 * (1 - b))), s)
        if anterior is not None and t < TRANSICAO:
            tela = Image.blend(anterior, tela, _ease(t / TRANSICAO))
        return tela


def _gravar_cena(cena, fundo, anterior, seguir, destino):
    n = max(1, round(cena.dur * FPS))
    tmp = destino.with_name(destino.stem + ".parcial.mp4")
    proc = subprocess.Popen(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "rawvideo",
                             "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
                             "-c:v", "libx264", "-preset", "veryfast", "-crf", "19", "-pix_fmt", "yuv420p",
                             "-r", str(FPS), str(tmp)], stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    ultimo = None
    try:
        for k in range(n):
            ultimo = cena.quadro(k / FPS, fundo, anterior, seguir)
            proc.stdin.write(ultimo.tobytes())
        proc.stdin.close()
    except BrokenPipeError:
        pass
    if proc.wait() != 0:
        raise RuntimeError(f"ffmpeg falhou na cena {cena.i + 1}: {proc.stderr.read().decode()[-500:]}")
    tmp.replace(destino)
    return ultimo


# =================================================================== som
def _ler_audio(arq):
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(arq), "-f", "f32le", "-ac", "1", "-ar", str(SR), "-"],
                       capture_output=True, check=True)
    return np.frombuffer(r.stdout, dtype=np.float32).copy()


def _ruido(n, seed):
    return np.random.default_rng(seed).standard_normal(n).astype(np.float32)


def _passa_banda(x, lo, hi):
    f = np.fft.rfft(x)
    fr = np.fft.rfftfreq(len(x), 1 / SR)
    f[(fr < lo) | (fr > hi)] = 0
    return np.fft.irfft(f, len(x)).astype(np.float32)


def som_rabisco(dur, seed):
    """Caneta riscando o papel: ruído agudo em rajadas curtas (cada traço)."""
    n = int(dur * SR)
    if n < 100:
        return np.zeros(max(n, 1), np.float32)
    x = _passa_banda(_ruido(n, seed), 1800, 6500)
    rng = np.random.default_rng(seed + 1)
    env = np.zeros(n, np.float32)
    t = 0
    while t < n:
        tam = int(rng.uniform(0.07, 0.22) * SR)
        seg = np.sin(np.linspace(0, np.pi, min(tam, n - t))) ** 0.7
        env[t:t + len(seg)] = seg * rng.uniform(0.5, 1.0)
        t += tam + int(rng.uniform(0.02, 0.08) * SR)
    fade = np.minimum(1, np.minimum(np.arange(n), n - np.arange(n)) / (0.08 * SR))
    x = x * env * fade
    return (x / (np.abs(x).max() + 1e-9)).astype(np.float32)


def som_whoosh(dur=0.35, seed=7):
    n = int(dur * SR)
    x = _ruido(n, seed)
    # filtro passa-baixa que abre e fecha (varredura)
    saida, y = np.zeros(n, np.float32), 0.0
    for k in range(n):
        a = 0.02 + 0.25 * math.sin(math.pi * k / n)
        y += a * (x[k] - y)
        saida[k] = y
    saida *= np.sin(np.linspace(0, np.pi, n)) ** 1.5
    return (saida / (np.abs(saida).max() + 1e-9)).astype(np.float32)


def som_pop():
    """'Pop' curtinho de bolha (entrada de elemento)."""
    t = np.arange(int(0.09 * SR)) / SR
    f = 950 - 6500 * t
    x = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 38)
    return (x / (np.abs(x).max() + 1e-9)).astype(np.float32)


def som_ding():
    t = np.arange(int(0.9 * SR)) / SR
    x = (np.sin(2 * np.pi * 1318.5 * t) + 0.6 * np.sin(2 * np.pi * 1975.5 * t) + 0.25 * np.sin(2 * np.pi * 2637 * t))
    x *= np.exp(-t * 5.5) * np.minimum(1, t / 0.004)
    return (x / np.abs(x).max()).astype(np.float32)


def _pluck(freq, dur, seed):
    """Corda dedilhada (Karplus-Strong): soa como um ukulele simpático."""
    n = int(dur * SR)
    p = max(2, int(SR / freq))
    buf = np.random.default_rng(seed).uniform(-1, 1, p).astype(np.float32)
    out = np.zeros(n, np.float32)
    for k in range(n):
        out[k] = buf[k % p]
        buf[k % p] = 0.5 * (buf[k % p] + buf[(k + 1) % p]) * 0.996
    return out


def trilha(dur):
    """Música de fundo leve e curiosa, composta aqui mesmo (sem direitos autorais)."""
    bpm = 104
    colcheia = 60 / bpm / 2
    nota = lambda m: 440 * 2 ** ((m - 69) / 12)
    acordes = [[60, 64, 67, 72], [55, 59, 62, 67], [57, 60, 64, 69], [53, 57, 60, 65]]   # C G Am F
    padrao = [0, 2, 1, 3, 2, 1, 3, 2]
    compasso = len(padrao) * colcheia
    loop = np.zeros(int(compasso * 4 * SR) + SR, np.float32)
    seed = 0
    for c, ac in enumerate(acordes):
        for k, idx in enumerate(padrao):
            t0 = int((c * compasso + k * colcheia) * SR)
            s = _pluck(nota(ac[idx]), 0.9, seed) * (0.9 if k % 2 == 0 else 0.6)
            seed += 1
            loop[t0:t0 + len(s)] += s[:len(loop) - t0]
        b = _pluck(nota(ac[0] - 24), 1.6, 99 + c) * 0.8                                # baixo
        t0 = int(c * compasso * SR)
        loop[t0:t0 + len(b)] += b[:len(loop) - t0]
    ciclo = int(compasso * 4 * SR)
    loop[:SR] += loop[ciclo:ciclo + SR]           # emenda o rabo do loop no começo
    loop = loop[:ciclo]
    n = int(dur * SR)
    out = np.tile(loop, n // len(loop) + 1)[:n]
    out = _passa_banda(out, 60, 5000) if n < SR * 400 else out
    return (out / (np.abs(out).max() + 1e-9)).astype(np.float32)


def mixar(cenas, falas, destino):
    """Narração + trilha (abaixa quando o Bino fala) + rabisco + whoosh + ding."""
    total = sum(c.dur for c in cenas)
    n = int(total * SR) + SR
    voz = np.zeros(n, np.float32)
    efeitos = np.zeros(n, np.float32)
    t0 = 0.0
    for k, (c, f) in enumerate(zip(cenas, falas)):
        a = int((t0 + c.voz_ini) * SR)
        voz[a:a + len(f)] += f[:n - a]
        r = som_rabisco(c.t_desenho, 100 + k) * 0.05
        b = int(t0 * SR)
        efeitos[b:b + len(r)] += r[:n - b]
        if k > 0 and not getattr(c, "continua", False):
            w = som_whoosh(seed=k) * 0.07
            b = max(0, int((t0 - 0.12) * SR))
            efeitos[b:b + len(w)] += w[:n - b]
        if c.efeito == "pop":
            d = som_pop() * 0.14
            b = int((t0 + c.voz_ini + 0.05) * SR)
            efeitos[b:b + len(d)] += d[:n - b]
        if c.surpresa or c.efeito == "ding":
            d = som_ding() * 0.16
            b = int((t0 + c.voz_ini - 0.05) * SR)
            efeitos[b:b + len(d)] += d[:n - b]
        t0 += c.dur
    musica_arq = _musica_externa()
    m = _ler_audio(musica_arq) if musica_arq else trilha(total + 1)
    if len(m) < n:
        m = np.tile(m, n // max(len(m), 1) + 1)
    m = m[:n] / (np.abs(m[:n]).max() + 1e-9)
    # ducking: música a 13% nos respiros e 6% embaixo da voz
    janela = int(0.25 * SR)
    acum = np.concatenate([[0.0], np.cumsum(np.abs(voz), dtype=np.float64)])
    ini = np.clip(np.arange(n) - janela // 2, 0, n)
    fim = np.clip(np.arange(n) + janela // 2, 0, n)
    energia = ((acum[fim] - acum[ini]) / janela).astype(np.float32)
    fala = np.clip(energia / 0.02, 0, 1)
    ganho = 0.13 - 0.07 * fala
    fim = int((total - 2.0) * SR)
    ganho[fim:] *= np.linspace(1, 0, n - fim) if n > fim > 0 else 1
    mix = voz * 1.0 + m * ganho + efeitos
    mix = np.tanh(mix * 1.1) / np.tanh(1.1)
    mix = mix[:int(total * SR)]
    pcm = (np.clip(mix, -1, 1) * 32767).astype("<i2")
    est = np.repeat(pcm[:, None], 2, axis=1)
    import wave
    with wave.open(str(destino), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(est.tobytes())
    return destino


def _musica_externa():
    pasta = RAIZ / "assets/musicas"
    ms = sorted(p for p in pasta.glob("*") if p.suffix.lower() in (".mp3", ".wav", ".m4a", ".ogg")) if pasta.exists() else []
    return ms[0] if ms else None


# =================================================================== legendas palavra a palavra
NUMEROS = set("dois duas três tres quatro cinco seis sete oito nove dez onze doze treze catorze quatorze quinze "
              "dezesseis dezessete dezoito dezenove vinte trinta quarenta cinquenta sessenta setenta oitenta noventa "
              "cem cento duzentos trezentos quinhentos mil milhão milhões bilhão bilhões metade dobro".split())


def _norm(s):
    s = unicodedata.normalize("NFD", s.lower())
    return re.sub(r"[^\w]", "", "".join(ch for ch in s if unicodedata.category(ch) != "Mn"))


def _palavras_com_tempo(texto, arq_audio, dur_fala):
    """[(ini, fim, palavra_original)]: tempos reais da voz quando existem; senão, distribui pelo tamanho."""
    originais = texto.replace("{", "(").replace("}", ")").split()
    js = Path(arq_audio).with_suffix(".palavras.json")
    if js.exists():
        try:
            marcas = json.loads(js.read_text(encoding="utf-8"))
            res, j = [], 0
            for m in marcas:
                alvo = _norm(m["texto"])
                # acha a palavra original correspondente (a voz não manda pontuação)
                k = j
                while k < len(originais) and _norm(originais[k]) != alvo and k - j < 3:
                    k += 1
                if k < len(originais) and _norm(originais[k]) == alvo:
                    for extra in originais[j:k]:          # palavras puladas pela voz (raras): coladas antes
                        res.append([m["ini"], m["ini"], extra])
                    res.append([m["ini"], m["fim"], originais[k]])
                    j = k + 1
                else:
                    res.append([m["ini"], m["fim"], m["texto"]])
            for extra in originais[j:]:
                res.append([res[-1][1] if res else 0, res[-1][1] if res else 0, extra])
            if res:
                return res
        except Exception as e:  # noqa: BLE001
            log.warning(f"Tempos das palavras ilegíveis ({e}); usando estimativa.")
    tot = sum(len(p) + 1 for p in originais) or 1
    res, t = [], 0.0
    for p in originais:
        d = dur_fala * (len(p) + 1) / tot
        res.append([t, t + d, p])
        t += d
    return res


def _cor_palavra(p, primeira, destaques):
    n = _norm(p)
    if re.search(r"\d", p) or n in NUMEROS:
        return VERMELHO
    if n and any(n == _norm(d) or (len(n) > 3 and n in _norm(d).split()) for d in destaques):
        return LARANJA
    limpo = re.sub(r"^[^\wÀ-ÿ]+", "", p)
    if limpo[:1].isupper() and not primeira and len(n) > 1:
        return AZUL
    return None


def _ass_cor(hexa):
    h = hexa.lstrip("#")
    return f"&H00{h[4:6]}{h[2:4]}{h[0:2]}"


def legendas_ass(cenas, textos, audios, destaques, destino, fonte_nome):
    tam = LEG_TAM
    linhas = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}", "WrapStyle: 0", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Padrao,{fonte_nome},{tam},{_ass_cor(PRETO)},{_ass_cor(PRETO)},&H00FFFFFF,&H00000000,"
        f"0,0,0,0,100,100,1,0,1,8,0,2,{LEG_ML},{LEG_ML},{LEG_MV},1",
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    def tempo(s):
        s = max(0.0, s)
        h, s = divmod(s, 3600)
        m, s = divmod(s, 60)
        return f"{int(h)}:{int(m):02d}:{s:05.2f}"

    t0 = 0.0
    for c, texto, aud, dest in zip(cenas, textos, audios, destaques):
        pal = _palavras_com_tempo(texto, aud, c.dur - c.voz_ini - FIM_PAUSA)
        grupos, atual = [], []
        for p in pal:                                  # até 3 palavras / 18 letras; quebra na pontuação
            atual.append(p)
            letras = sum(len(x[2]) + 1 for x in atual)
            if len(atual) >= 3 or letras >= 18 or re.search(r"[.!?,;:…]$", p[2]):
                grupos.append(atual)
                atual = []
        if atual:
            grupos.append(atual)
        inicio_frase = True
        for g, grupo in enumerate(grupos):
            ini = t0 + c.voz_ini + grupo[0][0]
            fim = t0 + c.voz_ini + (grupos[g + 1][0][0] if g + 1 < len(grupos) else grupo[-1][1] + 0.25)
            fim = min(fim, t0 + c.dur)
            if fim - ini < 0.05:
                continue
            partes = []
            for k, (_, _, w) in enumerate(grupo):
                cor = _cor_palavra(w, inicio_frase and k == 0, dest)
                w = w.replace("\\", "")
                partes.append(f"{{\\c{_ass_cor(cor)}}}{w}{{\\c{_ass_cor(PRETO)}}}" if cor else w)
                inicio_frase = bool(re.search(r"[.!?…]$", w))
            pop = "{\\fscx82\\fscy82\\t(0,90,\\fscx106\\fscy106)\\t(90,150,\\fscx100\\fscy100)}"
            linhas.append(f"Dialogue: 0,{tempo(ini)},{tempo(fim)},Padrao,,0,0,0,,{pop}{' '.join(partes)}")
        t0 += c.dur
    destino.write_text("\n".join(linhas), encoding="utf-8-sig")
    return destino


# =================================================================== montagem completa
def montar_tiktok(cfg, roteiro, cenas_png, audios, titulos, pasta, marca, selo=None, minimo=62, nome="tiktok_9x16",
                  formato="9:16", texto_seguir=None):
    """Monta o vídeo animado (vertical 9:16 ou horizontal 16:9). Devolve o caminho do MP4."""
    global TEXTO_SEGUIR
    _formato(formato)
    TEXTO_SEGUIR = texto_seguir
    try:
        return _montar(cfg, roteiro, cenas_png, audios, titulos, pasta, marca, selo, minimo, nome)
    finally:
        _formato("9:16")
        TEXTO_SEGUIR = None


def _montar(cfg, roteiro, cenas_png, audios, titulos, pasta, marca, selo, minimo, nome):
    from util import duracao
    narr = roteiro["cenas"]
    n = len(cenas_png)
    surpresa = roteiro.get("surpresa")
    try:
        surpresa = int(surpresa)
    except (TypeError, ValueError):
        surpresa = max(1, n - 3)
    surpresa = min(max(1, surpresa), n - 2) if n > 3 else -1
    trab = pasta / "_trab_animado"
    trab.mkdir(exist_ok=True)

    falas = [_ler_audio(a) for a in audios]
    cenas = []
    for i in range(n):
        svg_arq = Path(cenas_png[i]).with_suffix(".svg")
        svg = svg_arq.read_text(encoding="utf-8") if svg_arq.exists() else None
        voz_ini = ENTRADA + (PAUSA_SURPRESA if i == surpresa else 0)
        dur = voz_ini + len(falas[i]) / SR + FIM_PAUSA
        if i == n - 1:
            dur += 0.6                                   # respiro final antes do loop
        sb = narr[i] if i < len(narr) else {}
        base = cenas[-1] if i > 0 and str(cenas_png[i]) == str(cenas_png[i - 1]) else None
        cenas.append(Cena(svg, cenas_png[i], titulos[i], dur, voz_ini, i, surpresa=(i == surpresa), ultima=(i == n - 1),
                          movimento=sb.get("movimento"), efeito=sb.get("efeito"), base=base))
        log.info(f"[animado] cena {i + 1}/{n} preparada ({len(cenas[-1].desenho.formas) if cenas[-1].desenho else 0} traços)")
    total = sum(c.dur for c in cenas)
    if total < minimo:                                    # passa de 1 min: estica a última cena com o desenho vivo
        cenas[-1].dur += minimo - total + 0.2
        log.info(f"[animado] narração com {total:.0f}s; final estendido para {minimo:.0f}s")

    fundo = camada_fundo(marca, selo)
    seguir = camada_seguir(marca)
    arquivos, anterior = [], None
    for c in cenas:
        log.info(f"[animado] filmando cena {c.i + 1}/{n} ({c.dur:.1f}s)")
        destino = trab / f"cena_{c.i:02d}.mp4"
        anterior = _gravar_cena(c, fundo, None if c.continua else anterior, seguir, destino)
        arquivos.append(destino)
    t, tempos = 0.0, []
    for c in cenas:
        tempos.append(round(t, 2))
        t += c.dur
    (pasta / "tempos.json").write_text(json.dumps(tempos), encoding="utf-8")
    (trab / "lista.txt").write_text("\n".join(f"file '{a.name}'" for a in arquivos), encoding="utf-8")
    rodar_ffmpeg(["-f", "concat", "-safe", "0", "-i", "lista.txt", "-c", "copy", "imagem.mp4"], cwd=trab)

    mixar(cenas, falas, trab / "som.wav")
    fonte_nome = os.environ.get("FONTE_LEGENDA", "Gochi Hand")
    destaques = [list(c.get("destaques") or []) for c in narr[:n]]
    legendas_ass(cenas, [c["narracao"] for c in narr[:n]], audios, destaques, trab / "legendas.ass", fonte_nome)
    fontes = os.environ.get("FONTES_DIR") or str(RAIZ / "assets/fontes")
    saida = pasta / f"{nome}.mp4"
    tmp = pasta / f"{nome}.parcial.mp4"
    rodar_ffmpeg(["-i", "imagem.mp4", "-i", "som.wav", "-filter_complex",
                  f"[0:v]subtitles=legendas.ass:fontsdir='{fontes}'[v];[1:a]loudnorm=I=-14:TP=-1.5:LRA=11,aresample=44100[a]",
                  "-map", "[v]", "-map", "[a]",
                  "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p",
                  "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", tmp.resolve()], cwd=trab)
    tmp.replace(saida)
    log.info(f"[animado] pronto: {saida.name} ({duracao(saida):.0f}s)")
    return saida


# =================================================================== capa do Reels
def capa(cena_png, texto, destino, marca="@binoexplica", svg_txt=None):
    """Capa 1080x1920: título curto e grande, ilustração do assunto, identidade do perfil.
    O que importa fica no meio (o perfil do Instagram mostra a capa recortada em 3:4)."""
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    desenho = rasterizar(svg_txt, 2400, 1350) if svg_txt else Image.open(cena_png).convert("RGB").resize((2400, 1350))
    caixa = _caixa_conteudo(desenho)
    desenho = desenho.crop(caixa)
    topo, base = 820, 1500
    esc = min((W - 80) / desenho.width, (base - topo) / desenho.height)
    desenho = desenho.resize((int(desenho.width * esc), int(desenho.height * esc)), Image.LANCZOS)
    img.paste(desenho, ((W - desenho.width) // 2, topo + (base - topo - desenho.height) // 2))
    texto = (texto or "").upper().strip()
    tam = 150
    f = fonte(tam, negrito=True)
    linhas = _quebrar(d, texto, f, W - 110)
    while (len(linhas) > 3 or max(d.textlength(l, font=f) for l in linhas) > W - 110) and tam > 80:
        tam -= 10
        f = fonte(tam, negrito=True)
        linhas = _quebrar(d, texto, f, W - 110)
    alt = int(tam * 1.08)
    y = 780 - alt * len(linhas)
    for k, ln in enumerate(linhas):
        x = (W - d.textlength(ln, font=f)) / 2
        cor_final = VERMELHO if k == len(linhas) - 1 and ln[-1:] in "?!" else None
        corpo = ln[:-1] if cor_final else ln
        d.text((x, y), corpo, font=f, fill=PRETO, stroke_width=4, stroke_fill="white")
        if cor_final:
            d.text((x + d.textlength(corpo, font=f), y), ln[-1], font=f, fill=VERMELHO)
        y += alt
    # sublinhado de caneta embaixo do título
    d.line([(160, 800), (W // 2, 812), (W - 160, 798)], fill=VERMELHO, width=12, joint="curve")
    fm = fonte(46, negrito=True)
    d.text((W / 2, 1600), marca, font=fm, fill="#8a8a8a", anchor="mm")
    img.save(destino, quality=93)
    return destino
