"""Rode UMA vez: abre o navegador para você autorizar o envio ao seu canal."""
from youtube_upload import SEGREDO, credenciais

if not SEGREDO.exists():
    raise SystemExit("Coloque o arquivo client_secret.json (Google Cloud) nesta pasta primeiro.")
credenciais(interativo=True)
print("✅ YouTube autorizado! O token foi salvo em token_youtube.json")
