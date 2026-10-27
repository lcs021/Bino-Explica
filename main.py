"""
Turibenção Automático
Cria o roteiro, gera as ilustrações, narra, edita e publica no YouTube e no TikTok.

Uso:
  python main.py                      -> próximo tema da lista, publica tudo
  python main.py --tema "Jonas"       -> tema escolhido
  python main.py --sem-publicar       -> só cria os vídeos (para testar)
  python main.py --retomar PASTA      -> continua um vídeo que parou no meio
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import imagens
import narracao
import roteiro as rt
import video
from util import RAIZ, carregar_config, configurar_log, ler_historico, ler_temas, salvar_historico, slug

log = configurar_log()


def escolher_tema(cfg) -> str:
    feitos = {h["tema"] for h in ler_historico(cfg)}
    for tema in ler_temas(cfg):
        if tema not in feitos:
            return tema
    log.info("Lista de temas acabou — pedindo um tema novo ao Claude.")
    return rt.sugerir_tema(cfg, sorted(feitos))


def produzir(cfg, tema: str, pasta: Path) -> dict:
    pasta.mkdir(parents=True, exist_ok=True)
    arq_rot = pasta / "roteiro.json"
    if arq_rot.exists():
        rot = json.loads(arq_rot.read_text(encoding="utf-8"))
    else:
        rot = rt.criar_roteiro_aprovado(cfg, tema)
        rot["tema"] = tema
        arq_rot.write_text(json.dumps(rot, ensure_ascii=False, indent=2), encoding="utf-8")

    brutas = imagens.gerar_cenas(cfg, rot, pasta)
    miniatura = imagens.gerar_miniatura(cfg, rot, pasta)

    # ---- vídeo principal 16:9
    horiz = [imagens.versao_horizontal(b, pasta / f"h_{b.name}") for b in brutas]
    aud_longo = narracao.narrar_cenas(cfg, rot["cenas"], pasta, "longo")
    longo = video.montar(cfg, horiz, aud_longo, [c["narracao"] for c in rot["cenas"]],
                         pasta, "video_longo", 1920, 1080)

    # ---- corte vertical 9:16 (Shorts + TikTok)
    cc = rot["curto"]["cenas"]
    vert = [imagens.versao_vertical(brutas[c["imagem"]], pasta / f"v_{i:02d}.png") for i, c in enumerate(cc)]
    aud_curto = narracao.narrar_cenas(cfg, cc, pasta, "curto")
    curto = video.montar(cfg, vert, aud_curto, [c["narracao"] for c in cc],
                         pasta, "video_curto", 1080, 1920)
    return {"roteiro": rot, "longo": longo, "curto": curto, "miniatura": miniatura}


def publicar(cfg, r: dict, pasta: Path) -> dict:
    estado_arq = pasta / "publicacao.json"
    estado = json.loads(estado_arq.read_text(encoding="utf-8")) if estado_arq.exists() else {}
    rot, pub = r["roteiro"], cfg["publicacao"]

    def etapa(nome, func):
        if estado.get(nome):
            log.info(f"{nome}: já publicado antes ({estado[nome]}), pulando.")
            return
        try:
            estado[nome] = func()
        except Exception as e:  # noqa: BLE001
            log.error(f"{nome} falhou: {e}")
            estado[nome + "_erro"] = str(e)
        estado_arq.write_text(json.dumps(estado, ensure_ascii=False, indent=2), encoding="utf-8")

    if pub["youtube"]:
        import youtube_upload as yt
        etapa("youtube_longo", lambda: yt.publicar(
            cfg, r["longo"], rot["titulo"], rot["descricao"], rot["tags"], r["miniatura"]))
        if pub["publicar_curto_no_youtube"]:
            titulo_short = f"{rot['curto']['titulo']} #Shorts"
            canal = cfg["canal"].get("marca", "o canal")
            desc = rot["curto"].get("legenda_tiktok", "") + f"\n\nVídeo completo no canal {canal}!"
            etapa("youtube_short", lambda: yt.publicar(cfg, r["curto"], titulo_short, desc, rot["tags"]))
    if pub["tiktok"]:
        import tiktok_upload as tk
        etapa("tiktok", lambda: tk.publicar(cfg, r["curto"], rot["curto"]["legenda_tiktok"]))
    if pub.get("instagram"):
        import instagram_upload as ig
        legenda = rot["curto"].get("legenda_instagram") or rot["curto"]["legenda_tiktok"]
        etapa("instagram", lambda: ig.publicar(r["curto"], legenda))
    return estado


def main():
    ap = argparse.ArgumentParser(description="Turibenção Automático")
    ap.add_argument("--tema")
    ap.add_argument("--sem-publicar", action="store_true")
    ap.add_argument("--retomar", help="pasta de um vídeo que parou no meio")
    a = ap.parse_args()

    cfg = carregar_config()
    if a.retomar:
        pasta = Path(a.retomar).resolve()
        arq = pasta / "roteiro.json"
        tema = json.loads(arq.read_text(encoding="utf-8")).get("tema") if arq.exists() else None
        tema = tema or a.tema or pasta.name
    else:
        tema = a.tema or escolher_tema(cfg)
        pasta = RAIZ / cfg["pastas"]["saida"] / f"{datetime.now():%Y-%m-%d_%H%M}_{slug(tema)}"

    log.info(f"===== Novo vídeo: {tema} =====")
    try:
        r = produzir(cfg, tema, pasta)
    except Exception as e:  # noqa: BLE001
        log.error(f"Produção interrompida: {e}")
        log.error(f"Para continuar de onde parou: python main.py --retomar \"{pasta}\"")
        sys.exit(1)

    if a.sem_publicar:
        log.info(f"Vídeos prontos (não publicados): {pasta}")
        return
    estado = publicar(cfg, r, pasta)

    hist = ler_historico(cfg)
    hist.append({"tema": tema, "titulo": r["roteiro"]["titulo"], "data": f"{datetime.now():%Y-%m-%d %H:%M}",
                 "pasta": str(pasta), "publicacao": estado})
    salvar_historico(cfg, hist)
    log.info(f"===== Concluído: {pasta} =====")
    if any(k.endswith("_erro") for k in estado):
        sys.exit(2)


if __name__ == "__main__":
    main()
