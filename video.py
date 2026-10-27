"""Edição automática: movimento de câmera, legendas, música, marca d'água."""
import math
import os
import random
from pathlib import Path

from util import RAIZ, configurar_log, duracao, rodar_ffmpeg

log = configurar_log()
PAUSA = 0.5  # respiro entre cenas (segundos)


ZOOM = float(os.environ.get("ZOOM_VIDEO", "0.12"))


def _movimento(i: int, n: int) -> str:
    """4 movimentos alternados para o vídeo não ficar monótono."""
    z = ZOOM
    centro = "x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
    return [
        f"z='1+{z}*on/{n}':{centro}",                                     # aproxima
        f"z='{1 + z}-{z}*on/{n}':{centro}",                               # afasta
        f"z='{1 + z}':x='(iw-iw/zoom)*on/{n}':y='ih/2-(ih/zoom/2)'",       # panorâmica →
        f"z='{1 + z}':x='(iw-iw/zoom)*(1-on/{n})':y='ih/2-(ih/zoom/2)'",   # panorâmica ←
    ][i % 4]


def clipe(imagem: Path, audio: Path, saida: Path, w: int, h: int, i: int, fps: int) -> float:
    d = duracao(audio) + PAUSA
    n = math.ceil(d * fps)
    filtro = (f"[0:v]scale={w * 2}:{h * 2},zoompan={_movimento(i, n)}:d={n}:s={w}x{h}:fps={fps},"
              f"format=yuv420p[v];[1:a]apad=pad_dur={PAUSA}[a]")
    rodar_ffmpeg(["-i", imagem, "-i", audio, "-filter_complex", filtro,
                  "-map", "[v]", "-map", "[a]", "-t", f"{d:.3f}",
                  "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                  "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-ac", "2", saida])
    return d


# ---------------------------------------------------------------- legendas
def _tempo_ass(s: float) -> str:
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def criar_legendas(textos: list, duracoes: list, destino: Path, w: int, h: int, fonte: str):
    vertical = h > w
    alto = h / w > 1.5                     # 9:16 (o 4:5 do feed é vertical, mas baixo)
    tam = 78 if alto else 66 if vertical else 62
    margem = 560 if alto else 70
    por_bloco = 4 if alto else 5 if vertical else 7
    rabisco = os.environ.get("ESTILO_LEGENDA") == "rabisco"
    # rabisco: letra azul de caneta com contorno branco (combina com o fundo branco)
    cor, contorno, negrito, borda = ("&H00C94723", "&H00FFFFFF", 0, 7) if rabisco else ("&H00FFFFFF", "&H00862A5B", -1, 6)
    linhas = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {w}", f"PlayResY: {h}", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Padrao,{fonte},{tam},{cor},{cor},{contorno},&H64000000,"
        f"{negrito},0,0,0,100,100,0,0,1,{borda},{0 if rabisco else 2},2,60,60,{margem},1",
        "", "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    t0 = 0.0
    for texto, d in zip(textos, duracoes):
        fala = d - PAUSA
        palavras = texto.replace("{", "(").replace("}", ")").split()
        blocos = [" ".join(palavras[k:k + por_bloco]) for k in range(0, len(palavras), por_bloco)]
        total = sum(len(b) for b in blocos) or 1
        t = t0
        for b in blocos:
            dt = fala * len(b) / total
            linhas.append(f"Dialogue: 0,{_tempo_ass(t)},{_tempo_ass(t + dt)},Padrao,,0,0,0,,{b}")
            t += dt
        t0 += d
    destino.write_text("\n".join(linhas), encoding="utf-8-sig")


# ---------------------------------------------------------------- montagem
def _musica(cfg):
    pasta = RAIZ / cfg["video"]["pasta_musicas"]
    musicas = [p for p in pasta.glob("*") if p.suffix.lower() in (".mp3", ".wav", ".m4a", ".ogg")]
    return random.choice(musicas) if musicas else None


def montar(cfg, imagens: list, audios: list, textos: list, pasta: Path, nome: str,
           w: int, h: int, minimo: float = 0) -> Path:
    """Monta um vídeo completo a partir de imagens já no formato certo e das narrações."""
    fps = cfg["video"]["fps"]
    trab = pasta / f"_trab_{nome}"
    trab.mkdir(exist_ok=True)

    duracoes, lista = [], []
    for i, (img, aud) in enumerate(zip(imagens, audios)):
        log.info(f"[{nome}] editando cena {i + 1}/{len(imagens)}")
        c = trab / f"clipe_{i:02d}.mp4"
        duracoes.append(clipe(img, aud, c, w, h, i, fps))
        lista.append(f"file '{c.name}'")
    (trab / "lista.txt").write_text("\n".join(lista), encoding="utf-8")
    rodar_ffmpeg(["-f", "concat", "-safe", "0", "-i", "lista.txt", "-c", "copy", "junto.mp4"], cwd=trab)
    total = sum(duracoes)

    entradas = ["-i", "junto.mp4"]
    filtros_v = "[0:v]"
    if cfg["video"]["legendas"]:
        criar_legendas(textos, duracoes, trab / "legendas.ass", w, h, os.environ.get("FONTE_LEGENDA", cfg["video"]["fonte_legenda"]))
        fontes = os.environ.get("FONTES_DIR")
        filtros_v += "subtitles=legendas.ass" + (f":fontsdir='{fontes}'" if fontes else "")
    else:
        filtros_v += "null"
    filtros_v += "[v0]"
    filtros = [filtros_v]
    ultimo_v = "[v0]"
    idx = 1

    marca = RAIZ / cfg["video"]["marca_dagua"]
    if marca.exists():
        entradas += ["-i", marca]
        lado = int(min(w, h) * 0.16)
        filtros.append(f"[{idx}:v]scale={lado}:-1,format=rgba,colorchannelmixer=aa=0.85[mk]")
        filtros.append(f"{ultimo_v}[mk]overlay=W-w-30:30[v1]")
        ultimo_v = "[v1]"
        idx += 1

    musica = _musica(cfg)
    if musica:
        entradas += ["-stream_loop", "-1", "-i", musica]
        vol = cfg["video"]["musica_volume"]
        filtros.append(f"[{idx}:a]volume={vol},afade=t=out:st={max(total - 2.5, 0):.2f}:d=2.5[m]")
        filtros.append("[0:a][m]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[a]")
        ultimo_a = "[a]"
    else:
        ultimo_a = "0:a"

    final = total
    if minimo and total < minimo:              # segura o último quadro até a duração mínima
        extra = minimo - total + 0.2
        filtros.append(f"{ultimo_v}tpad=stop_mode=clone:stop_duration={extra:.2f}[vpad]")
        ultimo_v = "[vpad]"
        origem_a = ultimo_a if ultimo_a.startswith("[") else "[0:a]"
        filtros.append(f"{origem_a}apad[apad]")
        ultimo_a = "[apad]"
        final = minimo
        log.info(f"[{nome}] narração com {total:.0f}s; estendido para {minimo:.0f}s")

    saida = pasta / f"{nome}.mp4"
    rodar_ffmpeg(entradas + ["-filter_complex", ";".join(filtros),
                             "-map", ultimo_v, "-map", ultimo_a, "-t", f"{final:.3f}",
                             "-c:v", "libx264", "-preset", "medium" if total < 300 else "veryfast", "-crf", "20",
                             "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
                             "-movflags", "+faststart", saida.resolve()], cwd=trab)
    log.info(f"[{nome}] pronto: {saida.name} ({final:.0f}s)")
    return saida
