"""Publicação no YouTube (vídeo principal + Shorts) pela YouTube Data API v3."""
import json
import os
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from util import RAIZ, configurar_log

log = configurar_log()
ESCOPOS = ["https://www.googleapis.com/auth/youtube.upload",
           "https://www.googleapis.com/auth/youtube"]
SEGREDO = RAIZ / "client_secret.json"
TOKEN = RAIZ / "token_youtube.json"


def credenciais(interativo=False) -> Credentials:
    if os.environ.get("YOUTUBE_REFRESH_TOKEN"):       # nuvem: 3 segredos simples
        cred = Credentials.from_authorized_user_info({
            "client_id": os.environ["YOUTUBE_CLIENT_ID"],
            "client_secret": os.environ["YOUTUBE_CLIENT_SECRET"],
            "refresh_token": os.environ["YOUTUBE_REFRESH_TOKEN"],
            "token_uri": "https://oauth2.googleapis.com/token"}, ESCOPOS)
        cred.refresh(Request())
        return cred
    if os.environ.get("YOUTUBE_TOKEN_JSON"):          # nuvem (GitHub Secrets)
        cred = Credentials.from_authorized_user_info(json.loads(os.environ["YOUTUBE_TOKEN_JSON"]), ESCOPOS)
        cred.refresh(Request())
        return cred
    cred = Credentials.from_authorized_user_file(str(TOKEN), ESCOPOS) if TOKEN.exists() else None
    if cred and cred.expired and cred.refresh_token:
        cred.refresh(Request())
    if not cred or not cred.valid:
        if not interativo:
            raise RuntimeError("YouTube não autorizado. Rode: python autorizar_youtube.py")
        flow = InstalledAppFlow.from_client_secrets_file(str(SEGREDO), ESCOPOS)
        cred = flow.run_local_server(port=0)
    TOKEN.write_text(cred.to_json(), encoding="utf-8")
    return cred


def publicar(cfg, video: Path, titulo: str, descricao: str, tags: list,
             miniatura: Path = None) -> str:
    yt = build("youtube", "v3", credentials=credenciais())
    pub = cfg["publicacao"]
    corpo = {
        "snippet": {
            "title": titulo[:100],
            "description": descricao[:4900],
            "tags": tags,
            "categoryId": pub["youtube_categoria"],
            "defaultLanguage": "pt-BR",
            "defaultAudioLanguage": "pt-BR",
        },
        "status": {
            "privacyStatus": pub["youtube_privacidade"],
            # Infantil (COPPA) = True; Bino Explica (público geral) = False
            "selfDeclaredMadeForKids": bool(pub.get("feito_para_criancas", True)),
        },
    }
    media = MediaFileUpload(str(video), chunksize=8 * 1024 * 1024, resumable=True, mimetype="video/mp4")
    req = yt.videos().insert(part="snippet,status", body=corpo, media_body=media)
    resp = None
    while resp is None:
        status, resp = req.next_chunk()
        if status:
            log.info(f"YouTube: enviando {int(status.progress() * 100)}%")
    vid = resp["id"]
    log.info(f"YouTube publicado: https://youtu.be/{vid}  (status: {resp['status']['privacyStatus']})")

    if miniatura and miniatura.exists():
        try:
            yt.thumbnails().set(videoId=vid, media_body=MediaFileUpload(str(miniatura))).execute()
        except Exception as e:  # noqa: BLE001  (exige canal verificado por telefone)
            log.warning(f"Miniatura não enviada (verifique o canal por telefone): {e}")
    return vid
