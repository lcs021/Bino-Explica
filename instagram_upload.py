"""Publicação de Reels no Instagram pela API oficial da Meta (envio direto do arquivo, sem precisar de link público).

Aceita os dois tipos de conexão:
- "Instagram com login do Instagram" (mais simples, NÃO precisa de Página do Facebook): token começa com "IG".
  Esse token vale 60 dias; o robô renova sozinho e guarda a versão nova criptografada em reels/token.enc.
- "Instagram com login do Facebook" (conta profissional ligada a uma Página): token da Página.

Segredo no GitHub: INSTAGRAM_TOKEN (e, opcional, INSTAGRAM_USER_ID).
"""
import base64
import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

from util import RAIZ, configurar_log

log = configurar_log()
VERSAO = "v21.0"
COFRE = RAIZ / "reels" / "token.enc"


# ------------------------------------------------------------------ token
def _fernet():
    from cryptography.fernet import Fernet
    base = os.environ.get("INSTAGRAM_TOKEN", "")
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(("bino:" + base).encode()).digest()))


def _token():
    t = os.environ.get("INSTAGRAM_TOKEN")
    if not t:
        raise RuntimeError("Instagram não conectado: falta o segredo INSTAGRAM_TOKEN no GitHub.")
    if COFRE.exists():
        try:
            dados = json.loads(_fernet().decrypt(COFRE.read_bytes()))
            return dados["token"]
        except Exception:  # noqa: BLE001  (segredo trocado: o cofre antigo não vale mais)
            pass
    return t


def _graph(token):
    return f"https://graph.instagram.com/{VERSAO}" if token.startswith("IG") else f"https://graph.facebook.com/{VERSAO}"


def conectado() -> bool:
    return bool(os.environ.get("INSTAGRAM_TOKEN"))


def renovar_token():
    """Token do login do Instagram vale 60 dias: renova (no máximo 1x por semana) e guarda no cofre."""
    token = _token()
    if not token.startswith("IG"):
        return False
    if COFRE.exists():
        try:
            dados = json.loads(_fernet().decrypt(COFRE.read_bytes()))
            if time.time() - dados.get("quando", 0) < 7 * 86400:
                return False
        except Exception:  # noqa: BLE001
            pass
    r = requests.get("https://graph.instagram.com/refresh_access_token",
                     params={"grant_type": "ig_refresh_token", "access_token": token}, timeout=30).json()
    if "access_token" not in r:
        log.warning(f"Não consegui renovar o token do Instagram: {r}")
        return False
    COFRE.parent.mkdir(exist_ok=True)
    COFRE.write_bytes(_fernet().encrypt(json.dumps({"token": r["access_token"], "quando": time.time()}).encode()))
    log.info("Token do Instagram renovado por mais 60 dias.")
    return True


def ig_user_id(token=None) -> str:
    token = token or _token()
    if os.environ.get("INSTAGRAM_USER_ID"):
        return os.environ["INSTAGRAM_USER_ID"]
    g = _graph(token)
    if token.startswith("IG"):
        r = requests.get(f"{g}/me", params={"fields": "user_id,username", "access_token": token}, timeout=30).json()
        if r.get("user_id") or r.get("id"):
            return str(r.get("user_id") or r["id"])
        raise RuntimeError(f"Token do Instagram inválido: {r}")
    r = requests.get(f"{g}/me", params={"fields": "instagram_business_account", "access_token": token}, timeout=30).json()
    if r.get("instagram_business_account"):
        return r["instagram_business_account"]["id"]
    r = requests.get(f"{g}/me/accounts", params={"fields": "instagram_business_account", "access_token": token},
                     timeout=30).json()
    for pag in r.get("data", []):
        if pag.get("instagram_business_account"):
            return pag["instagram_business_account"]["id"]
    raise RuntimeError(f"Não achei a conta do Instagram ligada à Página: {r}")


def verificar_conta():
    """Auditoria: conta conectada, profissional e com permissão de publicar. Devolve dict com o resultado."""
    token = _token()
    g = _graph(token)
    ig = ig_user_id(token)
    campos = "username,account_type,followers_count,media_count" if token.startswith("IG") else \
        "username,name,followers_count,media_count"
    info = requests.get(f"{g}/{ig}", params={"fields": campos, "access_token": token}, timeout=30).json()
    if "error" in info:
        raise RuntimeError(f"a Meta recusou a leitura da conta: {info['error'].get('message')}")
    limite = requests.get(f"{g}/{ig}/content_publishing_limit", params={"fields": "quota_usage,config",
                                                                        "access_token": token}, timeout=30).json()
    return {"ig_id": ig, "conta": info, "limite": limite}


# ------------------------------------------------------------------ publicar
def recentes(limite=15):
    token = _token()
    g = _graph(token)
    r = requests.get(f"{g}/{ig_user_id(token)}/media", timeout=30, params={
        "fields": "id,caption,permalink,timestamp,media_type", "limit": limite, "access_token": token}).json()
    return r.get("data", [])


def ja_publicado(legenda, horas=72):
    """Controle de duplicidade: procura nos posts recentes um com o mesmo começo de legenda."""
    inicio = (legenda or "")[:80].strip()
    agora = datetime.now(timezone.utc)
    for m in recentes():
        try:
            quando = datetime.strptime(m["timestamp"], "%Y-%m-%dT%H:%M:%S%z")
        except (KeyError, ValueError):
            continue
        if (agora - quando).total_seconds() < horas * 3600 and (m.get("caption") or "")[:80].strip() == inicio:
            return m
    return None


def permalink(media_id):
    token = _token()
    r = requests.get(f"{_graph(token)}/{media_id}", params={"fields": "permalink", "access_token": token},
                     timeout=30).json()
    return r.get("permalink", "")


def publicar(video: Path, legenda: str, capa_ms: int = None) -> str:
    """Envia e publica o Reel. Devolve o id do post (só depois da confirmação da Meta)."""
    token = _token()
    g = _graph(token)
    ig = ig_user_id(token)
    dados = {"media_type": "REELS", "upload_type": "resumable", "caption": legenda[:2200],
             "share_to_feed": "true", "access_token": token}
    if capa_ms is not None:
        dados["thumb_offset"] = str(int(capa_ms))
    r = requests.post(f"{g}/{ig}/media", timeout=60, data=dados).json()
    if "id" not in r:
        raise RuntimeError(f"Instagram recusou o container: {r}")
    cid = r["id"]
    log.info(f"Instagram: container criado {r}")
    conteudo = Path(video).read_bytes()
    padrao = f"https://rupload.facebook.com/ig-api-upload/{VERSAO}/{cid}"
    tentativas = [(r.get("uri") or padrao, "OAuth"), (padrao, "OAuth"), (r.get("uri") or padrao, "Bearer")]
    erros = []
    for url, tipo in dict.fromkeys(tentativas):
        up = requests.post(url, data=conteudo, timeout=900, headers={
            "Authorization": f"{tipo} {token}", "offset": "0", "file_size": str(len(conteudo)),
            "Content-Type": "application/octet-stream"})
        try:
            ok = up.status_code == 200 and up.json().get("success")
        except ValueError:
            ok = False
        if ok:
            break
        erros.append(f"{url.split('/')[2]} {tipo} → {up.status_code}: {up.text[:200]}")
        log.warning(f"Envio ao Instagram recusado ({erros[-1]}); tentando outro jeito.")
    else:
        raise RuntimeError("Envio ao Instagram falhou: " + " | ".join(erros))
    log.info("Instagram: vídeo enviado, aguardando processamento…")
    for _ in range(60):      # até ~10 min
        time.sleep(10)
        st = requests.get(f"{g}/{cid}", params={"fields": "status_code,status", "access_token": token},
                          timeout=30).json()
        if st.get("status_code") == "FINISHED":
            break
        if st.get("status_code") in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Instagram não aceitou o vídeo: {st}")
    else:
        raise RuntimeError("Instagram demorou demais para processar o vídeo.")
    pub = requests.post(f"{g}/{ig}/media_publish", data={"creation_id": cid, "access_token": token},
                        timeout=60).json()
    if "id" not in pub:
        raise RuntimeError(f"Instagram não publicou: {pub}")
    log.info(f"Instagram publicado (Reel {pub['id']}).")
    return pub["id"]


# ------------------------------------------------------------------ resultados
METRICAS = ["views", "reach", "likes", "comments", "shares", "saved", "total_interactions",
            "ig_reels_avg_watch_time", "ig_reels_video_view_total_time"]


def insights(media_id):
    token = _token()
    g = _graph(token)
    res = {}
    for m in METRICAS:                       # uma por vez: se a Meta trocar o nome de uma, as outras continuam
        r = requests.get(f"{g}/{media_id}/insights", params={"metric": m, "access_token": token}, timeout=30).json()
        for d in r.get("data", []):
            v = d.get("values", [{}])[0].get("value")
            if v is None and "total_value" in d:
                v = d["total_value"].get("value")
            res[d.get("name", m)] = v
    return res


def seguidores():
    token = _token()
    r = requests.get(f"{_graph(token)}/{ig_user_id(token)}", params={"fields": "followers_count,media_count",
                                                                      "access_token": token}, timeout=30).json()
    return r.get("followers_count")
