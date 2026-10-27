"""
Rode no seu PC DEPOIS de autorizar YouTube e TikTok.
Mostra os valores para colar em GitHub → Settings → Secrets and variables → Actions.
"""
import json
import os

from util import RAIZ  # carrega o .env

segredos = {
    "ANTHROPIC_API_KEY": os.environ.get("ANTHROPIC_API_KEY", ""),
    "OPENAI_API_KEY": os.environ.get("OPENAI_API_KEY", ""),
    "TIKTOK_CLIENT_KEY": os.environ.get("TIKTOK_CLIENT_KEY", ""),
    "TIKTOK_CLIENT_SECRET": os.environ.get("TIKTOK_CLIENT_SECRET", ""),
}
yt = RAIZ / "token_youtube.json"
segredos["YOUTUBE_TOKEN_JSON"] = yt.read_text(encoding="utf-8").strip() if yt.exists() else ""
tk = RAIZ / "token_tiktok.json"
segredos["TIKTOK_REFRESH_TOKEN"] = json.loads(tk.read_text(encoding="utf-8"))["refresh_token"] if tk.exists() else ""

print("\nCrie cada segredo abaixo no GitHub (Nome = valor). NÃO mostre isto a ninguém.\n")
for nome, valor in segredos.items():
    print("=" * 70)
    print(nome)
    print(valor if valor else "⚠️  VAZIO — falta configurar este")
print("=" * 70)
