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
RESERVAS = ["gemini-flash-latest", "gemini-flash-lite-latest", "gemini-3.5-flash", "gemini-3.5-flash-lite"]


_DISPONIVEIS = None
_SEM_BUSCA = False


def disponiveis():
    """Modelos 'flash' grátis que existem HOJE na conta (o Google aposenta versões; o robô se adapta sozinho)."""
    global _DISPONIVEIS
    if _DISPONIVEIS is not None:
        return _DISPONIVEIS
    _DISPONIVEIS = []
    chave = os.environ.get("GEMINI_API_KEY")
    try:
        r = requests.get("https://generativelanguage.googleapis.com/v1beta/models", timeout=30,
                         params={"pageSize": 200}, headers={"x-goog-api-key": chave})
        nomes = [m["name"].split("/")[-1] for m in r.json().get("models", [])
                 if "generateContent" in m.get("supportedGenerationMethods", [])]
        flash = [n for n in nomes if "flash" in n and not re.search(r"image|tts|audio|live|embedding|exp|preview", n)]

        def versao(n):
            v = re.search(r"(\d+(?:\.\d+)?)", n)
            return (float(v.group(1)) if v else 0, "lite" not in n, "latest" in n)
        _DISPONIVEIS = sorted(flash, key=versao, reverse=True)
        log.info(f"Modelos Gemini disponíveis: {', '.join(_DISPONIVEIS[:6])}")
    except Exception as e:  # noqa: BLE001
        log.warning(f"Não consegui listar os modelos do Gemini ({e}).")
    return _DISPONIVEIS


def _ordem(modelo):
    base = [modelo] + disponiveis() + RESERVAS
    vistos, ordem = set(), []
    for m in base:
        if m and m not in vistos:
            vistos.add(m)
            ordem.append(m)
    return ordem[:6]


CHAMADAS = 0          # pedidos feitos nesta execução (controle de limites)


def _uma_chamada(modelo, corpo, chave):
    global CHAMADAS
    CHAMADAS += 1
    r = requests.post(URL.format(m=modelo), json=corpo, timeout=150,
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

    modelos = _ordem(modelo)
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
    """Pede JSON; se a resposta vier cortada ou quebrada, pede de novo (até 3 vezes)."""
    erro = None
    for tentativa in range(3):
        texto = gerar(prompt, modelo, json_mode=True, temperatura=0.8)
        m = re.search(r"\{.*\}", texto, re.S)
        try:
            return json.loads(m.group(0) if m else texto)
        except json.JSONDecodeError as e:
            erro = e
            log.warning(f"Resposta da IA com JSON quebrado ({e}); pedindo de novo.")
    raise RuntimeError(f"a IA devolveu JSON inválido 3 vezes ({erro})")


def pesquisar(prompt: str, modelo: str = "gemini-3.5-flash"):
    """Pergunta ao Gemini COM busca no Google. Devolve (texto, fontes) — fontes = [{"titulo", "url"}] reais,
    vindas da própria busca (nada inventado)."""
    chave = os.environ.get("GEMINI_API_KEY")
    if not chave:
        raise RuntimeError("Falta a chave grátis do Gemini (segredo GEMINI_API_KEY).")
    corpo = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
             "tools": [{"google_search": {}}], "generationConfig": {"temperature": 0.6}}
    global _SEM_BUSCA
    if _SEM_BUSCA:
        raise RuntimeError("busca do Google sem cota nesta execução")
    modelos = _ordem(modelo)
    ultimo, recusas = "", 0
    for volta in range(2):
        for m in modelos:
            try:
                r = _uma_chamada(m, corpo, chave)
            except requests.RequestException as e:
                log.warning(f"Falha de rede na pesquisa com {m}: {e}")
                time.sleep(10)
                continue
            if r.status_code != 200:
                ultimo = f"{r.status_code}: {r.text[:200]}"
                recusas += r.status_code == 429
                log.warning(f"Pesquisa com {m} indisponível ({r.status_code}); tentando outro.")
                time.sleep(8)
                continue
            cand = r.json().get("candidates", [{}])[0]
            texto = "".join(p.get("text", "") for p in cand.get("content", {}).get("parts", []))
            fontes, vistos = [], set()
            for ch in cand.get("groundingMetadata", {}).get("groundingChunks", []):
                web = ch.get("web") or {}
                tit = web.get("title") or ""
                if web.get("uri") and tit not in vistos:
                    vistos.add(tit)
                    fontes.append({"titulo": tit, "url": web["uri"]})
            if texto:
                return texto, fontes
        if recusas >= len(modelos):            # todos sem cota de busca: não insiste mais nesta execução
            _SEM_BUSCA = True
            break
        time.sleep(30)
    raise RuntimeError(f"A pesquisa no Google pelo Gemini não respondeu agora ({ultimo}).")


def extrair_json(texto: str):
    m = re.search(r"[\[{].*[\]}]", texto, re.S)
    return json.loads(m.group(0) if m else texto)


# ------------------------------------------------------------------ Wikipédia (fonte grátis de reserva)
def wikipedia(tema: str, idiomas=("pt", "en")):
    """Busca o artigo mais relevante e devolve (texto, fonte) — fonte real com link, ou (None, None)."""
    cab = {"User-Agent": "BinoExplicaBot/1.0 (https://github.com/lcs021/Bino-Explica)"}
    for lang in idiomas:
        try:
            api = f"https://{lang}.wikipedia.org/w/api.php"
            busca = requests.get(api, headers=cab, timeout=30, params={
                "action": "query", "list": "search", "srsearch": tema, "srlimit": 3, "format": "json"}).json()
            candidatos = [{"title": tema}] + busca.get("query", {}).get("search", [])   # título exato primeiro
            for res in candidatos:
                pag = requests.get(api, headers=cab, timeout=30, params={
                    "action": "query", "prop": "extracts|info", "inprop": "url", "explaintext": 1,
                    "titles": res["title"], "format": "json", "redirects": 1}).json()
                for p in pag.get("query", {}).get("pages", {}).values():
                    texto = (p.get("extract") or "")[:15000]
                    if len(texto) > 1200:
                        return texto, {"titulo": f"Wikipédia: {p['title']}", "url": p.get("fullurl", "")}
        except Exception as e:  # noqa: BLE001
            log.warning(f"Wikipédia ({lang}) indisponível: {e}")
    return None, None
