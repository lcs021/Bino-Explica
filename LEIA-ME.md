# Bino Explica — criação e postagem automática, 100% grátis ✏️

Toda segunda, quarta e sexta, a nuvem do GitHub (grátis) faz sozinha:
**escolhe o tema → Gemini escreve o roteiro e confere os fatos → Gemini desenha 8 cenas em rabisco →
voz neural da Microsoft narra → edita com legendas → posta no YouTube (+ Shorts) e no TikTok.**
Também gera a versão 4:5 do feed do Instagram para você baixar.

Custo: **R$ 0**. Nenhuma parte pede cartão de crédito.

## Ligar (só 1 chave obrigatória)

1. Entre em **aistudio.google.com/apikey** com sua conta Google → **Create API key** → copie.
2. No GitHub: **Settings → Secrets and variables → Actions → New repository secret**
   Nome: `GEMINI_API_KEY` · Valor: a chave copiada → **Add secret**.
3. **Settings → Actions → General → Workflow permissions → Read and write permissions → Save**.
4. Teste: aba **Actions → Bino Explica (grátis) → Run workflow** (marque "Só criar" no primeiro teste).
   Em ~15 min os vídeos aparecem em **Artifacts**, com as legendas prontas em `legendas.txt`.

Sem as autorizações de postagem, o sistema cria tudo e deixa para baixar.
Para postar sozinho, cadastre também `YOUTUBE_TOKEN_JSON`, `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET`
e `TIKTOK_REFRESH_TOKEN` (Parte A abaixo — grátis, feito uma vez em um computador).

**Vídeo com voz a partir do site:** no Estúdio, toque em **🎙️ Gerar vídeo com voz**, envie o arquivo baixado para a
pasta `episodios/` (GitHub → Add file → Upload files) e o robô monta sozinho com voz neural (sem usar o Gemini).

Temas: edite `temas_virais.txt`. Horários: `.github/workflows/bino-explica.yml` (linha `cron`, em UTC).

---

# Turibenção Automático 🐑🌈

Sistema que roda **na nuvem (GitHub Actions, grátis)** e, sozinho, **escolhe o tema → escreve o roteiro → revisa → gera as ilustrações → narra → edita → publica** no YouTube (vídeo principal + Shorts) e no TikTok.

## O que ele faz em cada vídeo

| Etapa | Ferramenta | Custo |
|---|---|---|
| Roteiro de ~2:30 + corte de ~55s, título, descrição, tags | Claude (Anthropic) | centavos |
| Revisão automática: fidelidade bíblica, adequado para crianças, português | Claude | centavos |
| 12 ilustrações + miniatura no estilo papel recortado 3D, com o cordeirinho **Turi** | OpenAI (gpt-image-1) | ~US$ 0,25 (low) a ~US$ 1 (medium) |
| Narração em português (voz neural) | edge-tts da Microsoft | **grátis** |
| Edição: zoom/panorâmica, legendas, música, marca d'água | ffmpeg (no seu PC) | grátis |
| Publicação | YouTube Data API + TikTok Content Posting API | grátis |

Saídas em `saida/AAAA-MM-DD_tema/`: `video_longo.mp4` (1920×1080), `video_curto.mp4` (1080×1920), `miniatura.jpg` e `roteiro.json`.


---

## ⚠️ Leia antes: o que o YouTube e o TikTok exigem

1. **Vídeos ficam privados até a auditoria.** Tanto o YouTube quanto o TikTok forçam como *privado* todo vídeo enviado por um app de desenvolvedor novo, até o app passar por uma auditoria deles. O sistema funciona desde o primeiro dia, mas para sair público você precisa pedir:
   - **YouTube:** formulário "YouTube API Services – Audit and Quota Extension" no Google Cloud. Diga que é uma ferramenta própria para publicar no seu único canal.
   - **TikTok:** no portal developers.tiktok.com, envie o app para revisão (Content Posting API → Direct Post). Até lá, a conta do TikTok precisa estar como privada para receber os posts.
2. **Conteúdo infantil:** o sistema marca todo vídeo do YouTube como **"feito para crianças"** (obrigatório por lei — COPPA). Isso desliga comentários e anúncios personalizados; é normal para canais infantis.
3. **IA:** no TikTok o vídeo vai com o rótulo de conteúdo gerado por IA, como a plataforma pede.

---

## Parte A — Preparar no seu PC (uma vez só)

A autorização do YouTube e do TikTok precisa de um navegador, então é feita uma única vez no PC. Depois disso, tudo roda na nuvem.

### 1. Programas
- **Python 3.11 ou mais novo** — python.org (marque *"Add Python to PATH"* na instalação).
- **ffmpeg** — só se quiser rodar no PC também: `winget install Gyan.FFmpeg`

### 2. Preparar a pasta
Abra o Prompt de Comando **dentro desta pasta** e rode:
```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Chaves de IA
Copie `.env.exemplo` para `.env` e preencha:
- `ANTHROPIC_API_KEY` — console.anthropic.com → API Keys
- `OPENAI_API_KEY` — platform.openai.com → API keys (coloque uns US$ 5–10 de crédito)

### 4. Música e marca d'água (opcional, recomendado)
- Coloque músicas infantis **sem direitos autorais** em `assets/musicas/` (ex.: Biblioteca de Áudio do YouTube Studio). Uma é sorteada por vídeo.
- Coloque a marca d'água do canal como `assets/marca_dagua.png` (fundo transparente).

### 5. Conectar o YouTube
1. console.cloud.google.com → crie um projeto → ative **YouTube Data API v3**.
2. *Tela de consentimento OAuth* → tipo Externo → adicione seu e-mail em **Usuários de teste** → depois clique em **Publicar app** (status *Em produção*). ⚠️ Se ficar em *Teste*, o Google desliga a autorização a cada 7 dias e a nuvem para de publicar. Na hora de autorizar vai aparecer "app não verificado": clique em *Avançado → Acessar*, é o seu próprio app.
3. *Credenciais* → Criar → **ID do cliente OAuth** → tipo **App para computador** → baixe o JSON e salve aqui como `client_secret.json`.
4. Rode `python autorizar_youtube.py` e autorize **com a conta do canal Turibenção**.
5. Dica: verifique o canal por telefone (youtube.com/verify) para a miniatura personalizada funcionar.

### 6. Conectar o TikTok
1. developers.tiktok.com → *Manage apps* → crie um app → adicione **Login Kit** e **Content Posting API** (ative *Direct Post*).
2. Em Login Kit, cadastre uma **Redirect URI** com https (pode ser qualquer página sua, até uma página do GitHub Pages).
3. Preencha `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET` e `TIKTOK_REDIRECT_URI` no `.env`.
4. Rode `python autorizar_tiktok.py`, autorize e cole o endereço da página para onde o TikTok te mandar.

### 7. Gerar os segredos
```
python preparar_nuvem.py
```
Ele mostra 6 valores. Deixe a janela aberta para o próximo passo.

---

## Parte B — Colocar na nuvem (GitHub Actions)

1. Crie uma conta grátis em **github.com**.
2. Clique em **New repository** → nome `turibencao-auto` → marque **Private** → *Create*.
3. Na página do repositório, clique em **uploading an existing file** e arraste **todo o conteúdo desta pasta** (inclusive a pasta `.github`).
   ⚠️ Não envie `.env`, `client_secret.json` nem `token_*.json`.
   *Dica: a pasta `.github` começa com ponto e pode estar oculta no Windows. No Explorador de Arquivos, ative "Exibir → Itens ocultos".*
4. Vá em **Settings → Secrets and variables → Actions → New repository secret** e crie os 6 segredos mostrados pelo `preparar_nuvem.py`, com o nome e o valor exatos:
   `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `YOUTUBE_TOKEN_JSON`, `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET`, `TIKTOK_REFRESH_TOKEN`
5. Vá em **Settings → Actions → General → Workflow permissions** → marque **Read and write permissions** → *Save*. Isso deixa o sistema salvar o histórico e não repetir temas.

### Testar
Aba **Actions** → *Turibenção Automático* → **Run workflow** → marque *"Só criar os vídeos, sem publicar"* → *Run*.
Em ~10 min, abra a execução e baixe os vídeos em **Artifacts** (lá embaixo).

### Funcionando sozinho
Pronto! Ele roda **segunda, quarta e sexta, ~17h45 (Brasília)**, mesmo com o PC desligado.
- **Mudar dias/horário:** edite a linha `cron:` em `.github/workflows/turibencao.yml`. O horário é em UTC, então some 3 horas ao horário de Brasília (ex.: 9h → `0 12 * * *`).
- **Rodar agora:** use o botão *Run workflow*. Dá para digitar um tema específico.
- **Ver o que aconteceu:** cada execução na aba Actions mostra o log. Os vídeos ficam guardados 30 dias em *Artifacts*.
- **Avisos de falha:** o GitHub manda e-mail quando uma execução falha.
- **Custo da nuvem:** grátis. O repositório privado tem 2.000 minutos/mês e cada vídeo usa ~10.

### Renovações
- **TikTok:** a autorização dura cerca de 1 ano. Se aparecer no log um aviso de que o token foi trocado, rode `autorizar_tiktok.py` e `preparar_nuvem.py` no PC e atualize o segredo `TIKTOK_REFRESH_TOKEN`.
- **YouTube:** com o app em *Em produção*, a autorização não expira sozinha.

---

## Rodar no PC (opcional)
Os arquivos `rodar.bat` e `agendar.bat` continuam funcionando, se um dia você preferir rodar localmente.

## Personalizar (`config.yaml`)
- **estilo_visual** e **personagens_fixos** — a identidade das imagens. O Turi aparece em todo vídeo.
- **narracao.voz** — `pt-BR-FranciscaNeural` (feminina), `pt-BR-AntonioNeural` (masculina).
- **imagens.qualidade** — `low` (mais barato) / `medium` / `high`.
- **publicacao** — ligar/desligar YouTube, Shorts ou TikTok.
- **temas.txt** — a fila de histórias (40 já incluídas). Quando acabar, o Claude sugere novas sozinho.

Depois de editar `config.yaml` ou `temas.txt`, envie o arquivo de novo no GitHub: abra o arquivo no repositório → ícone de lápis → cole → *Commit changes*.

## Segurança
Mantenha o repositório **privado**. Nunca compartilhe `.env`, `client_secret.json`, `token_youtube.json` nem `token_tiktok.json` — são as chaves das suas contas.

## Caso Ao Vivo (vídeos de crimes reais)

1. No site **Caso Ao Vivo**, gere o vídeo e clique em **Baixar caso para narrar**.
2. Envie o arquivo `caso-....json` para a pasta `casos/` aqui do GitHub (Add file → Upload files).
3. O robô narra com a voz masculina pt-BR-AntonioNeural (a mesma tecnologia de voz do Bino), monta o vídeo com o apresentador
   no estúdio noir e guarda em **Actions → Caso Ao Vivo (crimes reais) → Artifacts**.

Esses vídeos não são postados sozinhos: confira os fatos do arquivo `post.txt` antes de publicar.
Formatos: TikTok (vertical), Instagram Reels (vertical com os textos fora das áreas que o Instagram cobre) e YouTube (horizontal).
Arquivos: `montar_caso.py`, `caso_video.py`, `assets/caso/`, `.github/workflows/caso-ao-vivo.yml`.
