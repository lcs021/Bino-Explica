"""IA gratuita: Google Gemini (camada grátis, sem cartão de crédito).

Chave grátis em https://aistudio.google.com/apikey
Usa os apelidos "-latest" para sempre pegar o modelo gratuito mais novo.
"""
import json
import os
import re
import time

import requests

from util import configurar_log

log = configurar_log()
URL = "https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent"


def gerar(prompt: str, modelo: str, json_mode=False, temperatura=0.9) -> str:
    chave = os.environ.get("GEMINI_API_KEY")
    if not chave:
        raise RuntimeError("Falta a chave grátis do Gemini (segredo GEMINI_API_KEY).")
    corpo = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
             "generationConfig": {"temperature": temperatura}}
    if json_mode:
        corpo["generationConfig"]["responseMimeType"] = "application/json"
    for tentativa in range(5):
        r = requests.post(URL.format(m=modelo), json=corpo, timeout=240,
                          headers={"x-goog-api-key": chave, "Content-Type": "application/json"})
        if r.status_code in (429, 500, 503):
            espera = 30 * (tentativa + 1)
            log.warning(f"Gemini ocupado ({r.status_code}); tentando de novo em {espera}s")
            time.sleep(espera)
            continue
        if r.status_code != 200:
            raise RuntimeError(f"Gemini recusou ({r.status_code}): {r.text[:400]}")
        dados = r.json()
        partes = dados.get("candidates", [{}])[0].get("content", {}).get("parts", [])
        texto = "".join(p.get("text", "") for p in partes)
        if texto:
            return texto
        log.warning(f"Gemini respondeu vazio: {str(dados)[:300]}")
        time.sleep(10)
    raise RuntimeError("Gemini não respondeu depois de várias tentativas (limite grátis do dia?).")


def gerar_json(prompt: str, modelo: str) -> dict:
    texto = gerar(prompt, modelo, json_mode=True, temperatura=0.8)
    m = re.search(r"\{.*\}", texto, re.S)
    return json.loads(m.group(0) if m else texto)
