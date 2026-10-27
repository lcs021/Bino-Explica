"""Publicação no TikTok pela Content Posting API (Direct Post, envio do arquivo)."""
import json
import os
import time
from pathlib import Path

import requests

from util import RAIZ, configurar_log

log = configurar_log()
API = "https://open.tiktokapis.com/v2"
TOKEN = RAIZ / "token_tiktok.json"
COFRE = RAIZ / "tokens" / "tiktok.enc"     # criptografado com o TIKTOK_CLIENT_SECRET


def _fernet():
    import base64
    import hashlib
    from cryptography.fernet import Fernet
    chave = hashlib.sha256(("bino:" + os.environ["TIKTOK_CLIENT_SECRET"]).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(chave))


def guardar_no_cofre(dados: dict):
    COFRE.parent.mkdir(exist_ok=True)
    COFRE.write_bytes(_fernet().encrypt(json.dumps({"refresh_token": dados["refresh_token"]}).encode()))


def _salvar_token(dados: dict):
    dados["expira_em"] = time.time() + int(dados.get("expires_in", 86400)) - 300
    TOKEN.write_text(json.dumps(dados, indent=2), encoding="utf-8")


def trocar_codigo(codigo: str):
    r = requests.post(f"{API}/oauth/token/", data={
        "client_key": os.environ["TIKTOK_CLIENT_KEY"],
        "client_secret": os.environ["TIKTOK_CLIENT_SECRET"],
        "code": codigo,
        "grant_type": "authorization_code",
        "redirect_uri": os.environ["TIKTOK_REDIRECT_URI"],
    }, timeout=30)
    dados = r.json()
    if "access_token" not in dados:
        raise RuntimeError(f"TikTok recusou o código: {dados}")
    _salvar_token(dados)


def _renovar(refresh_token: str) -> dict:
    r = requests.post(f"{API}/oauth/token/", data={
        "client_key": os.environ["TIKTOK_CLIENT_KEY"],
        "client_secret": os.environ["TIKTOK_CLIENT_SECRET"],
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }, timeout=30)
    novo = r.json()
    if "access_token" not in novo:
        raise RuntimeError(f"Não renovou o token do TikTok, autorize de novo: {novo}")
    return novo


def _token() -> str:
    if COFRE.exists() and os.environ.get("TIKTOK_CLIENT_SECRET"):   # nuvem: conectado pelo guia
        atual = json.loads(_fernet().decrypt(COFRE.read_bytes()))["refresh_token"]
        novo = _renovar(atual)
        if novo.get("refresh_token") and novo["refresh_token"] != atual:
            guardar_no_cofre(novo)            # o robô salva o token novo no repositório
        return novo["access_token"]
    if os.environ.get("TIKTOK_REFRESH_TOKEN"):        # nuvem (GitHub Secrets)
        novo = _renovar(os.environ["TIKTOK_REFRESH_TOKEN"])
        if novo.get("refresh_token") and novo["refresh_token"] != os.environ["TIKTOK_REFRESH_TOKEN"]:
            log.warning("O TikTok trocou o refresh token. Rode autorizar_tiktok.py e atualize o segredo "
                        "TIKTOK_REFRESH_TOKEN no GitHub.")
        return novo["access_token"]
    if not TOKEN.exists():
        raise RuntimeError("TikTok não autorizado. Rode: python autorizar_tiktok.py")
    dados = json.loads(TOKEN.read_text(encoding="utf-8"))
    if time.time() > dados.get("expira_em", 0):
        novo = _renovar(dados["refresh_token"])
        _salvar_token(novo)
        dados = novo
    return dados["access_token"]


def _post(caminho, token, corpo):
    r = requests.post(f"{API}{caminho}", json=corpo, timeout=60, headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=UTF-8",
    })
    dados = r.json()
    erro = dados.get("error", {})
    if erro.get("code") not in (None, "ok"):
        raise RuntimeError(f"TikTok {caminho}: {erro}")
    return dados.get("data", {})


def publicar(cfg, video: Path, legenda: str) -> str:
    token = _token()
    info = _post("/post/publish/creator_info/query/", token, {})
    opcoes = info.get("privacy_level_options", [])
    privacidade = cfg["publicacao"]["tiktok_privacidade"]
    if privacidade not in opcoes:
        log.warning(f"TikTok não permite '{privacidade}' nesta conta/app; usando SELF_ONLY. Opções: {opcoes}")
        privacidade = "SELF_ONLY"

    tamanho = video.stat().st_size
    pedaco = tamanho if tamanho <= 64 * 1024 * 1024 else 10 * 1024 * 1024
    total = max(1, tamanho // pedaco)
    dados = _post("/post/publish/video/init/", token, {
        "post_info": {
            "title": legenda[:2200],
            "privacy_level": privacidade,
            "disable_duet": False,
            "disable_comment": False,
            "disable_stitch": False,
            "video_cover_timestamp_ms": 1500,
            "is_aigc": True,   # rótulo de conteúdo gerado por IA (transparência)
        },
        "source_info": {"source": "FILE_UPLOAD", "video_size": tamanho,
                        "chunk_size": pedaco, "total_chunk_count": total},
    })
    publish_id, url = dados["publish_id"], dados["upload_url"]

    with open(video, "rb") as f:
        for i in range(total):
            inicio = i * pedaco
            fim = tamanho - 1 if i == total - 1 else inicio + pedaco - 1
            f.seek(inicio)
            bloco = f.read(fim - inicio + 1)
            r = requests.put(url, data=bloco, timeout=300, headers={
                "Content-Type": "video/mp4",
                "Content-Length": str(len(bloco)),
                "Content-Range": f"bytes {inicio}-{fim}/{tamanho}",
            })
            if r.status_code not in (200, 201, 206):
                raise RuntimeError(f"Envio ao TikTok falhou ({r.status_code}): {r.text[:300]}")
            log.info(f"TikTok: enviado {int((fim + 1) / tamanho * 100)}%")

    for _ in range(30):     # acompanha o processamento (até ~5 min)
        time.sleep(10)
        st = _post("/post/publish/status/fetch/", token, {"publish_id": publish_id})
        situacao = st.get("status")
        if situacao == "PUBLISH_COMPLETE":
            log.info(f"TikTok publicado ({privacidade}).")
            break
        if situacao == "FAILED":
            raise RuntimeError(f"TikTok recusou o vídeo: {st.get('fail_reason')}")
    return publish_id
