"""Narração grátis com as vozes neurais da Microsoft (edge-tts)."""
import asyncio
from pathlib import Path

import edge_tts

from util import configurar_log

log = configurar_log()


async def _falar(texto, destino, voz, velocidade, tom):
    await edge_tts.Communicate(texto, voz, rate=velocidade, pitch=tom).save(str(destino))


def narrar(cfg, texto: str, destino: Path) -> Path:
    if destino.exists() and destino.stat().st_size > 0:
        return destino
    n = cfg["narracao"]
    for tentativa in range(3):
        try:
            asyncio.run(_falar(texto, destino, n["voz"], n["velocidade"], n["tom"]))
            return destino
        except Exception as e:  # noqa: BLE001
            log.warning(f"Falha na narração ({tentativa + 1}/3): {e}")
    raise RuntimeError(f"Não consegui narrar: {destino.name}")


def narrar_cenas(cfg, cenas: list, pasta: Path, prefixo: str) -> list:
    return [narrar(cfg, c["narracao"], pasta / f"{prefixo}_{i:02d}.mp3") for i, c in enumerate(cenas)]
