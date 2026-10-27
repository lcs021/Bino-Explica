"""
Monta com voz neural os episódios criados no site (Estúdio Bino Explica).

O site gera um arquivo "episodio-....json" (roteiro + desenhos). Você envia para a pasta
episodios/ do GitHub e este script monta os vídeos com narração, legendas e os 3 formatos.
Publica nas redes conectadas. Não usa nenhuma IA paga (nem o Gemini).
"""
import json
import os
import shutil
import sys
from datetime import datetime, timedelta, timezone

import main_gratis as mg
from util import RAIZ, carregar_config, configurar_log, ler_historico, salvar_historico, slug

log = configurar_log()
PASTA = RAIZ / "episodios"


def preparar(pacote: dict, pasta):
    """Grava o roteiro e os desenhos do site no formato que o robô já entende."""
    pasta.mkdir(parents=True, exist_ok=True)
    rot = {k: pacote.get(k) for k in ("titulo", "descricao", "tags", "personagens", "curto", "tema", "modo", "formato", "miniatura", "longo")}
    rot["cenas"] = [{"narracao": c.get("narracao", ""), "legenda_tela": c.get("legenda_tela", ""), "visual": ""}
                    for c in pacote["cenas"]]
    rot = mg.validar(rot)
    (pasta / "roteiro.json").write_text(json.dumps(rot, ensure_ascii=False, indent=2), encoding="utf-8")
    svgs = pacote.get("svgs", [])
    prontos = {}                       # vídeo longo: cada desenho serve a 2 falas seguidas
    for i, c in enumerate(pacote["cenas"][:len(rot["cenas"])]):
        d = c.get("img", i)
        d = d if isinstance(d, int) and 0 <= d < max(len(svgs), 1) else i
        destino = pasta / f"cena_{i:02d}.png"
        if d in prontos:
            shutil.copyfile(prontos[d], destino)
            continue
        limpo = mg.limpar_svg(svgs[d] if d < len(svgs) and svgs[d] else "")
        if not (limpo and mg.svg_para_png(limpo, destino)):
            from PIL import Image
            Image.new("RGB", (1920, 1080), "white").save(destino)
        prontos[d] = destino
    return rot


def main():
    cfg = carregar_config()
    pub = cfg["publicacao"]
    pub["youtube"] = bool(os.environ.get("YOUTUBE_REFRESH_TOKEN") or os.environ.get("YOUTUBE_TOKEN_JSON"))
    pub["tiktok"] = bool(os.environ.get("TIKTOK_REFRESH_TOKEN") or
                         ((RAIZ / "tokens/tiktok.enc").exists() and os.environ.get("TIKTOK_CLIENT_SECRET")))
    pub["instagram"] = bool(os.environ.get("INSTAGRAM_TOKEN"))
    arquivos = sorted(PASTA.glob("*.json"))
    if not arquivos:
        log.info("Nenhum episódio novo na pasta episodios/.")
        return
    conectado = pub["youtube"] or pub["tiktok"] or pub["instagram"]
    agora = datetime.now(timezone.utc)
    falhou = False
    feitos = PASTA / "feitos"
    feitos.mkdir(exist_ok=True)
    # episódios já montados antes (pelo título) e nesta rodada: não monta duas vezes
    ja_feitos = {h.get("titulo") for h in ler_historico(cfg) if h.get("origem") == "site"}
    for arq in arquivos:
        pacote = json.loads(arq.read_text(encoding="utf-8"))
        tema = pacote.get("tema") or pacote.get("titulo") or arq.stem
        if pacote.get("titulo") in ja_feitos:
            log.info(f"Pulando {arq.name}: este episódio já foi montado (arquivo repetido).")
            shutil.move(str(arq), feitos / arq.name)
            continue
        # cronograma: com redes conectadas, só posta quando chega o horário do episódio
        if conectado and pacote.get("agenda"):
            try:
                quando = datetime.fromisoformat(pacote["agenda"].replace("Z", "+00:00"))
            except ValueError:
                quando = agora
            if quando - agora > timedelta(minutes=45):
                log.info(f"Aguardando o horário: {pacote.get('titulo')} → {quando.astimezone(timezone(timedelta(hours=-3))):%d/%m %H:%M}")
                continue
        ja_feitos.add(pacote.get("titulo"))
        biblico = pacote.get("modo") == "biblico"
        cfg["canal"]["marca"] = "Turibenção" if biblico else cfg["canal"].get("marca", "@binoexplica")
        pub["feito_para_criancas"] = biblico
        # no cronograma, o vídeo longo vai ao YouTube só nos episódios longos (19h30);
        # os do meio-dia sobem só como Shorts/TikTok/Reels
        pub["youtube_longo"] = bool(pacote.get("longo")) or not pacote.get("agenda")
        pasta = RAIZ / cfg["pastas"]["saida"] / f"{datetime.now():%Y-%m-%d_%H%M}_{slug(tema)}"
        log.info(f"===== Montando episódio do site: {tema} =====")
        try:
            preparar(pacote, pasta)
            res = mg.produzir(cfg, tema, pasta, pacote.get("formato") or "explicacao")
            estado = {}
            if pub["youtube"] or pub["tiktok"] or pub["instagram"]:
                import main as motor
                estado = motor.publicar(cfg, res, pasta)
            hist = ler_historico(cfg)
            hist.append({"tema": tema, "titulo": res["roteiro"]["titulo"], "origem": "site",
                         "data": f"{datetime.now():%Y-%m-%d %H:%M}", "publicacao": estado})
            salvar_historico(cfg, hist)
            shutil.move(str(arq), feitos / arq.name)
        except Exception as e:  # noqa: BLE001
            log.error(f"Não consegui montar {arq.name}: {e}")
            falhou = True
    if falhou:
        sys.exit(1)


if __name__ == "__main__":
    main()
