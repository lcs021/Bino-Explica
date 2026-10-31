"""
Monta os casos criados no site Caso Ao Vivo (crimes reais).

O site gera um arquivo "caso-....json" (roteiro + plano de edição). Você envia para a pasta casos/
do GitHub e este script narra com a voz masculina (pt-BR-AntonioNeural, mesma tecnologia do Bino),
edita o vídeo (caso_edicao.py) e guarda o MP4 para baixar.
Trilha: coloque MP3 sem direitos autorais em assets/caso/musicas; sem música lá, o robô gera uma trilha sombria.
"""
import base64
import json
import os
import random
import time
import shutil
import sys
from datetime import datetime

import caso_edicao
import caso_pacote
import caso_pesquisa
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
                      "pausa": bool(c.get("pausa")),
                      "info": str(c.get("info", "")).strip().lower(),
                      "busca_imagem": str(c.get("busca_imagem", "")).strip()[:120],
                      "img3d": c.get("img3d") if isinstance(c.get("img3d"), str) and c["img3d"].startswith("data:image") else "",
                      "prompt_3d": str(c.get("prompt_3d", "")).strip()} for c in cenas]
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
        log.info(f"===== Caso Ao Vivo: {titulo} ({len(caso['cenas'])} cenas) =====")
        inicio = time.time()
        try:
            try:
                pesquisa = caso_pesquisa.pesquisar(caso, pasta, log.info)
            except Exception as e:  # noqa: BLE001
                log.warning(f"A pesquisa automática falhou ({e}); o vídeo sai só com artes ilustrativas.")
                pesquisa = {"data": "", "artigos": [], "fontes": [], "checagem": [], "imagens": {},
                            "limitacoes": [f"A pesquisa automática falhou ({e}). Confira todos os fatos à mão."]}
            cenas3d = {}
            for i, c in enumerate(caso["cenas"]):
                if c.get("img3d"):
                    arq3d = pasta / "imagens" / f"cena_{i + 1:02d}_3d.jpg"
                    arq3d.parent.mkdir(parents=True, exist_ok=True)
                    arq3d.write_bytes(base64.b64decode(c["img3d"].split(",", 1)[1]))
                    cenas3d[i] = arq3d
                    c["img3d"] = ""
            if cenas3d:
                log.info(f"{len(cenas3d)} cena(s) em animação 3D enviadas pelo site.")
            falas = narrar_falas(cfg, [c["fala"] for c in caso["cenas"]], pasta)
            formatos = caso.get("formatos") or [caso.get("aspect") or "9:16"]
            for fmt in formatos:
                vertical = fmt != "16:9"
                reels = vertical and caso.get("layout") == "reels"
                shorts = vertical and str(caso.get("formato", "")).startswith("shorts")
                nome = ("video-reels.mp4" if reels else "video-shorts.mp4" if shorts
                        else "video-tiktok.mp4" if vertical else "video-horizontal.mp4")
                log.info(f"Narração pronta. Editando {nome}…")
                _, pags, info = caso_edicao.montar(caso, falas, pasta / nome, vertical=vertical, musica=musica(cfg),
                                                   volume_musica=cfg["video"].get("musica_volume", 0.12), reels=reels,
                                                   max_dur=caso.get("duracao_max") if vertical else None,
                                                   imagens=pesquisa.get("imagens"), cenas3d=cenas3d)
            (pasta / "legendas.srt").write_text(caso_edicao.srt(pags), encoding="utf-8")
            (pasta / "pacote-de-producao.md").write_text(caso_pacote.gerar(caso, pesquisa, info, falas, pags, nome), encoding="utf-8")
            imgs = pesquisa.get("imagens", {})
            (pasta / "imagens" / "creditos.txt").write_text(
                "\n".join(f"Cena {i + 1}: {m['titulo']} — {m['autor']} — {m['licenca']} — {m['pagina']}" for i, m in sorted(imgs.items()))
                or "Nenhuma imagem de arquivo usada.", encoding="utf-8")
            chk = pesquisa.get("checagem", [])
            nao = sum(1 for x in chk if x["status"] == "Não verificado")
            post = [titulo, ""]
            for t in caso.get("titulos", []):
                post.append(f"- {t}")
            if caso.get("legenda"):
                post += ["", caso["legenda"]]
            if caso.get("hashtags"):
                post += ["", " ".join(caso["hashtags"])]
            q = caso.get("posts") or {}
            sh = q.get("shorts") or {}
            if sh.get("titulo"):
                post += ["", "===== YOUTUBE SHORTS =====", f"Título: {sh.get('titulo', '')}", sh.get("descricao", ""),
                         " ".join(sh.get("hashtags", []))]
            elif q:
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
            minutos = (time.time() - inicio) / 60
            log.info(f"Pronto em {minutos:.1f} min: {pasta}")
            resumo = os.environ.get("GITHUB_STEP_SUMMARY")
            if resumo:
                with open(resumo, "a", encoding="utf-8") as f:
                    f.write(f"- ✅ **{titulo}**: pronto em {minutos:.1f} min · {len(imgs)} foto(s) de arquivo · "
                            f"{len(chk) - nao}/{len(chk)} fatos conferidos. Baixe em *Artifacts*, no fim desta página.\n")
                    for x in pesquisa.get("limitacoes", []):
                        f.write(f"  - ⚠️ {x}\n")
        except Exception as e:  # noqa: BLE001
            log.exception(f"Falha ao montar {arq.name}: {e}")
            falhou = True
            resumo = os.environ.get("GITHUB_STEP_SUMMARY")
            if resumo:
                with open(resumo, "a", encoding="utf-8") as f:
                    f.write(f"- ❌ **{titulo}**: falhou ({e}). O arquivo continua na pasta casos/ para tentar de novo.\n")
    if falhou:
        sys.exit(1)


if __name__ == "__main__":
    main()
