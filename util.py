"""Funções auxiliares: configuração, log, histórico, ffprobe."""
import json
import logging
import os
import re
import subprocess
import unicodedata
from pathlib import Path

import yaml
from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent
load_dotenv(RAIZ / ".env")


def carregar_config() -> dict:
    with open(RAIZ / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def configurar_log() -> logging.Logger:
    (RAIZ / "logs").mkdir(exist_ok=True)
    log = logging.getLogger("turibencao")
    if not log.handlers:
        log.setLevel(logging.INFO)
        fmt = logging.Formatter("%(asctime)s  %(levelname)s  %(message)s", "%d/%m %H:%M:%S")
        fh = logging.FileHandler(RAIZ / "logs" / "turibencao.log", encoding="utf-8")
        fh.setFormatter(fmt)
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        log.addHandler(fh)
        log.addHandler(sh)
    return log


def slug(texto: str, limite: int = 50) -> str:
    t = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    t = re.sub(r"[^a-zA-Z0-9]+", "-", t).strip("-").lower()
    return t[:limite] or "video"


def ler_historico(cfg) -> list:
    p = RAIZ / cfg["pastas"]["historico"]
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return []


def salvar_historico(cfg, historico: list):
    p = RAIZ / cfg["pastas"]["historico"]
    p.write_text(json.dumps(historico, ensure_ascii=False, indent=2), encoding="utf-8")


def ler_temas(cfg) -> list:
    p = RAIZ / cfg["pastas"]["temas"]
    if not p.exists():
        return []
    linhas = p.read_text(encoding="utf-8").splitlines()
    return [l.strip() for l in linhas if l.strip() and not l.strip().startswith("#")]


def duracao(arquivo) -> float:
    saida = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(arquivo)],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    return float(saida)


def rodar_ffmpeg(args: list, cwd=None):
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"] + [str(a) for a in args]
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg falhou:\n{' '.join(cmd)}\n{r.stderr[-2000:]}")
