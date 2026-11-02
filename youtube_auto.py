"""
YouTube automático do Bino Explica: 1 vídeo de ~10 minutos por dia, agendado para as 19:30 (Brasília).

    python youtube_auto.py produzir [--tema "..."] [--quando "02/11 19:30"]   # pesquisa → roteiro em capítulos →
                                                                               # 16 desenhos → voz → edição 16:9 →
                                                                               # capa → QA → envio agendado
    python youtube_auto.py conferir     # confirma no YouTube o que já foi ao ar
    python youtube_auto.py auditoria    # confere a conexão com o canal

Usa as mesmas peças dos Reels (pesquisa na Wikipédia, revisão de fatos, desenho, voz neural, animação traço a traço,
legendas palavra a palavra, trilha própria). Registro em youtube/registro.json (id único, sem duplicar).
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import ia_gemini as ia
import operacao as op
from util import RAIZ, carregar_config, configurar_log, duracao, slug

log = configurar_log()
PASTA = RAIZ / "youtube"
REGISTRO = PASTA / "registro.json"
HORARIO = "19:30"
BLOCOS = 16                      # 16 ilustrações, cada uma com 2 falas = 32 falas (~10 min)
MARCA = "Bino Explica"


def agora():
    return op.agora()


def ler():
    try:
        return op.normalizar(json.loads(REGISTRO.read_text(encoding="utf-8")))
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def salvar(reg):
    PASTA.mkdir(exist_ok=True)
    REGISTRO.write_text(json.dumps(reg, ensure_ascii=False, indent=2), encoding="utf-8")


def atividade(texto, vid=None, erro=False):
    op.atividade("youtube", texto, vid, erro)


def horario_yt():
    return carregar_config().get("youtube_auto", {}).get("horario") or HORARIO


def proximo_horario(reg):
    """Próximo dia com 19:30 livre (a partir de agora + 2 h, para dar tempo de processar no YouTube)."""
    ocupados = {r["horario"] for r in reg if r["status"] in (op.AGUARDANDO, op.PUBLICANDO, op.PUBLICADO)}
    hh, mm = map(int, horario_yt().split(":"))
    dia = agora().date()
    while True:
        q = datetime(dia.year, dia.month, dia.day, hh, mm, tzinfo=op.FUSO)
        if q > agora() + timedelta(hours=2) and q.isoformat(timespec="minutes") not in ocupados:
            return q.isoformat(timespec="minutes")
        dia += timedelta(days=1)


# =================================================================== pauta
def escolher_tema(reg, modelo):
    feitos = [r["tema"] for r in reg][-150:] + op.temas_usados()[-150:]
    prompt = f"""Você é o pesquisador de pauta do canal de YouTube "Bino Explica" (vídeos de ~10 minutos, desenhados à mão,
curiosidades e histórias reais, público brasileiro geral). Sugira 8 temas com MUITO potencial de clique e de retenção
para um vídeo de 10 minutos: listas ("7 animais que...", "5 sobreviventes impossíveis..."), histórias reais
inacreditáveis contadas do começo ao fim, mistérios explicados, "como seria se...", ciência do dia a dia.
Fatos bem documentados (que existam artigos completos na Wikipédia). Nada de pessoas vivas, tragédias recentes,
política, saúde arriscada ou boatos. Não repita: {json.dumps(feitos, ensure_ascii=False)}.
Dê nota 0 a 10 para: curiosidade, retencao (rende 10 min sem enrolar), clique (título e capa chamativos),
interesse_brasil, ilustravel, credibilidade.
Responda SÓ JSON: {{"temas":[{{"tema":"...","categoria":"...","criterios":{{"curiosidade":0,"retencao":0,"clique":0,
"interesse_brasil":0,"ilustravel":0,"credibilidade":0}},"artigos":["2 a 4 títulos EXATOS de artigos da Wikipédia em
português que cobrem o tema"]}}]}}"""
    opcoes = ia.gerar_json(prompt, modelo).get("temas", [])
    for o in opcoes:
        c = o.get("criterios") or {}
        o["pontuacao"] = round(sum(min(10, max(0, float(c.get(k, 5) or 0))) for k in
                                   ("curiosidade", "retencao", "clique", "interesse_brasil", "ilustravel", "credibilidade")) / 60 * 100, 1)
    opcoes = sorted([o for o in opcoes if o.get("tema") and o["tema"] not in feitos], key=lambda o: -o["pontuacao"])
    op.registrar_temas(opcoes, opcoes[:3])
    log.info("Pauta YouTube: " + " | ".join(f"{o['pontuacao']:.0f} {o['tema'][:50]}" for o in opcoes[:4]))
    return opcoes[:3]


def pesquisar(tema, artigos, modelo):
    textos, fontes = [], []
    for termo in (artigos or [])[:4] or [tema]:
        artigo, fonte = ia.wikipedia(str(termo))
        if artigo and fonte["url"] not in [f["url"] for f in fontes]:
            textos.append(f"=== {fonte['titulo']} ===\n{artigo}")
            fontes.append(fonte)
    if not textos:
        raise RuntimeError("não achei fontes confiáveis para este tema")
    dados = ia.gerar_json(f"""Leia os artigos abaixo e extraia de 20 a 32 fatos curtos, precisos e interessantes para um vídeo de
10 minutos sobre: {tema}. Use SOMENTE o que está escrito (números, datas e nomes exatos). Diga se os artigos
comprovam a ideia principal do tema.
{chr(10).join(textos)[:45000]}
Responda SÓ JSON: {{"fatos":["..."],"comprova_o_tema":true|false}}""", modelo)
    if dados.get("comprova_o_tema") is False or len(dados.get("fatos") or []) < 12:
        raise RuntimeError("as fontes não sustentam um vídeo de 10 minutos sobre o tema")
    log.info(f"Pesquisa: {len(dados['fatos'])} fatos de {len(fontes)} fonte(s)")
    return dados["fatos"], fontes


# =================================================================== roteiro em capítulos
def prompt_roteiro(tema, fatos, obs=""):
    import main_gratis as mg
    pps = 2.6
    try:
        pps = json.loads((RAIZ / "reels" / "voz.json").read_text(encoding="utf-8"))["pps"]
    except Exception:  # noqa: BLE001
        pass
    pmin, pmax = round(500 * pps), round(570 * pps)
    regras = mg.REGRAS_VIRAL.replace("@binoexplica", "Bino Explica")
    return f"""{regras}

Formato: vídeo de YouTube HORIZONTAL de cerca de 10 minutos. A voz fala {pps:.1f} palavras por segundo:
escreva de {pmin} a {pmax} palavras no total.
Use SOMENTE estes fatos pesquisados (nenhum fato, número ou data a mais):
{json.dumps(fatos, ensure_ascii=False)}
Estrutura: 5 capítulos. Capítulo 1 = GANCHO forte nos primeiros 15 segundos (prometa o que vem e por que ficar até o
fim) + contexto. Capítulos 2 a 4 = desenvolvimento, cada um terminando com um mini-gancho para o próximo
("mas isso não é nada perto do que vem a seguir..."). Capítulo 5 = a revelação mais impressionante + conclusão +
pergunta para os comentários + "se inscreve no Bino Explica e ativa o sininho".
São EXATAMENTE {BLOCOS} blocos no total (distribua entre os capítulos). Cada bloco = UMA ilustração + DUAS falas
seguidas (cada fala com 35 a 50 palavras, linguagem falada, frases curtas). Sem enrolação e sem repetir informação.
{"Corrija estes problemas apontados pela revisão: " + obs if obs else ""}
"visual" do bloco: a ilustração EM INGLÊS que explica as duas falas (rabisco de quadro branco, bonequinhos de palito,
uma ação clara). "destaques": 1 a 3 palavras EXATAS das falas (números, nomes).
Responda SÓ JSON:
{{"titulo":"até 70 caracteres, chamativo e honesto","texto_capa":"2 a 4 palavras em MAIÚSCULAS para a capa",
"selo":"1 palavra curta (ex.: TOP 7, REAL, MISTÉRIO)","frase_capa":"até 5 palavras",
"descricao":"2 parágrafos que despertam curiosidade, sem spoiler do final","tags":["10 a 15 tags"],
"personagens":"aparência fixa dos personagens, em inglês",
"capitulos":[{{"titulo":"título curto do capítulo","blocos":[{{"visual":"...","falas":["...","..."],"destaques":["..."]}}]}}]}}"""


def revisar(r, fatos, modelo):
    texto = json.dumps({"titulo": r["titulo"], "capitulos": [{"titulo": c["titulo"], "falas": [f for b in c["blocos"] for f in b["falas"]]}
                                                             for c in r["capitulos"]]}, ensure_ascii=False)
    return ia.gerar_json(f"""Revisor final de um vídeo de YouTube de 10 minutos. Fatos pesquisados:
{json.dumps(fatos, ensure_ascii=False)}
Roteiro: {texto}
Reprove se: algum fato/número/data não está nos fatos ou foi distorcido; erro de português; título enganoso; gancho fraco
nos primeiros 15 segundos; repetição/enrolação; falta pergunta final; conteúdo impróprio, pessoa viva, política ou saúde.
Responda SÓ JSON: {{"aprovado": true|false, "problemas": "vazio se aprovado", "nota": 0-10}}""", modelo)


def criar_roteiro(tema, fatos, modelo):
    obs = ""
    for tentativa in range(3):
        log.info(f"Roteiro longo (tentativa {tentativa + 1}): {tema}")
        r = ia.gerar_json(prompt_roteiro(tema, fatos, obs), modelo)
        caps = [c for c in r.get("capitulos", []) if c.get("blocos")]
        blocos = [b for c in caps for b in c["blocos"] if len([f for f in b.get("falas", []) if f.strip()]) >= 1]
        palavras = sum(len(f.split()) for b in blocos for f in b.get("falas", []))
        if len(caps) < 3 or len(blocos) < 12:
            obs = f"precisa de 5 capítulos e {BLOCOS} blocos com 2 falas cada"
            continue
        if not 1050 <= palavras <= 1800:
            obs = f"o roteiro tem {palavras} palavras; precisa ter entre 1300 e 1500"
            continue
        r["capitulos"] = caps
        rev = revisar(r, fatos, modelo)
        if rev.get("aprovado"):
            r["revisao"] = {"aprovado": True, "nota": rev.get("nota")}
            return r
        obs = rev.get("problemas", "")
        log.warning(f"Revisão reprovou: {obs}")
    return None


# =================================================================== produção
def _srt(ass, destino):
    """Converte as legendas do vídeo (ASS) em SRT para enviar ao YouTube como legenda oficial."""
    def t(s):
        h, m, sec = s.split(":")
        total = int(h) * 3600 + int(m) * 60 + float(sec)
        return f"{int(total // 3600):02d}:{int(total % 3600 // 60):02d}:{int(total % 60):02d},{int(round(total % 1 * 1000)) % 1000:03d}"
    linhas, n = [], 0
    for l in ass.read_text(encoding="utf-8-sig").splitlines():
        if l.startswith("Dialogue:"):
            partes = l.split(",", 9)
            texto = re.sub(r"\{[^}]*\}", "", partes[9]).strip()
            if texto:
                n += 1
                linhas += [str(n), f"{t(partes[1])} --> {t(partes[2])}", texto, ""]
    destino.write_text("\n".join(linhas), encoding="utf-8")
    return destino


def verificar(mp4):
    problemas = []
    try:
        info = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(mp4)],
                                         capture_output=True, text=True, check=True).stdout)
    except Exception as e:  # noqa: BLE001
        return [f"arquivo corrompido ({e})"]
    v = [s for s in info["streams"] if s["codec_type"] == "video"]
    a = [s for s in info["streams"] if s["codec_type"] == "audio"]
    if not v or (int(v[0]["width"]), int(v[0]["height"])) != (1920, 1080):
        problemas.append("vídeo não está em 1920x1080")
    if not a:
        problemas.append("vídeo sem áudio")
    d = float(info["format"].get("duration", 0))
    if not 360 <= d <= 900:
        problemas.append(f"duração fora do padrão ({d / 60:.1f} min)")
    if a:
        r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(mp4), "-af", "ebur128", "-f", "null", "-"],
                           capture_output=True, text=True)
        m = re.findall(r"I:\s+(-?[\d.]+) LUFS", r.stderr)
        if m and not -22 <= float(m[-1]) <= -9:
            problemas.append(f"volume fora do padrão ({m[-1]} LUFS)")
    return problemas


def nota_qualidade(r, fontes, desenhos, falas, audios, mp4, capa, capitulos_desc, problemas):
    pontos, perdas = 0, []

    def item(ok, v, msg):
        nonlocal pontos
        if ok:
            pontos += v
        else:
            perdas.append(f"-{v}: {msg}")
    try:
        rev = float((r.get("revisao") or {}).get("nota") or 0)
    except (TypeError, ValueError):
        rev = 0
    pontos += round(25 * min(rev, 10) / 10)
    if rev < 10:
        perdas.append(f"-{25 - round(25 * min(rev, 10) / 10)}: revisão deu {rev}/10")
    item(bool(fontes), 10, "sem fontes")
    sem = sum(1 for d in desenhos if not Path(d).with_suffix(".svg").exists())
    item(sem <= 1, 15, f"{sem} desenhos falharam")
    ruins = sum(1 for f, a in zip(falas, audios) if not 1.6 <= len(f.split()) / max(duracao(a), 0.1) <= 4.8)
    item(ruins == 0, 10, f"{ruins} falas com narração suspeita")
    sem_t = sum(1 for a in audios if not Path(a).with_suffix(".palavras.json").exists())
    item(sem_t <= 2, 5, f"{sem_t} falas sem tempo exato das palavras")
    item(not problemas, 20, "; ".join(problemas))
    d = duracao(mp4) / 60
    item(8 <= d <= 12.5, 5, f"duração {d:.1f} min (ideal 8 a 12)")
    item(Path(capa).exists(), 5, "capa ausente")
    item(capitulos_desc >= 3, 5, "descrição sem capítulos")
    return min(100, pontos), perdas


def produzir(tema=None, quando=None):
    import animacao
    import main_gratis as mg
    import narracao
    import thumbnail
    cfg = carregar_config()
    modelo = cfg["gemini"]["modelo_texto"]
    reg = ler()
    if op.pausado():
        log.info("Automação pausada no painel: YouTube não produz.")
        return
    alvo = quando or proximo_horario(reg)
    if not quando and any(r["status"] == op.AGUARDANDO and r["horario"] == alvo for r in reg):
        log.info(f"Já existe vídeo agendado para {alvo}.")
        return
    # não produzir de novo se o vídeo de hoje já está agendado
    hoje = agora().date().isoformat()
    if not tema and any(r["status"] in (op.AGUARDANDO, op.PUBLICADO) and r["horario"][:10] == hoje for r in reg) \
            and alvo[:10] == hoje:
        log.info("O vídeo de hoje já está agendado.")
        return
    opcoes = [{"tema": tema, "categoria": "manual", "artigos": [tema]}] if tema else escolher_tema(reg, modelo)
    for o in opcoes:
        vid = f"yt-{agora():%Y%m%d}-{uuid.uuid4().hex[:5]}"
        item = {"id": vid, "criado": agora().isoformat(timespec="minutes"), "tema": o["tema"], "titulo": o["tema"][:70],
                "categoria": o.get("categoria"), "pontuacao_tema": o.get("pontuacao"), "status": op.EM_PRODUCAO,
                "horario": None, "tentativas": 0, "erros": [], "historico": [], "youtube_id": None, "link": None}
        reg.append(item)
        salvar(reg)
        atividade(f"Começou o vídeo longo: {o['tema']}", vid)
        try:
            fatos, fontes = pesquisar(o["tema"], o.get("artigos"), modelo)
            r = criar_roteiro(o["tema"], fatos, modelo)
            if not r:
                raise RuntimeError("roteiro reprovado 3 vezes")
        except Exception as e:  # noqa: BLE001
            op.mudar(item, op.CANCELADO, str(e))
            op.marcar_tema(o["tema"], "descartado", str(e))
            atividade(f"Tema descartado: {o['tema']} — {e}", vid)
            salvar(reg)
            continue
        item.update(titulo=r["titulo"], fontes=fontes)
        pasta = RAIZ / "saida" / f"{vid}_{slug(r['titulo'])[:40]}"
        pasta.mkdir(parents=True, exist_ok=True)
        (pasta / "roteiro.json").write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            blocos = [(ci, b) for ci, c in enumerate(r["capitulos"]) for b in c["blocos"]]
            rd = {"cenas": [{"visual": b.get("visual", "")} for _, b in blocos], "personagens": r.get("personagens", ""),
                  "formato_video": "16:9"}
            desenhos = mg.desenhar_cenas(cfg, rd, pasta)
            for _ in range(2):
                falhos = [d for d in desenhos if not d.with_suffix(".svg").exists()]
                if not falhos:
                    break
                for d in falhos:
                    d.unlink(missing_ok=True)
                desenhos = mg.desenhar_cenas(cfg, rd, pasta)
            falas, pngs, titulos, destaques, inicio_cap = [], [], [], [], {}
            for k, (ci, b) in enumerate(blocos):
                for f in [x for x in b.get("falas", []) if x.strip()][:2]:
                    inicio_cap.setdefault(ci, len(falas))
                    falas.append(f.strip())
                    pngs.append(desenhos[k])
                    titulos.append(r["capitulos"][ci]["titulo"])
                    destaques.append(b.get("destaques") or [])
            auds = narracao.narrar_cenas(cfg, [{"narracao": f} for f in falas], pasta, "yt")
            rot = {"cenas": [{"narracao": f, "destaques": d} for f, d in zip(falas, destaques)],
                   "surpresa": inicio_cap.get(len(r["capitulos"]) - 1, len(falas) - 4)}
            mp4 = animacao.montar_tiktok(cfg, rot, pngs, auds, titulos, pasta, MARCA, minimo=0, nome="youtube",
                                         formato="16:9", texto_seguir="▶ INSCREVA-SE NO BINO EXPLICA")
            tempos = json.loads((pasta / "tempos.json").read_text())
            caps = []
            for ci, c in enumerate(r["capitulos"]):
                if ci in inicio_cap:
                    s = 0 if ci == 0 else int(tempos[inicio_cap[ci]])
                    caps.append(f"{s // 60:02d}:{s % 60:02d} {c['titulo']}")
            descricao = (r.get("descricao", "").strip() + "\n\n📌 Capítulos\n" + "\n".join(caps) +
                         "\n\n📚 Fontes\n" + "\n".join(f"- {f['titulo']}: {f.get('url', '')}" for f in fontes) +
                         "\n\nSe inscreve no Bino Explica pra uma curiosidade nova todo dia! 🔔\n"
                         "Instagram: @binoteexplica")
            idx_capa = min(len(desenhos) - 1, max(0, len(desenhos) - 3))
            capa = thumbnail.gerar(desenhos[idx_capa], r.get("texto_capa") or r["titulo"], pasta / "capa.jpg",
                                   selo=(r.get("selo") or "")[:14].upper(), frase=r.get("frase_capa", ""))
            srt = _srt(pasta / "_trab_animado" / "legendas.ass", pasta / "legendas.srt")
            nota, perdas = nota_qualidade(r, fontes, desenhos, falas, auds, mp4, capa, len(caps), verificar(mp4))
            item.update(qualidade=nota, perdas_qa=perdas, duracao=round(duracao(mp4), 1), capitulos=caps)
            log.info(f"Controle de qualidade: {nota}/100 {perdas}")
            nome = slug(r["titulo"])[:50]
            arqs = {pasta / f"{nome}.mp4": mp4, pasta / f"{nome}-capa.jpg": capa, pasta / f"{nome}-legenda.srt": srt}
            (pasta / f"{nome}-descricao.txt").write_text(f"{r['titulo']}\n\n{descricao}\n\nTags: {', '.join(r.get('tags', []))}",
                                                         encoding="utf-8")
            arqs[pasta / f"{nome}-descricao.txt"] = pasta / f"{nome}-descricao.txt"
            for dst, src in arqs.items():
                if dst != src:
                    shutil.copyfile(src, dst)
            aprovado = nota >= op.NOTA_MINIMA
            subprocess.run(["gh", "release", "create", vid, *map(str, arqs), "--title",
                            f"{'▶️' if aprovado else '🧪'} {r['titulo']}", "--notes",
                            (f"Vídeo de {item['duracao'] / 60:.1f} min · qualidade {nota}/100 · "
                             f"{'agendado no YouTube para ' + alvo[8:10] + '/' + alvo[5:7] + ' ' + alvo[11:16] if aprovado else 'QUARENTENA: ' + '; '.join(perdas)}"),
                            "--latest=false"], check=True)
            item["release"] = vid
            if not aprovado:
                op.mudar(item, op.QUARENTENA, "; ".join(perdas))
                atividade(f"Vídeo longo em quarentena ({nota}/100): {r['titulo']}", vid, True)
                salvar(reg)
                print(f"::warning::Vídeo do YouTube em quarentena ({nota}/100): {'; '.join(perdas)}")
                continue
            item["horario"] = alvo
            enviar(item, mp4, capa, srt, r, descricao, alvo)
            salvar(reg)
            return
        except Exception as e:  # noqa: BLE001
            op.mudar(item, op.FALHA, str(e))
            item["erros"].append(f"{agora():%d/%m %H:%M} {str(e)[:300]}")
            atividade(f"Falha no vídeo longo '{item['titulo']}': {str(e)[:250]}", vid, True)
            salvar(reg)
            log.error(f"Falha: {e}")
            raise
    print("::warning::Nenhum vídeo do YouTube foi aprovado hoje (veja o PAINEL.md).")
    sys.exit(1)


def enviar(item, mp4, capa, srt, r, descricao, alvo):
    """Envia agendado (o próprio YouTube publica às 19:30). Sem conexão, fica em Releases para postar à mão."""
    import youtube_upload as yu
    if not yu.conectado():
        op.mudar(item, op.AGUARDANDO, "YouTube não conectado: arquivos em Releases")
        atividade(f"Vídeo pronto em Releases ({item['id']}); YouTube não conectado.", item["id"])
        print(f"::warning::YouTube não conectado (segredos YOUTUBE_*). Vídeo pronto em Releases: {item['id']}")
        return
    existente = yu.ja_enviado(r["titulo"])
    if existente:
        item.update(youtube_id=existente, link=f"https://youtu.be/{existente}")
        op.mudar(item, op.AGUARDANDO, "já estava no canal (sem duplicar)")
        return
    quando_utc = datetime.fromisoformat(alvo).astimezone(timezone.utc)
    cfg = carregar_config()
    cfg["publicacao"]["feito_para_criancas"] = False
    vid, info = yu.publicar_agendado(cfg, mp4, r["titulo"], descricao, r.get("tags", [])[:15], capa, quando_utc, srt)
    item.update(youtube_id=vid, link=f"https://youtu.be/{vid}", envio=info)
    op.mudar(item, op.AGUARDANDO, f"enviado ao YouTube, agendado para {alvo[11:16]}")
    atividade(f"Enviado ao YouTube e agendado para {alvo[8:10]}/{alvo[5:7]} {alvo[11:16]}: {r['titulo']} "
              f"(status {info.get('privacidade')})", item["id"])
    print(f"::notice::Vídeo agendado no YouTube: {r['titulo']} → https://youtu.be/{vid} ({info})")


def conferir():
    import youtube_upload as yu
    reg = ler()
    if not yu.conectado():
        return
    for r in reg:
        if r["status"] == op.AGUARDANDO and r.get("youtube_id") and datetime.fromisoformat(r["horario"]) <= agora():
            st = yu.status(r["youtube_id"])
            if st.get("privacyStatus") == "public":
                op.mudar(r, op.PUBLICADO, "confirmado no YouTube")
                r["publicado"] = agora().isoformat(timespec="minutes")
                atividade(f"No ar no YouTube: {r['titulo']} → {r['link']}", r["id"])
            else:
                atividade(f"'{r['titulo']}' ainda está {st.get('privacyStatus')} no YouTube "
                          "(app sem auditoria do Google publica como privado: mude para público no YouTube Studio).",
                          r["id"], True)
    salvar(reg)


def auditoria():
    import youtube_upload as yu
    if not yu.conectado():
        print("❌ YouTube: faltam os segredos YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET e YOUTUBE_REFRESH_TOKEN.")
        return
    try:
        c = yu.canal()
        print(f"✅ YouTube conectado: {c.get('titulo')} ({c.get('inscritos')} inscritos, {c.get('videos')} vídeos)")
    except Exception as e:  # noqa: BLE001
        print(f"❌ YouTube: {e}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("acao", choices=["produzir", "conferir", "auditoria"])
    ap.add_argument("--tema", default="")
    ap.add_argument("--quando", default="")
    a = ap.parse_args()
    try:
        if a.acao == "produzir":
            q = None
            if a.quando:
                m = re.fullmatch(r"\s*(\d{1,2})/(\d{1,2})\s+(\d{1,2}):(\d{2})\s*", a.quando)
                if m:
                    d, mes, h, mi = map(int, m.groups())
                    q = datetime(agora().year, mes, d, h, mi, tzinfo=op.FUSO).isoformat(timespec="minutes")
            produzir(a.tema or None, q)
        elif a.acao == "conferir":
            conferir()
        else:
            auditoria()
    finally:
        try:
            import reels
            op.painel(reels.ler_registro())
        except Exception as e:  # noqa: BLE001
            log.warning(f"Painel não atualizado: {e}")
