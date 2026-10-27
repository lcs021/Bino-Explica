"""Usado pelo GitHub (workflow "Conectar TikTok"): troca o código de autorização por um token
e guarda criptografado em tokens/tiktok.enc. Você não precisa rodar nada no computador."""
import os
import sys
import urllib.parse

import tiktok_upload as tk

entrada = os.environ.get("CODIGO", "").strip()
if not entrada:
    sys.exit("Cole o endereço (ou o código) que apareceu depois de autorizar no TikTok.")
if "code=" in entrada:
    entrada = urllib.parse.parse_qs(urllib.parse.urlparse(entrada).query).get("code", [""])[0]
codigo = urllib.parse.unquote(entrada)
r = tk.requests.post(f"{tk.API}/oauth/token/", data={
    "client_key": os.environ["TIKTOK_CLIENT_KEY"], "client_secret": os.environ["TIKTOK_CLIENT_SECRET"],
    "code": codigo, "grant_type": "authorization_code", "redirect_uri": os.environ["TIKTOK_REDIRECT_URI"],
}, timeout=30).json()
if "refresh_token" not in r:
    sys.exit(f"O TikTok recusou o código (ele vale poucos minutos e só uma vez). Gere outro. Resposta: {r}")
tk.guardar_no_cofre(r)
print("✅ TikTok conectado! O Bino já pode postar no seu perfil.")
