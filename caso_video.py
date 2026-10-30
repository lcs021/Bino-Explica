"""
Monta o vídeo do Caso Ao Vivo (crimes reais) com a mesma voz neural do Bino Explica.

Cena: sala de reconhecimento (régua de altura na parede), refletor, TV de evidências,
marcadores amarelos no chão e o apresentador em pé, com a boca mexendo pelo volume da voz.
Desenha cada quadro com Pillow e entrega para o ffmpeg junto com a narração.
"""
import array
import math
import random
import re
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

RAIZ = Path(__file__).resolve().parent
ASSETS = RAIZ / "assets" / "caso"
FONTES = RAIZ / "assets" / "fontes"
FPS = 30
GAP = 0.25            # pausa entre as falas (segundos)


# ---------- fontes ----------
def _fonte(nomes, tam):
    for n in nomes:
        for base in (FONTES, Path("/usr/share/fonts/truetype/dejavu")):
            p = base / n
            if p.exists():
                try:
                    return ImageFont.truetype(str(p), int(tam))
                except OSError:
                    pass
    return ImageFont.load_default(int(tam))


def f_display(t): return _fonte(["Anton-Regular.ttf", "DejaVuSans-Bold.ttf"], t)
def f_body(t): return _fonte(["Rubik-Medium.ttf", "Rubik[wght].ttf", "DejaVuSans.ttf"], t)
def f_mono(t): return _fonte(["JetBrainsMono-Bold.ttf", "DejaVuSansMono-Bold.ttf"], t)


# ---------- utilidades de desenho ----------
def radial(w, h, cx, cy, r, cor, alfa):
    """Camada RGBA com brilho radial (alfa máximo no centro)."""
    g = Image.radial_gradient("L").resize((int(r * 2), int(r * 2)))   # 0 no centro, 255 na borda
    g = g.point(lambda v: int(alfa * max(0, 255 - v * 1.0) / 255))
    camada = Image.new("RGBA", (w, h), cor + (0,))
    a = Image.new("L", (w, h), 0)
    a.paste(g, (int(cx - r), int(cy - r)))
    camada.putalpha(a)
    return camada


def lateral(w, h, lado, cor, alfa):
    """Gradiente vindo de uma borda (luz de sirene)."""
    gw = int(w * 0.35)
    linha = Image.new("L", (gw, 1))
    linha.putdata([int(alfa * (1 - x / gw)) for x in range(gw)])
    if lado != "esq":
        linha = linha.transpose(Image.FLIP_LEFT_RIGHT)
    g = linha.resize((gw, h))
    camada = Image.new("RGBA", (w, h), cor + (0,))
    a = Image.new("L", (w, h), 0)
    a.paste(g, (0 if lado == "esq" else w - gw, 0))
    camada.putalpha(a)
    return camada


def quebrar(draw, texto, fonte, largura):
    linhas, cur = [], ""
    for p in str(texto).split():
        t = f"{cur} {p}".strip()
        if draw.textlength(t, font=fonte) > largura and cur:
            linhas.append(cur)
            cur = p
        else:
            cur = t
    if cur:
        linhas.append(cur)
    return linhas


def blocos_legenda(texto):
    """Mesma divisão do site: até 6 palavras, quebrando em pontuação."""
    palavras = [(m.group(), m.start(), m.end()) for m in re.finditer(r"\S+", texto)]
    out, cur = [], []
    for w in palavras:
        cur.append(w)
        if len(cur) >= 6 or re.search(r"[.!?;:]$", w[0]) or (len(cur) >= 4 and w[0].endswith(",")):
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return out


# ---------- layout ----------
def layout(vertical):
    if vertical:
        W, H = 720, 1280
        return dict(W=W, H=H, floor=H * 0.93, h=650, cx=W * 0.5, foot=H * 0.93 + 16,
                    tv=(36, 150, W - 72, 340), tape=74,
                    markers=[(W * 0.16, H * 0.93 + 26, 1.1, 1), (W * 0.85, H * 0.93 + 30, 1.1, 2)],
                    subs=1055, subsz=58, marca=(W / 2, H - 34, 22, "mm"))
    W, H = 1280, 720
    return dict(W=W, H=H, floor=H * 0.86, h=560, cx=W * 0.3, foot=H * 0.86 + 12,
                tv=(W * 0.5, 70, W * 0.46, W * 0.46 * 0.58), tape=None,
                markers=[(W * 0.06, H * 0.86 + 34, 0.9, 1), (W * 0.93, H * 0.86 + 34, 0.9, 2)],
                subs=H - 46, subsz=48, marca=(W - 30, H - 22, 18, "rm"))


def fundo(L, titulo, marca):
    """Sala de reconhecimento sem as partes animadas."""
    W, H = L["W"], L["H"]
    img = Image.new("RGBA", (W, H))
    grad = Image.linear_gradient("L").resize((W, H))
    topo, base = (26, 31, 43), (16, 19, 27)
    img = Image.merge("RGB", [grad.point(lambda v, a=a, b=b: int(a + (b - a) * v / 255)) for a, b in zip(topo, base)]).convert("RGBA")
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    ppc = L["h"] / 178
    fm = f_mono(15 if H > W else 14)
    for cm in range(30, 235, 5):
        y = L["floor"] - cm * ppc
        if y < 0:
            break
        grande = cm % 10 == 0
        d.rectangle([0, y, W, y + (2 if grande else 1)], fill=(220, 228, 240, 41 if grande else 18))
        if grande:
            d.text((12, y - 10), str(cm), font=fm, fill=(220, 228, 240, 107), anchor="lm")
            d.text((W - 12, y - 10), str(cm), font=fm, fill=(220, 228, 240, 107), anchor="rm")
    img.alpha_composite(ov)
    img.alpha_composite(radial(W, H, L["cx"], L["floor"] - L["h"] * 0.6, L["h"] * 0.85, (255, 236, 200), 52))
    # chão
    chao = Image.new("RGBA", (W, int(H - L["floor"]) + 1), (13, 15, 21, 255))
    img.alpha_composite(chao, (0, int(L["floor"])))
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(ov).rectangle([0, L["floor"], W, L["floor"] + 2], fill=(255, 255, 255, 20))
    img.alpha_composite(ov)
    img.alpha_composite(radial(W, H, L["cx"], L["floor"] + 6, L["h"] * 0.45, (255, 236, 200), 30))
    # vinheta
    vin = Image.radial_gradient("L").resize((int(W * 1.5), int(H * 1.5)))
    vin = vin.point(lambda v: int(min(140, max(0, (v - 110) * 1.4))))
    vc = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    a = vin.crop((int(W * 0.25), int(H * 0.25), int(W * 0.25) + W, int(H * 0.25) + H))
    vc.putalpha(a)
    img.alpha_composite(vc)
    # marcadores de evidência
    for x, y, s, n in L["markers"]:
        marcador(img, x, y, s, n)
    # fita do topo (vertical)
    if L["tape"]:
        fita(img, W, L["tape"], titulo)
    # marca d'água
    if marca:
        x, y, tam, anc = L["marca"]
        ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(ov).text((x, y), marca, font=f_body(tam), fill=(255, 255, 255, 190), anchor=anc)
        img.alpha_composite(ov)
    return img


def marcador(img, x, y, s, n):
    ov = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(ov).ellipse([x - 26 * s, y - 3 * s, x + 26 * s, y + 7 * s], fill=(0, 0, 0, 100))
    img.alpha_composite(ov)
    d = ImageDraw.Draw(img)
    d.polygon([(x - 22 * s, y), (x - 12 * s, y - 42 * s), (x + 12 * s, y - 42 * s), (x + 22 * s, y)], fill=(242, 194, 48))
    d.polygon([(x + 4 * s, y - 42 * s), (x + 12 * s, y - 42 * s), (x + 22 * s, y), (x + 10 * s, y)], fill=(201, 154, 18))
    d.text((x - 2 * s, y - 18 * s), str(n), font=f_display(24 * s), fill=(27, 26, 34), anchor="mm")


def fita(img, W, y, titulo):
    faixa = Image.new("RGBA", (int(W * 1.4), 52), (245, 197, 66, 255))
    d = ImageDraw.Draw(faixa)
    unidade = f"  CASO REAL  •  {titulo.upper()}  •"
    fonte = f_display(26)
    uw = d.textlength(unidade, font=fonte)
    x = -uw * 0.3
    while x < faixa.width:
        d.text((x, 27), unidade, font=fonte, fill=(27, 26, 34), anchor="lm")
        x += uw
    faixa = faixa.rotate(2, expand=True, resample=Image.BICUBIC)
    img.alpha_composite(faixa, (int(W / 2 - faixa.width / 2), int(y - faixa.height / 2)))


def tv(L, cena, idx, titulo, conteudo=True):
    x, y, w, h = [int(v) for v in L["tv"]]
    img = Image.new("RGBA", (w + 12, h + 14), (0, 0, 0, 0))
    ImageDraw.Draw(img).rounded_rectangle([6, 10, w + 6, h + 10], 14, fill=(0, 0, 0, 120))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, w, h], 14, fill=(7, 8, 12), outline=(43, 49, 66), width=2)
    p = max(10, int(w * 0.025))
    sw, sh = w - 2 * p, h - 2 * p
    tela = Image.linear_gradient("L").resize((sw, sh))
    tela = Image.merge("RGB", [tela.point(lambda v, a=a, b=b: int(a + (b - a) * v / 255)) for a, b in zip((15, 32, 50), (10, 20, 32))])
    m = Image.new("L", (sw, sh), 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, sw - 1, sh - 1], 8, fill=255)
    img.paste(tela, (p, p), m)
    if conteudo:
        s2 = sw / 600
        pad = 26 * s2
        tem = cena and (cena.get("tela_titulo") or cena.get("tela_texto"))
        rotulo = f"EVIDÊNCIA #{idx + 1:02d}" if tem else "CASO REAL"
        d.ellipse([p + pad, p + pad + 2 * s2, p + pad + 12 * s2, p + pad + 14 * s2], fill=(255, 59, 85))
        d.text((p + pad + 20 * s2, p + pad + 9 * s2), rotulo, font=f_mono(15 * s2), fill=(255, 107, 126), anchor="lm")
        d.text((p + sw - pad, p + pad + 9 * s2), "ARQUIVO", font=f_mono(15 * s2), fill=(120, 132, 150), anchor="rm")
        cab = (cena.get("tela_titulo") if cena and cena.get("tela_titulo") else titulo or "").upper()
        sub = cena.get("tela_texto", "") if cena else ""
        fs = 64 * s2
        fd = f_display(fs)
        linhas = quebrar(d, cab, fd, sw - 2 * pad)
        if len(linhas) > 2:
            fs = 48 * s2
            fd = f_display(fs)
            linhas = quebrar(d, cab, fd, sw - 2 * pad)[:3]
        yy = p + pad + 40 * s2
        for l in linhas:
            d.text((p + pad, yy), l, font=fd, fill=(255, 255, 255))
            yy += fs * 1.08
        fb = f_body(24 * s2)
        for l in quebrar(d, sub, fb, sw - 2 * pad)[:2]:
            yy += 6 * s2
            d.text((p + pad, yy), l, font=fb, fill=(185, 198, 214))
            yy += 24 * s2
    ov = Image.new("RGBA", img.size, (0, 0, 0, 0))
    do = ImageDraw.Draw(ov)
    for yy in range(p, p + sh, 4):
        do.line([(p, yy), (p + sw, yy)], fill=(255, 255, 255, 9))
    img.alpha_composite(ov)
    return img, (x, y)


class Legenda:
    def __init__(self, W, tam):
        self.W, self.fonte, self.tam, self.cache = W, f_display(tam), tam, {}

    def imagem(self, texto, prog):
        blocos = blocos_legenda(texto)
        if not blocos:
            return None
        pos = prog * len(texto)
        k = next((i for i, g in enumerate(blocos) if pos < g[-1][2] + 1), len(blocos) - 1)
        g = blocos[k]
        ativo = next((i for i, w in enumerate(g) if w[1] <= pos <= w[2] + 1), -1)
        chave = (texto, k, ativo)
        if chave in self.cache:
            return self.cache[chave]
        partes = [w[0].upper() for w in g]
        tmp = ImageDraw.Draw(Image.new("RGB", (1, 1)))
        esp = tmp.textlength(" ", font=self.fonte)
        linhas, lw, maxw = [[]], 0, self.W * 0.86
        for i, p in enumerate(partes):
            pw = tmp.textlength(p, font=self.fonte)
            if lw + pw > maxw and linhas[-1]:
                linhas.append([])
                lw = 0
            linhas[-1].append(i)
            lw += pw + esp
        alt = int(self.tam * 1.12 * len(linhas) + self.tam)
        img = Image.new("RGBA", (self.W, alt), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        for li, ln in enumerate(linhas):
            tw = sum(tmp.textlength(partes[i], font=self.fonte) for i in ln) + esp * (len(ln) - 1)
            x = (self.W - tw) / 2
            y = alt / 2 + (li - (len(linhas) - 1) / 2) * self.tam * 1.12
            for i in ln:
                cor = (245, 197, 66) if i == ativo else (255, 255, 255)
                d.text((x, y), partes[i], font=self.fonte, fill=cor, anchor="lm",
                       stroke_width=max(3, int(self.tam * 0.09)), stroke_fill=(0, 0, 0))
                x += tmp.textlength(partes[i], font=self.fonte) + esp
        if len(self.cache) > 400:
            self.cache.clear()
        self.cache[chave] = img
        return img


# ---------- áudio ----------
def duracao(arq: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(arq)],
                       capture_output=True, text=True)
    return float(r.stdout.strip() or 0)


def juntar_narracao(arquivos, pasta: Path):
    """Junta as falas com uma pausa curta entre elas. Devolve (wav, [(inicio, fim)])."""
    lista, tempos, t = [], [], 0.0
    silencio = pasta / "_pausa.wav"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
                    "-t", str(GAP), str(silencio)], check=True)
    for i, a in enumerate(arquivos):
        wav = pasta / f"_fala_{i:02d}.wav"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(a), "-ar", "24000", "-ac", "1", str(wav)], check=True)
        dur = duracao(wav)
        tempos.append((t, t + dur))
        t += dur + GAP
        lista += [wav, silencio]
    txt = pasta / "_lista.txt"
    txt.write_text("".join(f"file '{p.resolve()}'\n" for p in lista), encoding="utf-8")
    saida = pasta / "narracao.wav"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(txt), "-c", "copy", str(saida)], check=True)
    return saida, tempos


def envelope(wav: Path, total_quadros: int):
    """Volume da voz em cada quadro (0 a 1), para mexer a boca."""
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


# ---------- montagem ----------
def montar(caso: dict, arquivos_voz: list, destino: Path, vertical=True, musica: Path = None, volume_musica=0.12):
    pasta = destino.parent
    pasta.mkdir(parents=True, exist_ok=True)
    cenas = caso["cenas"]
    titulo = caso.get("titulo_caso") or "Caso real"
    L = layout(vertical)
    W, H = L["W"], L["H"]
    wav, tempos = juntar_narracao(arquivos_voz, pasta)
    total = tempos[-1][1] + 0.8
    nq = int(total * FPS)
    env = envelope(wav, nq)

    base = fundo(L, titulo, caso.get("marca") or "")
    sir_esq = lateral(W, H, "esq", (255, 40, 70), 46)
    sir_dir = lateral(W, H, "dir", (50, 110, 255), 51)
    tv_vazia, tv_pos = tv(L, None, 0, titulo, conteudo=False)
    tvs = [tv(L, c, i, titulo)[0] for i, c in enumerate(cenas)]
    fig = Image.open(ASSETS / "apresentador.png").convert("RGBA")
    boca = Image.open(ASSETS / "boca_fechada.png").convert("RGBA")
    k = L["h"] / fig.height
    fig = fig.resize((int(fig.width * k), int(L["h"])), Image.LANCZOS)
    boca = boca.resize((max(1, int(80 * k)), max(1, int(60 * k))), Image.LANCZOS)
    boca_off = (int(225 * k), int(191 * k))
    sombra = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(sombra).ellipse([L["cx"] - fig.width * 0.42, L["foot"] - 2 - L["h"] * 0.02,
                                    L["cx"] + fig.width * 0.42, L["foot"] - 2 + L["h"] * 0.02], fill=(0, 0, 0, 128))
    base.alpha_composite(sombra)
    leg = Legenda(W, L["subsz"])
    rnd = random.Random(7)

    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
           "-i", str(wav)]
    filtro = []
    if musica and musica.exists():
        cmd += ["-stream_loop", "-1", "-i", str(musica)]
        filtro = ["-filter_complex", f"[2:a]volume={volume_musica}[m];[1:a][m]amix=inputs=2:duration=first:dropout_transition=0[a]",
                  "-map", "0:v", "-map", "[a]"]
    else:
        filtro = ["-map", "0:v", "-map", "1:a"]
    cmd += filtro + ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
                     "-c:a", "aac", "-b:a", "160k", "-t", f"{total:.2f}", "-movflags", "+faststart", str(destino)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)

    for q in range(nq):
        t = q / FPS
        si = next((i for i, (a, b) in enumerate(tempos) if t < b + GAP), len(tempos) - 1)
        ini, fim = tempos[si]
        el = t - ini
        prog = max(0.0, min(1.0, el / max(0.1, fim - ini - 0.1)))
        fr = base.copy()
        ph = math.sin(t * 5.5)
        if ph > 0.05:
            fr.alpha_composite(Image.blend(Image.new("RGBA", (W, H), (0, 0, 0, 0)), sir_esq, ph))
        elif ph < -0.05:
            fr.alpha_composite(Image.blend(Image.new("RGBA", (W, H), (0, 0, 0, 0)), sir_dir, -ph))
        # TV
        a = max(0.0, min(1.0, el / 0.4))
        if a >= 1:
            fr.alpha_composite(tvs[si], tv_pos)
        else:
            fr.alpha_composite(Image.blend(tv_vazia, tvs[si], a), tv_pos)
            if a < 0.45:
                x0, y0, w0, h0 = [int(v) for v in L["tv"]]
                ru = Image.new("RGBA", (w0, h0), (0, 0, 0, 0))
                d = ImageDraw.Draw(ru)
                for _ in range(60):
                    xx, yy = rnd.randint(14, w0 - 50), rnd.randint(14, h0 - 16)
                    d.rectangle([xx, yy, xx + rnd.randint(2, 40), yy + 2], fill=(200, 220, 255, rnd.randint(0, 64)))
                fr.alpha_composite(ru, (x0, y0))
        # apresentador
        falando = ini <= t <= fim
        bob = (math.sin(t * 3.2) * L["h"] * 0.004) if falando else math.sin(t * 1.2) * L["h"] * 0.002
        fx, fy = int(L["cx"] - fig.width / 2), int(L["foot"] - L["h"] + bob)
        fr.alpha_composite(fig, (fx, fy))
        if not (falando and env[q] > 0.35):
            fr.alpha_composite(boca, (fx + boca_off[0], fy + boca_off[1]))
        # legenda
        li = leg.imagem(cenas[si]["fala"], prog if t <= fim else 1.0)
        if li is not None:
            fr.alpha_composite(li, (0, int(L["subs"] - li.height / 2)))
        proc.stdin.write(fr.convert("RGB").tobytes())
    proc.stdin.close()
    if proc.wait() != 0:
        raise RuntimeError("O ffmpeg falhou ao montar o vídeo do caso.")
    return destino, tempos


def srt(cenas, tempos) -> str:
    def f(s):
        ms = int(round(s * 1000))
        return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"
    out, n = [], 1
    for c, (a, b) in zip(cenas, tempos):
        texto = c["fala"]
        tam = max(1, len(texto))
        for g in blocos_legenda(texto):
            ia = a + (b - a) * g[0][1] / tam
            ib = a + (b - a) * min(tam, g[-1][2] + 1) / tam
            out.append(f"{n}\n{f(ia)} --> {f(ib)}\n{' '.join(w[0] for w in g)}\n")
            n += 1
    return "\n".join(out)
