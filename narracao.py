"""Narração grátis com as vozes neurais da Microsoft (edge-tts).

Usa a voz principal do config.yaml; se ela falhar, tenta as reservas na ordem.
"""
import asyncio
import re
from pathlib import Path

import edge_tts

from util import configurar_log

log = configurar_log()
RESERVAS = ["pt-BR-ThalitaMultilingualNeural", "pt-BR-AntonioNeural", "pt-BR-FranciscaNeural"]


def preparar_texto(texto: str) -> str:
    """Deixa a fala mais natural: tira emojis e símbolos que a voz lê errado."""
    t = re.sub(r"[\U0001F000-\U0001FFFF☀-➿️]", "", texto)
    t = t.replace("nº", "número ").replace("Nº", "Número ").replace("#", "")
    t = re.sub(r"\s*([!?])\s*\1+", r"\1", t)        # "!!!" -> "!"
    t = re.sub(r"\.{3,}|…", "... ", t)               # reticências = pausa
    return re.sub(r"\s+", " ", t).strip()


async def _falar(texto, destino, voz, velocidade, tom):
    await edge_tts.Communicate(texto, voz, rate=velocidade, pitch=tom).save(str(destino))


def narrar(cfg, texto: str, destino: Path) -> Path:
    if destino.exists() and destino.stat().st_size > 0:
        return destino
    n = cfg["narracao"]
    vozes = [n["voz"]] + [v for v in RESERVAS if v != n["voz"]]
    texto = preparar_texto(texto)
    for voz in vozes:
        for tentativa in range(2):
            try:
                asyncio.run(_falar(texto, destino, voz, n["velocidade"], n["tom"]))
                if destino.exists() and destino.stat().st_size > 0:
                    if voz != n["voz"]:
                        log.info(f"Narração feita com a voz reserva {voz}.")
                    return destino
            except Exception as e:  # noqa: BLE001
                log.warning(f"Falha na narração com {voz} ({tentativa + 1}/2): {e}")
    raise RuntimeError(f"Não consegui narrar: {destino.name}")


def narrar_cenas(cfg, cenas: list, pasta: Path, prefixo: str) -> list:
    return [narrar(cfg, c["narracao"], pasta / f"{prefixo}_{i:02d}.mp3") for i, c in enumerate(cenas)]
