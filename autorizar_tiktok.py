"""Rode UMA vez para conectar sua conta do TikTok."""
import os
import secrets
import urllib.parse
import webbrowser

from tiktok_upload import trocar_codigo
import util  # noqa: F401  (carrega o .env)

params = {
    "client_key": os.environ["TIKTOK_CLIENT_KEY"],
    "scope": "user.info.basic,video.publish",
    "response_type": "code",
    "redirect_uri": os.environ["TIKTOK_REDIRECT_URI"],
    "state": secrets.token_urlsafe(12),
}
url = "https://www.tiktok.com/v2/auth/authorize/?" + urllib.parse.urlencode(params)
print("\n1) Vai abrir o TikTok no navegador. Entre e clique em Autorizar.")
print("2) Depois você vai cair numa página (pode até dar erro, tudo bem).")
print("3) Copie o ENDEREÇO COMPLETO dessa página e cole aqui.\n")
webbrowser.open(url)
print(url, "\n")
volta = input("Cole o endereço aqui: ").strip()
q = urllib.parse.parse_qs(urllib.parse.urlparse(volta).query)
if q.get("state", [""])[0] != params["state"]:
    raise SystemExit("O endereço colado não corresponde a esta autorização. Tente de novo.")
trocar_codigo(q["code"][0])
print("✅ TikTok autorizado! O token foi salvo em token_tiktok.json")
print("Para a nuvem, rode agora: python preparar_nuvem.py")
