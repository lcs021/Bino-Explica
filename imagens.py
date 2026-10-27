"""Gera as ilustrações das cenas e a miniatura com IA (OpenAI)."""
import base64
import time
from pathlib import Path

from openai import OpenAI
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from util import configurar_log

log = configurar_log()


def _prompt_completo(cfg, cena: str) -> str:
    return (f"{cena}. Recurring character: {cfg['personagens_fixos']} "
            f"Art style: {cfg['estilo_visual']}. Safe, gentle, joyful scene for young children.")


def gerar_imagem(cfg, prompt: str, destino: Path, tamanho=None) -> Path:
    if destino.exists():            # retomada: não paga duas vezes pela mesma imagem
        return destino
    cliente = OpenAI()
    ic = cfg["imagens"]
    for tentativa in range(3):
        try:
            r = cliente.images.generate(
                model=ic["modelo"],
                prompt=_prompt_completo(cfg, prompt),
                size=tamanho or ic["tamanho"],
                quality=ic["qualidade"],
                n=1,
            )
            destino.write_bytes(base64.b64decode(r.data[0].b64_json))
            return destino
        except Exception as e:  # noqa: BLE001
            log.warning(f"Falha ao gerar imagem ({tentativa + 1}/3): {e}")
            time.sleep(5 * (tentativa + 1))
    raise RuntimeError(f"Não consegui gerar a imagem: {destino.name}")


def gerar_cenas(cfg, roteiro: dict, pasta: Path) -> list:
    caminhos = []
    for i, cena in enumerate(roteiro["cenas"]):
        log.info(f"Imagem {i + 1}/{len(roteiro['cenas'])}")
        caminhos.append(gerar_imagem(cfg, cena["prompt_imagem"], pasta / f"cena_{i:02d}.png"))
    return caminhos


def _fonte(tamanho: int):
    for nome in ["arialbd.ttf", "Arial Bold.ttf", "C:/Windows/Fonts/arialbd.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]:
        try:
            return ImageFont.truetype(nome, tamanho)
        except OSError:
            continue
    return ImageFont.load_default()


def gerar_miniatura(cfg, roteiro: dict, pasta: Path) -> Path:
    base = gerar_imagem(cfg, roteiro.get("prompt_miniatura") or roteiro["cenas"][0]["prompt_imagem"],
                        pasta / "miniatura_base.png")
    img = Image.open(base).convert("RGB")
    img = recortar(img, 1280, 720)
    draw = ImageDraw.Draw(img)
    titulo = roteiro["titulo"].split("|")[0].split("-")[0].strip().upper()
    fonte = _fonte(84)
    # quebra em até 2 linhas
    palavras, linhas, atual = titulo.split(), [], ""
    for p in palavras:
        teste = (atual + " " + p).strip()
        if draw.textlength(teste, font=fonte) > 1180 and atual:
            linhas.append(atual)
            atual = p
        else:
            atual = teste
    linhas.append(atual)
    linhas = linhas[:2]
    y = 720 - 40 - len(linhas) * 100
    for linha in linhas:
        w = draw.textlength(linha, font=fonte)
        draw.text(((1280 - w) / 2, y), linha, font=fonte, fill="#FFFFFF",
                  stroke_width=8, stroke_fill="#5B2A86")
        y += 100
    destino = pasta / "miniatura.jpg"
    img.save(destino, quality=92)
    return destino


def recortar(img: Image.Image, w: int, h: int) -> Image.Image:
    """Redimensiona preenchendo w x h e corta o excesso pelo centro."""
    escala = max(w / img.width, h / img.height)
    img = img.resize((round(img.width * escala), round(img.height * escala)), Image.LANCZOS)
    x = (img.width - w) // 2
    y = (img.height - h) // 2
    return img.crop((x, y, x + w, y + h))


def versao_horizontal(origem: Path, destino: Path) -> Path:
    recortar(Image.open(origem).convert("RGB"), 1920, 1080).save(destino)
    return destino


def versao_vertical(origem: Path, destino: Path) -> Path:
    """9:16 com a ilustração inteira no centro e fundo desfocado (nada é cortado)."""
    img = Image.open(origem).convert("RGB")
    fundo = recortar(img, 1080, 1920).filter(ImageFilter.GaussianBlur(28))
    fundo = Image.blend(fundo, Image.new("RGB", fundo.size, (255, 248, 235)), 0.25)
    # ilustração um pouco maior que a largura da tela (corta só as bordas laterais)
    alt = round(img.height * 1300 / img.width)
    frente = recortar(img.resize((1300, alt), Image.LANCZOS), 1080, alt)
    fundo.paste(frente, (0, (1920 - alt) // 2 - 120))
    fundo.save(destino)
    return destino
