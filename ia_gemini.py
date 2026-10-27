"""IA gratuita: Google Gemini (camada grátis, sem cartão de crédito).

Chave grátis em https://aistudio.google.com/apikey
Se um modelo estiver lotado (503) ou sem cota (429), troca sozinho para outro modelo grátis.
"""
import json
import os
import re
import time

import requests

from util import configurar_log

log = configurar_log()
URL = "https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent"
RESERVAS = ["gemini-flash-latest", "gemini-flash-lite-latest", "gemini-2.5-flash", "gemini-2.5-flash-lite"]


def _uma_chamada(modelo, corpo, chave):
    r = requests.post(URL.format(m=modelo), json=corpo, timeout=240,
                      headers={"x-goog-api-key": chave, "Content-Type": "application/json"})
    return r


def gerar(prompt: str, modelo: str, json_mode=False, temperatura=0.9) -> str:
    chave = os.environ.get("GEMINI_API_KEY")
    if not chave:
        raise RuntimeError("Falta a chave grátis do Gemini (segredo GEMINI_API_KEY).")
    corpo = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
             "generationConfig": {"temperature": temperatura}}
    if json_mode:
        corpo["generationConfig"]["responseMimeType"] = "application/json"

    modelos = [modelo] + [m for m in RESERVAS if m != modelo]
    for volta in range(3):                        # até 3 voltas por todos os modelos
        for m in modelos:
            for tentativa in range(2):
                try:
                    r = _uma_chamada(m, corpo, chave)
                except requests.RequestException as e:
                    log.warning(f"Falha de rede com {m}: {e}")
                    time.sleep(10)
                    continue
                if r.status_code == 200:
                    dados = r.json()
                    partes = dados.get("candidates", [{}])[0].get("content", {}).get("parts", [])
                    texto = "".join(p.get("text", "") for p in partes)
                    if texto:
                        if m != modelo:
                            log.info(f"Respondido pelo modelo reserva {m}.")
                        return texto
                    log.warning(f"{m} respondeu vazio; tentando outro.")
                    break
                if r.status_code in (500, 503):           # lotado: espera um pouco e tenta de novo
                    log.warning(f"{m} lotado ({r.status_code}); tentando de novo em {15 * (tentativa + 1)}s")
                    time.sleep(15 * (tentativa + 1))
                    continue
                if r.status_code in (429, 404, 400):      # sem cota hoje / modelo indisponível: troca
                    log.warning(f"{m} indisponível ({r.status_code}); trocando de modelo.")
                    break
                raise RuntimeError(f"Gemini recusou ({r.status_code}): {r.text[:400]}")
        log.warning("Todos os modelos grátis ocupados; esperando 60s para outra volta.")
        time.sleep(60)
    raise RuntimeError("Os servidores grátis do Gemini estão lotados agora. Rode de novo mais tarde.")


def gerar_json(prompt: str, modelo: str) -> dict:
    texto = gerar(prompt, modelo, json_mode=True, temperatura=0.8)
    m = re.search(r"\{.*\}", texto, re.S)
    return json.loads(m.group(0) if m else texto)
