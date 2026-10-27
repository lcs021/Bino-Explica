"""Publicação de Reels no Instagram (API oficial da Meta, envio direto do arquivo).

Precisa: conta Instagram Profissional ligada a uma Página do Facebook e o segredo
INSTAGRAM_TOKEN (token de acesso da Página, que não expira). Veja o guia "Conectar contas".
"""
import os
import time
from pathlib import Path

import requests

from util import configurar_log

log = configurar_log()
GRAPH = "https://graph.facebook.com/v21.0"


def _token():
    t = os.environ.get("INSTAGRAM_TOKEN")
    if not t:
        raise RuntimeError("Instagram não conectado (segredo INSTAGRAM_TOKEN).")
    return t


def _ig_user_id(token) -> str:
    if os.environ.get("INSTAGRAM_USER_ID"):
        return os.environ["INSTAGRAM_USER_ID"]
    r = requests.get(f"{GRAPH}/me", params={"fields": "instagram_business_account", "access_token": token}, timeout=30).json()
    if r.get("instagram_business_account"):
        return r["instagram_business_account"]["id"]
    r = requests.get(f"{GRAPH}/me/accounts", params={"fields": "instagram_business_account", "access_token": token},
                     timeout=30).json()
    for pag in r.get("data", []):
        if pag.get("instagram_business_account"):
            return pag["instagram_business_account"]["id"]
    raise RuntimeError(f"Não achei a conta do Instagram ligada à Página: {r}")


def publicar(video: Path, legenda: str) -> str:
    token = _token()
    ig = _ig_user_id(token)
    r = requests.post(f"{GRAPH}/{ig}/media", timeout=60, data={
        "media_type": "REELS", "upload_type": "resumable", "caption": legenda[:2200],
        "share_to_feed": "true", "access_token": token}).json()
    if "id" not in r:
        raise RuntimeError(f"Instagram recusou o container: {r}")
    cid = r["id"]
    tamanho = video.stat().st_size
    with open(video, "rb") as f:
        up = requests.post(f"https://rupload.facebook.com/ig-api-upload/v21.0/{cid}", data=f, timeout=600, headers={
            "Authorization": f"OAuth {token}", "offset": "0", "file_size": str(tamanho)})
    if up.status_code != 200 or not up.json().get("success"):
        raise RuntimeError(f"Envio ao Instagram falhou ({up.status_code}): {up.text[:300]}")
    log.info("Instagram: vídeo enviado, aguardando processamento…")
    for _ in range(40):      # até ~7 min
        time.sleep(10)
        st = requests.get(f"{GRAPH}/{cid}", params={"fields": "status_code,status", "access_token": token},
                          timeout=30).json()
        if st.get("status_code") == "FINISHED":
            break
        if st.get("status_code") == "ERROR":
            raise RuntimeError(f"Instagram não aceitou o vídeo: {st}")
    pub = requests.post(f"{GRAPH}/{ig}/media_publish", data={"creation_id": cid, "access_token": token},
                        timeout=60).json()
    if "id" not in pub:
        raise RuntimeError(f"Instagram não publicou: {pub}")
    log.info(f"Instagram publicado (Reel {pub['id']}).")
    return pub["id"]
