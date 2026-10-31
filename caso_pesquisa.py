"""
Caso Ao Vivo — pesquisa documental e imagens de arquivo.

1. Encontra o artigo do caso na Wikipédia (português e inglês) e lista as referências que ele cita,
   separando fontes primárias (tribunais, órgãos oficiais) de reportagens de veículos reconhecidos.
2. Confere datas, números e nomes do roteiro contra o texto desses artigos.
3. Busca imagens no Wikimedia Commons só com licença que permite reuso (domínio público, CC0, CC BY, CC BY-SA),
   guarda autor, licença e link, e descarta fotos de pessoas (categorias + detector de rostos).

Nada é inventado: o que não for encontrado fica marcado como "não verificado" no pacote de produção.
"""
import html
import re
import time
import unicodedata
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

import requests

UA = {"User-Agent": "CasoAoVivo/1.0 (https://github.com/lcs021/Bino-Explica; robo de pesquisa documental)"}
COMMONS = "https://commons.wikimedia.org/w/api.php"

PRIMARIAS = (".jus.br", ".gov.br", ".mp.br", ".leg.br", ".def.br", ".mil.br", ".gov", ".gov.uk", ".gouv.fr", ".gob.",
             "europa.eu", "un.org", "interpol.int", "fbi.gov", "justice.gov", "supremecourt", "courts.", "court.",
             "archives.", "arquivonacional", "bnf.fr", "loc.gov", "nationalarchives")
VEICULOS = ("g1.globo.com", "oglobo.globo.com", "globo.com", "folha.uol.com.br", "estadao.com.br", "uol.com.br",
            "veja.abril.com.br", "abril.com.br", "cnnbrasil.com.br", "agenciabrasil.ebc.com.br", "ebc.com.br",
            "bbc.com", "bbc.co.uk", "nytimes.com", "theguardian.com", "reuters.com", "apnews.com", "washingtonpost.com",
            "lemonde.fr", "elpais.com", "time.com", "theatlantic.com", "smithsonianmag.com", "nationalgeographic.com",
            "cnn.com", "nbcnews.com", "cbsnews.com", "latimes.com", "telegraph.co.uk", "independent.co.uk",
            "lefigaro.fr", "corriere.it", "repubblica.it", "dw.com", "francetvinfo.fr", "terra.com.br", "r7.com",
            "correiobraziliense.com.br", "gazetadopovo.com.br", "jornaldocomercio", "opovo.com.br", "diariodonordeste")
IGNORAR = ("catalogue.bnf.fr", "data.bnf.fr", "isni.org", "d-nb.info", "viaf.org", "orcid.org", "wikipedia.org", "wikimedia.org", "wikidata.org", "wiktionary.org", "google.com/search", "worldcat.org",
           "doi.org/10.", "jstor.org/action", "archive.org/details", "openlibrary.org", "viaf.org", "id.loc.gov")
LICENCAS_OK = re.compile(r"^(public domain|pd\b|pd-|cc0|cc[ -]?by(-sa)?([ -]\d(\.\d)?)?$|cc[ -]?by(-sa)?[ -]\d\.\d)", re.I)
PALAVRAS_PESSOAS = ("portrait", "retrato", "people", "person", "persons", "men ", "women", "woman", " man", "boy", "girl",
                    "child", "children", "criança", "mugshot", "victim", "vítima", "face", "selfie", "politician",
                    "criminal", "actor", "actress", "singer", "crowd", "family", "família", "funeral", "corpse", "body",
                    "dead ", "cadáver", "self-portrait", "headshot", "bust of", "photograph of")
PALAVRAS_FORA = ("flag of", "bandeira", "coat of arms", "brasão", "logo", "icon", "ícone", "signature", "assinatura",
                 "symbol", "emblem", "seal of", "button", "question_book", "edit-clear", "ambox")


def _get(url, params, tentativas=3):
    params = dict(params, format="json", formatversion=2)
    for k in range(tentativas):
        try:
            r = requests.get(url, params=params, headers=UA, timeout=25)
            if r.status_code == 200:
                return r.json()
        except (requests.RequestException, ValueError):
            pass
        time.sleep(1.5 * (k + 1))
    return {}


def _sem_acento(t):
    return "".join(c for c in unicodedata.normalize("NFKD", str(t)) if not unicodedata.combining(c)).lower()


def _texto_html(t):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", str(t or "")))).strip()


# ---------------------------------------------------------------------------
# Wikipédia
# ---------------------------------------------------------------------------
def artigo(titulo, lang, busca_extra=""):
    """Devolve {lang, titulo, url, texto, resumo, links, imagens} ou None."""
    api = f"https://{lang}.wikipedia.org/w/api.php"
    candidatos = [titulo] if titulo else []
    if busca_extra:
        res = _get(api, {"action": "query", "list": "search", "srsearch": busca_extra, "srlimit": 3})
        candidatos += [s["title"] for s in res.get("query", {}).get("search", [])]
    for t in candidatos:
        res = _get(api, {"action": "query", "titles": t, "redirects": 1, "prop": "extracts|info",
                         "explaintext": 1, "inprop": "url"})
        paginas = res.get("query", {}).get("pages", [])
        if not paginas or paginas[0].get("missing") or not paginas[0].get("extract"):
            continue
        p = paginas[0]
        if "may refer to" in p["extract"][:300] or "pode referir-se" in p["extract"][:300]:
            continue                                   # página de desambiguação
        parse = _get(api, {"action": "parse", "page": p["title"], "prop": "externallinks|images", "redirects": 1})
        pr = parse.get("parse", {})
        return {"lang": lang, "titulo": p["title"], "url": p.get("fullurl", f"https://{lang}.wikipedia.org/wiki/{p['title']}"),
                "texto": p["extract"], "resumo": p["extract"].split("\n")[0][:1200],
                "links": pr.get("externallinks", []), "imagens": pr.get("images", [])}
    return None


def classificar(url):
    dom = urlparse(url).netloc.lower().removeprefix("www.")
    if not dom or any(x in url for x in IGNORAR):
        return None
    if "web.archive.org" in dom:
        orig = re.sub(r"^https?://web\.archive\.org/web/\d+[a-z_]*/", "", url)
        c = classificar(orig) if orig != url else None
        return (c[0], c[1] + " (cópia arquivada)", url) if c else None
    if any(p in dom or dom.endswith(p.strip(".")) for p in PRIMARIAS):
        return dom, "Fonte primária / oficial", url
    if any(v in dom for v in VEICULOS):
        return dom, "Reportagem de veículo reconhecido", url
    return dom, "Outra fonte (avaliar)", url


def fontes(artigos):
    vistos, out = set(), []
    ordem = {"Fonte primária / oficial": 0, "Reportagem de veículo reconhecido": 1}
    for a in artigos:
        for u in a.get("links", []):
            c = classificar(u)
            if not c or u in vistos:
                continue
            vistos.add(u)
            out.append({"dominio": c[0], "tipo": c[1], "url": c[2], "via": a["url"]})
    out.sort(key=lambda f: (ordem.get(f["tipo"].replace(" (cópia arquivada)", ""), 2), f["dominio"]))
    return out[:40]


# ---------------------------------------------------------------------------
# checagem de fatos
# ---------------------------------------------------------------------------
def _numeros(t):
    out = set()
    for m in re.finditer(r"\d[\d.,]*", t):
        n = m.group().strip(".,")
        if not n:
            continue
        out.add(n)
        out.add(n.replace(".", "").replace(",", "."))
        out.add(n.replace(",", "."))
    return {n for n in out if n}


MESES = {"janeiro": "january", "fevereiro": "february", "março": "march", "abril": "april", "maio": "may",
         "junho": "june", "julho": "july", "agosto": "august", "setembro": "september", "outubro": "october",
         "novembro": "november", "dezembro": "december"}


TRADUCOES = {"florenca": ("florence",), "italia": ("italy",), "franca": ("france",), "londres": ("london",),
             "alemanha": ("germany",), "espanha": ("spain",), "brasil": ("brazil",), "inglaterra": ("england",),
             "estados": ("united states",), "nova": ("new",), "roma": ("rome",), "lisboa": ("lisbon",), "veneza": ("venice",),
             "milao": ("milan",), "pequim": ("beijing",), "moscou": ("moscow",), "genebra": ("geneva",), "suica": ("switzerland",),
             "holanda": ("netherlands",), "belgica": ("belgium",), "mexico": ("mexico",), "japao": ("japan",), "china": ("china",)}


def _nomes(t):
    ignorar = {"segundo", "imprensa", "polícia", "policia", "justiça", "caso", "isso", "mas", "naquela", "hoje", "depois",
               "quando", "como", "para", "pois", "porque", "então", "agora", "aqui", "esse", "essa", "este", "esta",
               "você", "voce", "nossa", "olha", "presta", "calma", "imagina", "naquele", "dois", "três", "quatro", "cinco"}
    return {w for w in re.findall(r"\b[A-ZÁÉÍÓÚÂÊÔÃÕÇ][a-záéíóúâêôãõç]{3,}\b", t) if _sem_acento(w) not in ignorar}


def checar(item, base):
    """
    Confere datas, números e nomes do item contra o texto de referência.
    Só marca "Confirmado" quando a frase tem data ou número e tudo aparece junto num mesmo trecho da referência.
    Frase só com nomes vira no máximo "Parcial": o nome existe, mas o que a frase diz sobre ele precisa de conferência.
    """
    b = _sem_acento(base)
    nums = sorted({re.sub(r"\D", "", n) for n in _numeros(item) if len(re.sub(r"\D", "", n)) >= 2}, key=len, reverse=True)
    nomes = sorted({_sem_acento(w) for w in _nomes(item)})
    meses = [m for m in MESES if m in _sem_acento(item)]
    if not (nums or nomes or meses):
        return {"item": item, "status": "Sem dado conferível", "trecho": ""}
    b_dig = re.sub(r"(?<=\d)[.,](?=\d)", "", b)            # 1.200 / 164,7 -> comparáveis
    alvos = [(n, "n") for n in nums] + [(m, "m") for m in meses] + [(w, "w") for w in nomes]

    def achados(janela):
        ok = []
        for t, k in alvos:
            if k == "n":
                ok.append(bool(re.search(rf"(?<!\d){t}(?!\d)", janela)))
            elif k == "m":
                ok.append(t in janela or MESES[t] in janela)
            else:
                ok.append(t in janela or any(x in janela for x in TRADUCOES.get(t, ())))
        return ok

    ancora = nums[0] if nums else (meses[0] if meses else nomes[0])
    melhor, melhor_ok, pos = -1, [], -1
    for m in re.finditer(re.escape(ancora), b_dig):
        janela = b_dig[max(0, m.start() - 260): m.end() + 260]
        ok = achados(janela)
        if sum(ok) > melhor:
            melhor, melhor_ok, pos = sum(ok), ok, m.start()
    if pos < 0:
        geral = achados(b_dig)
        status = "Parcial: confira o detalhe" if any(geral) else "Não verificado"
        return {"item": item, "status": status, "trecho": ""}
    trecho = re.sub(r"\s+", " ", base[max(0, pos - 200): pos + 220]).strip()
    tem_dado = bool(nums or meses)
    if tem_dado and all(melhor_ok):
        status = "Confirmado na referência"
    elif any(melhor_ok):
        status = "Parcial: confira o detalhe"
    else:
        status = "Não verificado"
    return {"item": item, "status": status, "trecho": trecho}


# ---------------------------------------------------------------------------
# imagens (Wikimedia Commons)
# ---------------------------------------------------------------------------
def _info_arquivos(titulos):
    if not titulos:
        return []
    res = _get(COMMONS, {"action": "query", "titles": "|".join(titulos[:40]), "prop": "imageinfo|categories",
                         "iiprop": "url|size|mime|extmetadata", "iiurlwidth": 1600, "clshow": "!hidden", "cllimit": "max"})
    return res.get("query", {}).get("pages", [])


MOTIVOS = {}


def _nao(motivo):
    MOTIVOS[motivo] = MOTIVOS.get(motivo, 0) + 1
    return None


def _aceitavel(p):
    """Devolve os dados da imagem se ela puder ser usada; senão None (o motivo vai para MOTIVOS)."""
    ii = (p.get("imageinfo") or [{}])[0]
    meta = ii.get("extmetadata", {})
    v = lambda k: _texto_html(meta.get(k, {}).get("value", ""))
    titulo = p.get("title", "")
    lic = v("LicenseShortName")
    texto = _sem_acento(" ".join([titulo, v("ImageDescription"), v("ObjectName")] + [c.get("title", "") for c in p.get("categories", [])]))
    if p.get("missing") or not ii:
        return _nao("não está no Commons")
    if ii.get("mime") not in ("image/jpeg", "image/png", "image/tiff", "image/webp"):
        return _nao("formato")
    if min(ii.get("width", 0), ii.get("height", 0)) < 500:
        return _nao("pequena")
    if not lic or not LICENCAS_OK.search(lic.strip()) or "nc" in _sem_acento(lic).split("-") or "nd" in _sem_acento(lic):
        return _nao(f"licença ({lic or 'sem'})")
    if any(k in f" {texto} " for k in PALAVRAS_PESSOAS):
        return _nao("pessoas (descrição)")
    if any(k in texto for k in PALAVRAS_FORA):
        return _nao("ícone/logo/bandeira")
    return {"titulo": titulo.removeprefix("File:").removeprefix("Arquivo:"), "pagina": ii.get("descriptionurl", ""),
            "url": ii.get("thumburl") or ii.get("url"), "largura": ii.get("width"), "altura": ii.get("height"),
            "licenca": lic, "licenca_url": v("LicenseUrl"), "autor": v("Artist")[:120] or "Autor desconhecido",
            "credito": v("Credit")[:160], "data": v("DateTimeOriginal")[:40], "descricao": v("ImageDescription")[:300],
            "fonte": "Wikimedia Commons"}


_rostos = None


def _tem_rosto(arquivo):
    global _rostos
    try:
        import cv2
    except ImportError:
        return False
    if _rostos is None:
        _rostos = [cv2.CascadeClassifier(cv2.data.haarcascades + n)
                   for n in ("haarcascade_frontalface_default.xml", "haarcascade_profileface.xml")]
    img = cv2.imread(str(arquivo), cv2.IMREAD_GRAYSCALE)
    if img is None:
        return True
    esc = 900 / max(img.shape)
    if esc < 1:
        img = cv2.resize(img, None, fx=esc, fy=esc)
    lado = max(40, int(min(img.shape) * 0.09))
    for c in _rostos:
        if len(c.detectMultiScale(img, scaleFactor=1.1, minNeighbors=8, minSize=(lado, lado))):
            return True
    return False


def buscar_imagens(termo, limite=8):
    res = _get(COMMONS, {"action": "query", "list": "search", "srsearch": f"{termo} filetype:bitmap",
                         "srnamespace": 6, "srlimit": 15})
    titulos = [s["title"] for s in res.get("query", {}).get("search", [])]
    out = [x for x in (_aceitavel(p) for p in _info_arquivos(titulos)) if x]
    out.sort(key=lambda x: -(x["largura"] or 0))
    return out[:limite]


def baixar(img, pasta, nome):
    destino = pasta / f"{nome}.jpg"
    try:
        r = requests.get(img["url"], headers=UA, timeout=40)
        if r.status_code != 200 or len(r.content) < 5000:
            return _nao(f"download ({r.status_code})")
        destino.write_bytes(r.content)
        from PIL import Image
        with Image.open(destino) as im:
            im.convert("RGB").save(destino, quality=92)
        if _tem_rosto(destino):
            destino.unlink(missing_ok=True)
            return _nao("rosto detectado")
        return destino
    except Exception as e:  # noqa: BLE001
        destino.unlink(missing_ok=True)
        return _nao(f"erro ({type(e).__name__})")


# ---------------------------------------------------------------------------
# pesquisa completa
# ---------------------------------------------------------------------------
def pesquisar(caso, pasta, log=print):
    pasta = Path(pasta)
    imgs_dir = pasta / "imagens"
    imgs_dir.mkdir(parents=True, exist_ok=True)
    titulo = caso.get("titulo_caso", "")
    wk = caso.get("wikipedia") if isinstance(caso.get("wikipedia"), dict) else {}
    artigos, limitacoes = [], []
    for lang in ("pt", "en"):
        a = artigo(str(wk.get(lang, "")).strip(), lang, busca_extra=titulo if lang == "pt" or not wk.get(lang) else "")
        if a:
            artigos.append(a)
            log(f"Pesquisa: artigo encontrado ({lang}): {a['titulo']}")
    if not artigos:
        limitacoes.append("Nenhum artigo da Wikipédia foi encontrado para o caso: os fatos não puderam ser conferidos automaticamente.")
    base = "\n".join(a["texto"] for a in artigos)
    lista_fontes = fontes(artigos)
    if artigos and not any(f["tipo"].startswith(("Fonte primária", "Reportagem")) for f in lista_fontes):
        limitacoes.append("As referências encontradas não incluem fontes oficiais nem veículos reconhecidos: reforce a apuração antes de postar.")

    # checagem: itens do roteiro com data, número ou nome próprio
    itens = [x.get("fato", "") for x in caso.get("conferir", []) if x.get("fato")]
    for c in caso["cenas"]:
        for frase in re.split(r"(?<=[.!?])\s+", c["fala"]):
            if re.search(r"\d", frase) or len(_nomes(frase)) >= 1:
                itens.append(frase.strip())
    vistos, checagem = set(), []
    for it in itens:
        k = _sem_acento(it)
        if k in vistos or len(it) < 6:
            continue
        vistos.add(k)
        checagem.append(checar(it, base) if base else {"item": it, "status": "Não verificado", "trecho": ""})

    # imagens: busca de cada cena primeiro, depois as do próprio artigo
    por_cena, usados = {}, set()
    termos_artigo = []
    for a in artigos:
        termos_artigo += [f"File:{n}" for n in a.get("imagens", [])[:25]]
    pool_artigo = [x for x in (_aceitavel(p) for p in _info_arquivos(termos_artigo)) if x]
    MOTIVOS.clear()
    for i, c in enumerate(caso["cenas"]):
        termo = str(c.get("busca_imagem", "")).strip()
        cand = buscar_imagens(termo) if termo else []
        log(f"Imagens da cena {i + 1} ('{termo}'): {len(cand)} candidatas aceitas pela licença e descrição")
        for img in cand + pool_artigo:
            if img["pagina"] in usados:
                continue
            arq = baixar(img, imgs_dir, f"cena_{i + 1:02d}")
            usados.add(img["pagina"])
            if arq:
                img["arquivo"] = arq
                img["busca"] = termo or "imagem do artigo"
                por_cena[i] = img
                log(f"Imagem da cena {i + 1}: {img['titulo']} ({img['licenca']})")
                break
            time.sleep(0.2)
    if MOTIVOS:
        log("Imagens descartadas: " + ", ".join(f"{k}: {v}" for k, v in sorted(MOTIVOS.items(), key=lambda x: -x[1])))
    if not por_cena:
        limitacoes.append("Nenhuma imagem de arquivo com licença livre e sem pessoas foi encontrada: o vídeo usa só artes ilustrativas.")
    return {"data": date.today().isoformat(), "artigos": [{k: a[k] for k in ("lang", "titulo", "url", "resumo")} for a in artigos],
            "fontes": lista_fontes, "checagem": checagem, "imagens": por_cena, "limitacoes": limitacoes}
