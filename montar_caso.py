"""
Monta com a voz neural do Bino Explica os casos criados no site Caso Ao Vivo.

O site gera um arquivo "caso-....json" (roteiro do caso). Você envia para a pasta casos/
do GitHub e este script narra com a mesma voz do Bino (edge-tts, config.yaml > narracao),
monta o vídeo com o apresentador e guarda o MP4 para baixar.
"""
import json
import random
import shutil
import sys
from datetime import datetime

import caso_video
import narracao
from narracao import narrar_cenas
from util import RAIZ, carregar_config, configurar_log, slug

log = configurar_log()
PASTA = RAIZ / "casos"
# O apresentador é homem: o Caso Ao Vivo narra só com voz masculina.
# (O Bino Explica continua com a voz do config.yaml.)
VOZ_CASO = "pt-BR-AntonioNeural"


def validar(caso: dict) -> dict:
    cenas = [c for c in caso.get("cenas", []) if str(c.get("fala", "")).strip()]
    if not cenas:
        raise ValueError("o arquivo não tem nenhuma fala")
    caso["cenas"] = [{"fala": str(c["fala"]).strip(),
                      "tela_titulo": str(c.get("tela_titulo", "")).strip(),
                      "tela_texto": str(c.get("tela_texto", "")).strip()} for c in cenas]
    return caso


def musica(cfg):
    pasta = RAIZ / cfg["video"].get("pasta_musicas", "assets/musicas")
    opcoes = sorted(pasta.glob("*.mp3")) if pasta.exists() else []
    return random.choice(opcoes) if opcoes else None


def main():
    cfg = carregar_config()
    cfg["narracao"] = dict(cfg["narracao"], voz=VOZ_CASO)
    narracao.RESERVAS = [VOZ_CASO]   # sem reserva feminina: se falhar, tenta de novo em vez de trocar de voz
    arquivos = sorted(PASTA.glob("*.json"))
    if not arquivos:
        log.info("Nenhum caso novo na pasta casos/.")
        return
    feitos = PASTA / "feitos"
    feitos.mkdir(exist_ok=True)
    falhou = False
    for arq in arquivos:
        try:
            caso = validar(json.loads(arq.read_text(encoding="utf-8")))
        except Exception as e:  # noqa: BLE001
            log.error(f"{arq.name}: arquivo inválido ({e}).")
            falhou = True
            continue
        titulo = caso.get("titulo_caso") or arq.stem
        pasta = RAIZ / cfg["pastas"]["saida"] / "casos" / f"{datetime.now():%Y-%m-%d_%H%M}_{slug(titulo)}"
        pasta.mkdir(parents=True, exist_ok=True)
        log.info(f"===== Caso Ao Vivo: {titulo} =====")
        try:
            vozes = narrar_cenas(cfg, [{"narracao": c["fala"]} for c in caso["cenas"]], pasta, "fala")
            formatos = caso.get("formatos") or [caso.get("aspect") or "9:16"]
            for fmt in formatos:
                vertical = fmt != "16:9"
                reels = vertical and caso.get("layout") == "reels"
                nome = "video-reels.mp4" if reels else ("video-vertical.mp4" if vertical else "video-horizontal.mp4")
                log.info(f"Montando {nome}…")
                _, tempos = caso_video.montar(caso, vozes, pasta / nome, vertical=vertical,
                                              musica=musica(cfg), volume_musica=cfg["video"].get("musica_volume", 0.12), reels=reels)
            (pasta / "legendas.srt").write_text(caso_video.srt(caso["cenas"], tempos), encoding="utf-8")
            post = [titulo, ""]
            for t in caso.get("titulos", []):
                post.append(f"- {t}")
            if caso.get("legenda"):
                post += ["", caso["legenda"]]
            if caso.get("hashtags"):
                post += ["", " ".join(caso["hashtags"])]
            if caso.get("conferir"):
                post += ["", "CONFERIR ANTES DE POSTAR"] + [f"- {x.get('fato')} (buscar: {x.get('buscar')})" for x in caso["conferir"]]
            (pasta / "post.txt").write_text("\n".join(post), encoding="utf-8")
            for p in pasta.glob("_*"):
                p.unlink(missing_ok=True)
            shutil.move(str(arq), feitos / arq.name)
            log.info(f"Pronto: {pasta}")
        except Exception as e:  # noqa: BLE001
            log.exception(f"Falha ao montar {arq.name}: {e}")
            falhou = True
    if falhou:
        sys.exit(1)


if __name__ == "__main__":
    main()
