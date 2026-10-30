"""Narração do Caso Ao Vivo: voz neural masculina e o tempo de cada palavra (para as legendas)."""
import asyncio
import time

import edge_tts

from narracao import preparar_texto
from util import configurar_log

log = configurar_log()
VOZ = "pt-BR-AntonioNeural"


async def _gerar(texto, destino, velocidade, tom):
    try:
        com = edge_tts.Communicate(texto, VOZ, rate=velocidade, pitch=tom, boundary="WordBoundary")
    except TypeError:                         # versões antigas já mandam as palavras sem pedir
        com = edge_tts.Communicate(texto, VOZ, rate=velocidade, pitch=tom)
    marcas = []
    with open(destino, "wb") as f:
        async for parte in com.stream():
            if parte["type"] == "audio":
                f.write(parte["data"])
            elif parte["type"] == "WordBoundary":
                ini = parte["offset"] / 1e7
                marcas.append({"ini": ini, "fim": ini + parte["duration"] / 1e7, "texto": parte["text"]})
    return marcas


def narrar_falas(cfg, falas, pasta):
    """Narra cada fala. Devolve [{"arquivo", "texto", "marcas"}] na mesma ordem."""
    n = cfg.get("narracao", {})
    velocidade, tom = n.get("velocidade", "+8%"), n.get("tom", "+0Hz")
    saida = []
    for i, fala in enumerate(falas):
        texto = preparar_texto(fala)
        destino = pasta / f"fala_{i:02d}.mp3"
        for tentativa in range(4):
            try:
                destino.unlink(missing_ok=True)
                marcas = asyncio.run(_gerar(texto, destino, velocidade, tom))
                if destino.exists() and destino.stat().st_size > 0:
                    if not marcas:
                        log.warning(f"Fala {i + 1}: a voz não mandou o tempo das palavras; a legenda vai pelo tamanho do texto.")
                    saida.append({"arquivo": destino, "texto": texto, "marcas": marcas})
                    break
            except Exception as e:  # noqa: BLE001
                log.warning(f"Fala {i + 1}: a voz {VOZ} falhou ({tentativa + 1}/4): {e}")
            time.sleep(3 * (tentativa + 1))
        else:
            raise RuntimeError(f"Não consegui narrar a fala {i + 1} com a voz {VOZ}. Rode de novo em alguns minutos.")
    return saida
