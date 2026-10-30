"""
Monta o vídeo do Caso Ao Vivo (crimes reais) com a mesma voz neural do Bino Explica.

Cena: estúdio noir (luz de persiana, feixe de refletor com poeira, palco com borda dourada),
um dossiê de vidro escuro com a evidência de cada cena e o apresentador em pé,
com a boca mexendo pelo volume da voz.
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


def f_serif(t): return _fonte(["DMSerifDisplay-Regular.ttf", "DejaVuSerif.ttf"], t)


OURO = (201, 164, 92)


def _h(n):
    n = (n * 2654435761) & 0xFFFFFFFF
    return (n ^ (n >> 13)) & 0xFFFFFFFF


def espacado(d, x, y, texto, fonte, cor, esp, alinhar="l"):
    """Texto com espaço entre letras (rótulos em caixa alta)."""
    larg = sum(d.textlength(ch, font=fonte) for ch in texto) + esp * (len(texto) - 1)
    x0 = x - larg / 2 if alinhar == "m" else (x - larg if alinhar == "r" else x)
    for ch in texto:
        d.text((x0, y), ch, font=fonte, fill=cor, anchor="ls")
        x0 += d.textlength(ch, font=fonte) + esp


# ---------- layout ----------
def layout(vertical):
    if vertical:
        W, H = 720, 1280
        return dict(W=W, H=H, floor=H * 0.93, h=650, cx=W * 0.5, foot=H * 0.93 + 16,
                    head=(W / 2, 78, W - 120, "m", 1.0), doss=(48, 230, W - 96, 1.0),
                    subs=1055, subsz=58, marca=(W / 2, H - 34, 22, "mm"), blinds=0.42)
    W, H = 1280, 720
    return dict(W=W, H=H, floor=H * 0.86, h=560, cx=W * 0.3, foot=H * 0.86 + 12,
                head=(W * 0.54, 70, W * 0.42, "l", 0.9), doss=(W * 0.54, 200, W * 0.41, 0.86),
                subs=H - 46, subsz=48, marca=(W - 30, H - 22, 18, "rm"), blinds=0.5)


def fundo(L, titulo, marca):
    """Estúdio noir: grafite, luz de persiana, feixe do refletor, palco com borda dourada."""
    W, H = L["W"], L["H"]
    grad = Image.linear_gradient("L").resize((W, H))
    def cor_em(v):
        p = v / 255
        if p < 0.62:
            a, b, q = (11, 15, 23), (18, 26, 40), p / 0.62
        else:
            a, b, q = (18, 26, 40), (8, 10, 16), (p - 0.62) / 0.38
        return [int(a[i] + (b[i] - a[i]) * q) for i in range(3)]
    tab = [cor_em(v) for v in range(256)]
    img = Image.merge("RGB", [grad.point([tab[v][i] for v in range(256)]) for i in range(3)]).convert("RGBA")
    # persiana
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    bw, sl = W * 0.035, H * 0.55
    for k in range(9):
        x0 = W * L["blinds"] + k * bw * 1.9
        d.polygon([(x0, 0), (x0 + bw, 0), (x0 + bw - sl * 0.55, sl), (x0 - sl * 0.55, sl)], fill=(255, 206, 150, 11))
    img.alpha_composite(ov)
    # feixe do refletor
    fl, half, cx = L["floor"], L["h"] * 0.42, L["cx"]
    mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask).polygon([(cx - 26, 0), (cx + 26, 0), (cx + half, fl), (cx - half, fl)], fill=255)
    g = Image.linear_gradient("L").resize((W, H)).point(lambda v: int(41 - 36 * min(1, v / 255 * H / fl)))
    feixe = Image.new("RGBA", (W, H), (255, 236, 205, 0))
    a = Image.new("L", (W, H), 0)
    a.paste(g, (0, 0), mask)
    feixe.putalpha(a)
    img.alpha_composite(feixe)
    # chão e palco
    chao = Image.new("RGBA", (W, int(H - fl) + 1), (12, 15, 22, 255))
    img.alpha_composite(chao, (0, int(fl)))
    rx, ry = L["h"] * 0.36, L["h"] * 0.055
    brilho = radial(int(rx * 2), int(rx * 2), rx, rx, rx, (255, 230, 190), 51).resize((int(rx * 2), max(2, int(ry * 2))))
    img.alpha_composite(brilho, (int(cx - rx), int(fl + ry * 0.2 - ry)))
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(ov).ellipse([cx - rx, fl + ry * 0.2 - ry, cx + rx, fl + ry * 0.2 + ry], outline=OURO + (140,), width=2)
    img.alpha_composite(ov)
    # vinheta
    vin = Image.radial_gradient("L").resize((int(W * 1.5), int(H * 1.5)))
    vin = vin.point(lambda v: int(min(153, max(0, (v - 100) * 1.3))))
    vc = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    vc.putalpha(vin.crop((int(W * 0.25), int(H * 0.2), int(W * 0.25) + W, int(H * 0.2) + H)))
    img.alpha_composite(vc)
    # grão de filme
    ruido = Image.frombytes("L", (W, H), bytes(random.Random(3).getrandbits(8) for _ in range(W * H)))
    gr = Image.merge("RGBA", [ruido, ruido, ruido, Image.new("L", (W, H), 16)])
    img.alpha_composite(gr)
    # cabeçalho
    x, y, maxw, al, s = L["head"]
    d = ImageDraw.Draw(img)
    espacado(d, x, y, "CASO REAL", f_mono(13 * s), OURO, 3 * s, al)
    fs = f_serif(38 * s)
    yy = y + 44 * s
    for l in quebrar(d, titulo, fs, maxw)[:2]:
        d.text((x, yy), l, font=fs, fill=(242, 239, 232), anchor=al + "s")
        yy += 42 * s
    lw = 56 * s
    x0 = x - lw / 2 if al == "m" else x
    d.rectangle([x0, yy - 24 * s, x0 + lw, yy - 24 * s + 2], fill=OURO)
    if marca:
        x, y, tam, anc = L["marca"]
        ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(ov).text((x, y), marca, font=f_body(tam), fill=(255, 255, 255, 190), anchor=anc)
        img.alpha_composite(ov)
    return img


def dossie(L, cena, idx, n, titulo):
    """Cartão de vidro escuro com cantos dourados: a evidência da cena."""
    x, y, w, s = L["doss"]
    w = int(w)
    pad = 28 * s
    tem = cena and (cena.get("tela_titulo") or cena.get("tela_texto"))
    cab = cena.get("tela_titulo") if cena and cena.get("tela_titulo") else titulo
    sub = cena.get("tela_texto", "") if cena else ""
    tmp = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    fs = 46 * s
    fsf = f_serif(fs)
    linhas = quebrar(tmp, cab, fsf, w - 2 * pad)
    if len(linhas) > 2:
        fs = 36 * s
        fsf = f_serif(fs)
        linhas = quebrar(tmp, cab, fsf, w - 2 * pad)[:3]
    fb = f_body(21 * s)
    subl = quebrar(tmp, sub, fb, w - 2 * pad)[:2]
    h = int(pad + 30 * s + fs * 0.9 + (len(linhas) - 1) * fs * 1.08 + 18 * s + (32 * s + (len(subl) - 1) * 27 * s if subl else 0) + pad * 0.9)
    img = Image.new("RGBA", (w, h), (9, 12, 19, 199))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, w - 1, h - 1], outline=(70, 64, 52, 255), width=1)
    k = int(18 * s)
    for cx, cy, dx, dy in ((0, 0, 1, 1), (w - 1, 0, -1, 1), (0, h - 1, 1, -1), (w - 1, h - 1, -1, -1)):
        d.line([(cx + dx * k, cy), (cx, cy), (cx, cy + dy * k)], fill=OURO, width=2)
    fm = f_mono(13 * s)
    espacado(d, pad, pad + 9 * s, f"EVIDÊNCIA {idx + 1:02d}" if tem else "DOSSIÊ", fm, OURO, 2.5 * s)
    d.text((w - pad, pad + 9 * s), f"{idx + 1:02d} / {n:02d}", font=fm, fill=(120, 122, 128), anchor="rs")
    yy = pad + 30 * s + fs * 0.9
    for i, l in enumerate(linhas):
        d.text((pad, yy), l, font=fsf, fill=(242, 239, 232), anchor="ls")
        if i < len(linhas) - 1:
            yy += fs * 1.08
    yy += 18 * s
    d.rectangle([pad, yy, pad + 44 * s, yy + 2], fill=OURO)
    yy += 32 * s
    for l in subl:
        d.text((pad, yy), l, font=fb, fill=(169, 178, 195), anchor="ls")
        yy += 27 * s
    return img, (int(x), int(y))


def poeira(fr, L, t):
    fl, half, cx = L["floor"], L["h"] * 0.42, L["cx"]
    ov = Image.new("RGBA", fr.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    for k in range(46):
        h1, h2 = _h(k * 13 + 5), _h(k * 29 + 11)
        yy = ((h1 % 1000) / 1000 * (fl - 40) + t * (6 + h2 % 10)) % (fl - 40) + 20
        spread = (yy / fl) * half
        xx = cx + ((h2 % 2000) / 1000 - 1) * spread * 0.9 + math.sin(t * 0.6 + k) * 6
        r = 0.8 + (h2 % 3) * 0.6
        d.ellipse([xx - r, yy - r, xx + r, yy + r], fill=(255, 240, 215, int(255 * (0.12 + ((h1 >> 5) % 30) / 100))))
    fr.alpha_composite(ov)


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
                cor = (232, 194, 122) if i == ativo else (255, 255, 255)
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
    cartoes = [dossie(L, c, i, len(cenas), titulo) for i, c in enumerate(cenas)]
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
        poeira(fr, L, t)
        # dossiê da cena (entra subindo e aparecendo)
        card, pos = cartoes[si]
        a = max(0.0, min(1.0, el / 0.45))
        e = 1 - (1 - a) ** 3
        if e >= 1:
            fr.alpha_composite(card, pos)
        elif e > 0.02:
            c2 = card.copy()
            c2.putalpha(card.getchannel("A").point(lambda v, e=e: int(v * e)))
            fr.alpha_composite(c2, (pos[0], int(pos[1] + (1 - e) * 16)))
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
