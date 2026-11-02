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


# ------------------------------------------------------------------ envio automático agendado (youtube_auto.py)
def conectado() -> bool:
    return bool(os.environ.get("YOUTUBE_REFRESH_TOKEN") or os.environ.get("YOUTUBE_TOKEN_JSON"))


def _yt():
    return build("youtube", "v3", credentials=credenciais(), cache_discovery=False)


def canal() -> dict:
    r = _yt().channels().list(part="snippet,statistics,contentDetails", mine=True).execute()
    if not r.get("items"):
        raise RuntimeError("a conta autorizada não tem canal do YouTube")
    c = r["items"][0]
    return {"id": c["id"], "titulo": c["snippet"]["title"], "inscritos": c["statistics"].get("subscriberCount"),
            "videos": c["statistics"].get("videoCount"),
            "uploads": c["contentDetails"]["relatedPlaylists"]["uploads"]}


def ja_enviado(titulo: str):
    """Controle de duplicidade: procura o mesmo título nos últimos envios do canal (custa 1 ponto de cota)."""
    try:
        yt = _yt()
        ups = canal()["uploads"]
        r = yt.playlistItems().list(part="snippet", playlistId=ups, maxResults=15).execute()
        for it in r.get("items", []):
            if it["snippet"]["title"].strip() == titulo[:100].strip():
                return it["snippet"]["resourceId"]["videoId"]
    except Exception as e:  # noqa: BLE001
        log.warning(f"Não consegui conferir envios anteriores: {e}")
    return None


def status(video_id: str) -> dict:
    r = _yt().videos().list(part="status", id=video_id).execute()
    return r["items"][0]["status"] if r.get("items") else {}


def publicar_agendado(cfg, video: Path, titulo: str, descricao: str, tags: list, miniatura: Path,
                      quando_utc, legenda_srt: Path = None):
    """Envia como privado com publishAt: o próprio YouTube publica no horário. Depois manda capa e legenda."""
    from googleapiclient.errors import HttpError
    yt = _yt()
    pub = cfg["publicacao"]
    corpo = {"snippet": {"title": titulo[:100], "description": descricao[:4900], "tags": tags,
                         "categoryId": pub.get("youtube_categoria", "27"), "defaultLanguage": "pt-BR",
                         "defaultAudioLanguage": "pt-BR"},
             "status": {"privacyStatus": "private", "publishAt": quando_utc.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                        "selfDeclaredMadeForKids": False}}
    media = MediaFileUpload(str(video), chunksize=16 * 1024 * 1024, resumable=True, mimetype="video/mp4")
    req = yt.videos().insert(part="snippet,status", body=corpo, media_body=media)
    resp = None
    while resp is None:
        st, resp = req.next_chunk()
        if st:
            log.info(f"YouTube: enviando {int(st.progress() * 100)}%")
    vid = resp["id"]
    info = {"privacidade": resp["status"].get("privacyStatus"), "agendado": resp["status"].get("publishAt")}
    log.info(f"YouTube: enviado https://youtu.be/{vid} {info}")
    if miniatura and Path(miniatura).exists():
        try:
            yt.thumbnails().set(videoId=vid, media_body=MediaFileUpload(str(miniatura))).execute()
            info["capa"] = "ok"
        except HttpError as e:
            info["capa"] = "falhou (verifique o canal por telefone em youtube.com/verify)"
            log.warning(f"Capa não enviada: {e}")
    if legenda_srt and Path(legenda_srt).exists():
        try:
            yt.captions().insert(part="snippet", body={"snippet": {"videoId": vid, "language": "pt-BR",
                                                                   "name": "Português", "isDraft": False}},
                                 media_body=MediaFileUpload(str(legenda_srt), mimetype="application/octet-stream")).execute()
            info["legenda"] = "ok"
        except HttpError as e:
            info["legenda"] = "falhou (a legenda já está gravada no vídeo)"
            log.warning(f"Legenda não enviada: {e}")
    return vid, info
