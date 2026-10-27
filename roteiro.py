"""Gera o roteiro (vídeo longo + corte curto) com o Claude e faz a revisão automática."""
import json
import re

import anthropic

from util import configurar_log

log = configurar_log()


def _cliente():
    return anthropic.Anthropic()


def _json_da_resposta(texto: str) -> dict:
    m = re.search(r"\{.*\}", texto, re.S)
    if not m:
        raise ValueError("Resposta do Claude sem JSON")
    return json.loads(m.group(0))


def _perguntar(cfg, sistema: str, pedido: str, max_tokens=8000) -> dict:
    resp = _cliente().messages.create(
        model=cfg["roteiro"]["modelo_claude"],
        max_tokens=max_tokens,
        system=sistema,
        messages=[{"role": "user", "content": pedido}],
    )
    texto = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
    return _json_da_resposta(texto)


def sugerir_tema(cfg, ja_feitos: list) -> str:
    sistema = "Você planeja conteúdo para um canal infantil cristão. Responda só em JSON."
    pedido = (
        f"Fundamentos do canal:\n{cfg['canal']['fundamentos']}\n\n"
        f"Temas já publicados: {json.dumps(ja_feitos, ensure_ascii=False)}\n\n"
        "Sugira UM novo tema de história bíblica ou valor cristão que ainda não foi feito, "
        "adequado para crianças pequenas. Formato: {\"tema\": \"...\"}"
    )
    return _perguntar(cfg, sistema, pedido, 500)["tema"]


def _sistema_roteirista(cfg) -> str:
    c = cfg["canal"]
    return f"""Você é roteirista do canal infantil "{c['nome']}" no YouTube.
Fundamentos obrigatórios de todos os vídeos:
{c['fundamentos']}
Público: {c['publico']}. Idioma: português do Brasil, frases curtas, vocabulário simples,
tom alegre e acolhedor. Seja fiel ao texto bíblico (cite o livro e capítulo na descrição),
sem cenas assustadoras ou violentas em detalhe — trate momentos difíceis com delicadeza.
Personagem guia fixo: {cfg['personagens_fixos']}
Responda SOMENTE com JSON válido, sem comentários."""


def gerar_roteiro(cfg, tema: str, observacoes: str = "") -> dict:
    r = cfg["roteiro"]
    palavras_longo = int(r["duracao_longo_seg"] * 2.2)   # ~2,2 palavras/seg narrando devagar
    palavras_curto = int(r["duracao_curto_seg"] * 2.2)
    pedido = f"""Tema: {tema}

Crie:
1) Um vídeo principal de cerca de {r['duracao_longo_seg']} segundos (~{palavras_longo} palavras no total),
   dividido em exatamente {r['cenas_longo']} cenas. Comece com o Turi cumprimentando as crianças,
   conte a história, termine com a lição/valor e um convite carinhoso para se inscrever no canal.
2) Um corte curto vertical de cerca de {r['duracao_curto_seg']} segundos (~{palavras_curto} palavras)
   com gancho forte no primeiro segundo, reaproveitando as imagens do vídeo principal.

Para cada cena do vídeo principal escreva "prompt_imagem" EM INGLÊS descrevendo só a cena
(personagens, ação, cenário, emoção) — o estilo visual é adicionado depois automaticamente.
Inclua o Turi nas cenas de abertura e fechamento.

Formato:
{{
  "titulo": "título do YouTube (máx 70 caracteres, atrativo para pais)",
  "descricao": "descrição com resumo, referência bíblica e chamada para inscrição",
  "tags": ["até 15 tags"],
  "referencia_biblica": "Livro capítulo",
  "cenas": [{{"narracao": "...", "prompt_imagem": "..."}}],
  "curto": {{
     "titulo": "título curto com 1-2 emojis",
     "legenda_tiktok": "texto curto + hashtags",
     "cenas": [{{"imagem": 0, "narracao": "..."}}]
  }},
  "prompt_miniatura": "cena em inglês para a miniatura, muito colorida e expressiva"
}}
No "curto", "imagem" é o índice (começando em 0) da cena do vídeo principal a reutilizar.
{('Corrija estes pontos apontados na revisão: ' + observacoes) if observacoes else ''}"""
    roteiro = _perguntar(cfg, _sistema_roteirista(cfg), pedido)
    _validar(roteiro, r["cenas_longo"])
    return roteiro


def _validar(rot: dict, n_cenas: int):
    assert rot.get("titulo") and rot.get("cenas"), "roteiro incompleto"
    n = len(rot["cenas"])
    for c in rot["curto"]["cenas"]:
        c["imagem"] = max(0, min(int(c.get("imagem", 0)), n - 1))
    rot["titulo"] = rot["titulo"][:100]
    rot["tags"] = [t for t in rot.get("tags", []) if t][:15]


def revisar_roteiro(cfg, rot: dict) -> dict:
    sistema = ("Você revisa conteúdo infantil cristão antes da publicação automática. "
               "Seja criterioso. Responda só em JSON.")
    pedido = f"""Revise este roteiro para o canal infantil "{cfg['canal']['nome']}".
Verifique: (1) fidelidade ao relato bíblico, sem inventar fatos importantes;
(2) adequado para {cfg['canal']['publico']} — nada assustador, violento, triste demais ou inadequado;
(3) português correto; (4) segue os fundamentos: {cfg['canal']['fundamentos']}
(5) título e descrição honestos (sem clickbait enganoso).

Roteiro:
{json.dumps(rot, ensure_ascii=False)}

Formato: {{"aprovado": true/false, "problemas": "lista dos problemas, vazio se aprovado"}}"""
    return _perguntar(cfg, sistema, pedido, 1500)


def criar_roteiro_aprovado(cfg, tema: str) -> dict:
    obs = ""
    for tentativa in range(1, cfg["roteiro"]["tentativas_maximas"] + 1):
        log.info(f"Escrevendo roteiro (tentativa {tentativa}): {tema}")
        rot = gerar_roteiro(cfg, tema, obs)
        if not cfg["roteiro"]["revisao_automatica"]:
            return rot
        rev = revisar_roteiro(cfg, rot)
        if rev.get("aprovado"):
            log.info("Roteiro aprovado na revisão automática.")
            return rot
        obs = rev.get("problemas", "")
        log.warning(f"Revisão reprovou: {obs}")
    raise RuntimeError(f"Roteiro reprovado na revisão após {tentativa} tentativas. Nada foi publicado.")
