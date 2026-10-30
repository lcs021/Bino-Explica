"""
Monta os casos criados no site Caso Ao Vivo (crimes reais).

O site gera um arquivo "caso-....json" (roteiro + plano de edição). Você envia para a pasta casos/
do GitHub e este script narra com a voz masculina (pt-BR-AntonioNeural, mesma tecnologia do Bino),
edita o vídeo (caso_edicao.py) e guarda o MP4 para baixar.
Trilha: coloque MP3 sem direitos autorais em assets/caso/musicas; sem música lá, o robô gera uma trilha sombria.
"""
import json
import random
import shutil
import sys
from datetime import datetime

import caso_edicao
from caso_voz import narrar_falas
from util import RAIZ, carregar_config, configurar_log, slug

log = configurar_log()
PASTA = RAIZ / "casos"


def validar(caso: dict) -> dict:
    cenas = [c for c in caso.get("cenas", []) if str(c.get("fala", "")).strip()]
    if not cenas:
        raise ValueError("o arquivo não tem nenhuma fala")
    caso["cenas"] = [{"fala": str(c["fala"]).strip(),
                      "tela_titulo": str(c.get("tela_titulo", "")).strip(),
                      "tela_texto": str(c.get("tela_texto", "")).strip(),
                      "apoio": c.get("apoio") if isinstance(c.get("apoio"), dict) else None,
                      "destaques": [str(x) for x in c.get("destaques", []) if str(x).strip()][:3],
                      "pausa": bool(c.get("pausa"))} for c in cenas]
    return caso


def musica(cfg):
    pasta = RAIZ / "assets" / "caso" / "musicas"      # separada das músicas do Bino
    opcoes = sorted(pasta.glob("*.mp3")) if pasta.exists() else []
    return random.choice(opcoes) if opcoes else None


def main():
    cfg = carregar_config()
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
            falas = narrar_falas(cfg, [c["fala"] for c in caso["cenas"]], pasta)
            formatos = caso.get("formatos") or [caso.get("aspect") or "9:16"]
            for fmt in formatos:
                vertical = fmt != "16:9"
                reels = vertical and caso.get("layout") == "reels"
                nome = "video-reels.mp4" if reels else ("video-vertical.mp4" if vertical else "video-horizontal.mp4")
                log.info(f"Montando {nome}…")
                _, pags = caso_edicao.montar(caso, falas, pasta / nome, vertical=vertical, musica=musica(cfg),
                                             volume_musica=cfg["video"].get("musica_volume", 0.12), reels=reels)
            (pasta / "legendas.srt").write_text(caso_edicao.srt(pags), encoding="utf-8")
            post = [titulo, ""]
            for t in caso.get("titulos", []):
                post.append(f"- {t}")
            if caso.get("legenda"):
                post += ["", caso["legenda"]]
            if caso.get("hashtags"):
                post += ["", " ".join(caso["hashtags"])]
            q = caso.get("posts") or {}
            if q:
                t, i, y = q.get("tiktok") or {}, q.get("instagram") or {}, q.get("youtube") or {}
                post += ["", "===== TIKTOK =====", t.get("legenda", ""), " ".join(t.get("hashtags", [])),
                         "", "===== INSTAGRAM REELS =====", i.get("legenda", ""), " ".join(i.get("hashtags", [])),
                         "", "===== YOUTUBE =====", f"Título: {y.get('titulo', '')}", y.get("descricao", ""),
                         f"Tags: {', '.join(y.get('tags', []))}"]
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
