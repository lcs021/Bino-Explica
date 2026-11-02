"""Narração grátis com as vozes neurais da Microsoft (edge-tts).

Usa a voz principal do config.yaml; se ela falhar, tenta as reservas na ordem.
"""
import asyncio
import json
import re
import time
from pathlib import Path

import edge_tts

from util import configurar_log

log = configurar_log()
RESERVAS = ["pt-BR-FranciscaNeural", "pt-BR-AntonioNeural", "pt-BR-ThalitaMultilingualNeural"]


def preparar_texto(texto: str) -> str:
    """Deixa a fala mais natural: tira emojis e símbolos que a voz lê errado."""
    t = re.sub(r"[\U0001F000-\U0001FFFF☀-➿️]", "", texto)
    t = t.replace("nº", "número ").replace("Nº", "Número ").replace("#", "")
    t = re.sub(r"\s*([!?])\s*\1+", r"\1", t)        # "!!!" -> "!"
    t = re.sub(r"\.{3,}|…", "... ", t)               # reticências = pausa
    return re.sub(r"\s+", " ", t).strip()


async def _falar(texto, destino, voz, velocidade, tom):
    """Grava a fala e, ao lado (.palavras.json), o momento exato de cada palavra (para a legenda sincronizada)."""
    try:
        com = edge_tts.Communicate(texto, voz, rate=velocidade, pitch=tom, boundary="WordBoundary")
    except TypeError:                      # edge-tts antigo: já manda as palavras por padrão
        com = edge_tts.Communicate(texto, voz, rate=velocidade, pitch=tom)
    audio, palavras = bytearray(), []
    async for parte in com.stream():
        if parte["type"] == "audio":
            audio += parte["data"]
        elif parte["type"] == "WordBoundary":
            palavras.append({"ini": parte["offset"] / 1e7, "fim": (parte["offset"] + parte["duration"]) / 1e7,
                             "texto": parte["text"]})
    if not audio:
        raise RuntimeError("No audio was received")
    Path(destino).write_bytes(bytes(audio))
    if palavras:
        Path(destino).with_suffix(".palavras.json").write_text(json.dumps(palavras, ensure_ascii=False), encoding="utf-8")


_voz_escolhida = None   # decidida uma vez por execução: o episódio inteiro sai com a mesma voz


def _voz_que_funciona(cfg, pasta: Path) -> str:
    """Testa as vozes com uma frase curta e devolve a primeira que responde (leva ~2s por voz)."""
    global _voz_escolhida
    if _voz_escolhida:
        return _voz_escolhida
    n = cfg["narracao"]
    teste = pasta / "_teste_voz.mp3"
    for voz in [n["voz"]] + [v for v in RESERVAS if v != n["voz"]]:
        try:
            teste.unlink(missing_ok=True)
            asyncio.run(_falar("Olá! Teste de voz.", teste, voz, n["velocidade"], n["tom"]))
            if teste.exists() and teste.stat().st_size > 0:
                _voz_escolhida = voz
                if voz != n["voz"]:
                    log.warning(f"A voz {n['voz']} não respondeu agora; usando {voz} neste episódio.")
                else:
                    log.info(f"Voz da narração: {voz}")
                return voz
        except Exception as e:  # noqa: BLE001
            log.warning(f"Voz {voz} indisponível agora: {e}")
        finally:
            teste.unlink(missing_ok=True)
    raise RuntimeError("Nenhuma voz da Microsoft respondeu agora. Rode de novo em alguns minutos.")


def narrar(cfg, texto: str, destino: Path, voz: str = None) -> Path:
    if destino.exists() and destino.stat().st_size > 0:
        return destino
    n = cfg["narracao"]
    voz = voz or _voz_que_funciona(cfg, destino.parent)
    texto = preparar_texto(texto)
    for tentativa in range(3):
        try:
            asyncio.run(_falar(texto, destino, voz, n["velocidade"], n["tom"]))
            if destino.exists() and destino.stat().st_size > 0:
                return destino
        except Exception as e:  # noqa: BLE001
            log.warning(f"Falha na narração com {voz} ({tentativa + 1}/3): {e}")
        time.sleep(3 * (tentativa + 1))
    raise RuntimeError(f"Não consegui narrar: {destino.name}")


def narrar_cenas(cfg, cenas: list, pasta: Path, prefixo: str) -> list:
    """Narra todas as falas com UMA voz. Se ela falhar no meio, refaz tudo com a próxima voz."""
    global _voz_escolhida
    n = cfg["narracao"]
    ordem = [n["voz"]] + [v for v in RESERVAS if v != n["voz"]]
    primeira = _voz_que_funciona(cfg, pasta)
    candidatas = ordem[ordem.index(primeira):] if primeira in ordem else ordem
    for voz in candidatas:
        arquivos = [pasta / f"{prefixo}_{i:02d}.mp3" for i in range(len(cenas))]
        try:
            feitos = [narrar(cfg, c["narracao"], arq, voz) for c, arq in zip(cenas, arquivos)]
            _voz_escolhida = voz
            return feitos
        except RuntimeError as e:
            log.warning(f"A voz {voz} falhou no meio ({e}). Refazendo a narração inteira com outra voz.")
            for arq in arquivos:
                arq.unlink(missing_ok=True)
    raise RuntimeError("Nenhuma voz conseguiu narrar o episódio inteiro agora. Rode de novo mais tarde.")
