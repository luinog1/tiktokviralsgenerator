# ViralPost Studio

Aplicação Flask que transforma o texto gerado pelo **goviral.ai** em um carrossel visual pronto para publicar — combinando o texto colado com imagens da API oficial do Pinterest, composição opcional via LLM e renderização estilo **TikTok photo post** (1080×1350, 4:5).

> **Status:** MVP v0.4 — Ready for building
> **Stack:** Python 3.11 · Flask 3 · Jinja2 · WTForms · Pillow · Docker
> **Idioma inicial:** Português (pt-BR)

---

## 🎯 O que mudou na v0.4

- ✅ **Estilo `sticker` (padrão)** — texto preto em caixas brancas arredondadas, uma por linha, sobre a foto sem escurecer. É o formato de legenda nativo dos photo posts do TikTok.
- ✅ **Roteiro viral** — os slides são ordenados na estrutura de 3 atos (`hook → problema → agitação → valor → prova → CTA`). Cada slide carrega um `role`, e o `role` decide onde o texto é posicionado na imagem.
- ✅ **Prompt de roteirista no Groq** — o LLM reordena e encurta o texto colado seguindo os tipos de hook e as regras de escrita de script viral, em vez de só fatiar o texto.
- 🐛 **Fontes no Docker** — a imagem `python:3.11-slim` não traz nenhuma fonte TrueType, então o Pillow caía na fonte bitmap padrão e renderizava os slides com texto minúsculo. Agora `fonts-liberation` e `fonts-dejavu-core` são instaladas.
- 🐛 **Texto duplicado** — headline e body recebiam a mesma frase quando o parágrafo tinha uma só sentença.
- 🐛 **Emoji virava tofu (`□`)** — as fontes do sistema não têm glifo de emoji; agora o emoji é removido do PNG e preservado na legenda/Markdown.
- 🐛 **Conflito de merge** — `.env.example` estava commitado com marcadores `<<<<<<< HEAD`.

---

## 🎬 Estrutura do roteiro viral

O texto colado é reorganizado nesta ordem (baseada na estrutura de script viral em 3 atos):

| Papel | Função no carrossel |
|-------|---------------------|
| `hook` | Para o scroll no primeiro segundo. Fica sozinho e ancorado embaixo. |
| `problem` | Nomeia a dor do público. |
| `agitation` | Amplia a consequência de não resolver. |
| `value` | A entrega concreta — uma ideia por slide. |
| `proof` | Número, resultado ou prova de que funciona. |
| `cta` | Uma única ação clara. Centralizado, é o único slide com CTA. |

A distribuição se adapta ao nº de slides — 3 slides viram `hook → value → cta`; 6 ou mais recebem a estrutura completa, com o miolo em slides de `value`.

---

## 🔌 Sobre o goviral.ai

O `content.goviralai.app` **não possui API pública** — responde `HTTP 403` a qualquer requisição programática e não publica documentação de desenvolvedor. A autenticação é uma sessão Discord presa ao navegador.

Reaproveitar essa sessão no servidor significaria repassar seus cookies, ou seja, automação de login não autorizada — exatamente o que o escopo deste projeto proíbe e o que pode derrubar sua conta. Por isso o fluxo continua sendo **colar o texto**, e o trabalho de estruturação acontece aqui, via Groq.

---

## ✨ Funcionalidades do MVP

- Landing page com link direto para o goviral.ai (login Discord manual).
- Formulário com textarea para o texto colado + tema, estilo, nº de slides, idioma e keywords.
- Composição de carrossel via TextComposer (mock determinístico ou LLM).
- Ordenação no roteiro viral de 3 atos (`hook → problema → agitação → valor → prova → CTA`).
- Renderização estilo sticker do TikTok — caixas brancas arredondadas com texto preto.
- Busca de imagens via API oficial do Pinterest (com fallback mock).
- Ranking opcional de imagens por endpoint LLM (com fallback determinístico).
- Prévia do carrossel com slides editáveis (headline, body, CTA por slide) e o papel de cada slide visível.
- Galeria miniatura por slide para troca de imagem.
- Exportação em três formatos:
  - **ZIP** — todos os slides PNG + Markdown anexo.
  - **PNG** — slide único (primeiro).
  - **Markdown** — texto plano com hashtags e atribuição.
- Health check sem expor segredos.
- Funciona em modo **mock** sem credenciais externas.

Fora do escopo (conforme PRD v0.2): publicação automática, scraping, automação de login via Discord, geração de vídeos, banco de imagens próprio.

---

## 🚀 Execução rápida (modo mock)

```bash
# 1. Configurar ambiente (defaults mock — funciona sem credenciais)
cp .env.example .env

# 2. Rodar com Docker
docker compose up --build

# 3. Abrir em http://localhost:5000
```

Sem Docker (desenvolvimento local):

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
python run.py
```

### Fluxo de uso

1. Acesse [https://content.goviralai.app/](https://content.goviralai.app/) (login Discord) **em outra aba**.
2. Gere o texto pronto lá.
3. No ViralPost Studio (`http://localhost:5000/create`), **cole o texto** no campo "Texto do goviral.ai".
4. Preencha tema, estilo (**sticker** recomendado — ou quote/list/tutorial/story) e nº de slides (3/6/9/12).
5. Clique em "Gerar carrossel" — o sistema estrutura o texto no roteiro viral e busca imagens.
6. Na prévia, cada slide mostra seu papel (hook, problema, valor, CTA). Edite os textos e escolha a imagem.
7. Exporte: **ZIP** (carrossel completo) ou **PNG** (slide único) ou **Markdown** (texto).

---

## ⚙️ Variáveis de ambiente

| Variável | Default | Descrição |
|----------|---------|-----------|
| `FLASK_ENV` | `development` | Ambiente Flask |
| `SECRET_KEY` | `dev-insecure-change-me` | **Definir em produção** |
| `DEBUG` | `true` | Modo debug |
| `PINTEREST_ACCESS_TOKEN` | (vazio) | Token da API oficial v5. Vazio → mock |
| `PINTEREST_API_BASE_URL` | `https://api.pinterest.com/v5` | Base URL da API |
| `LLM_PROVIDER` | `mock` | `mock` ou `openai_compatible` |
| `LLM_API_BASE_URL` | (vazio) | Endpoint OpenAI-compatible (ex.: `https://api.groq.com/openai/v1`) |
| `LLM_API_KEY` | (vazio) | Token do LLM (ex.: `gsk_...` para Groq) |
| `LLM_MODEL` | (vazio) | Nome do modelo. Ex.: `qwen/qwen3.6-27b`, `llama-3.3-70b-versatile`, `gpt-4o-mini` |
| `RANKING_ENABLED` | `true` | Liga/desliga ranking de imagens (reusa LLM) |
| `REQUEST_TIMEOUT_SECONDS` | `20` | Timeout HTTP |
| `SESSION_TTL_MINUTES` | `60` | TTL dos projetos em memória |
| `SLIDE_WIDTH` | `1080` | Largura do slide PNG |
| `SLIDE_HEIGHT` | `1350` | Altura do slide PNG (4:5 = TikTok/Instagram) |
| `SLIDE_FONT_BOLD` | (auto) | Caminho para um `.ttf` bold. Vazio → detecção automática |
| `SLIDE_FONT_REGULAR` | (auto) | Caminho para um `.ttf` regular. Vazio → detecção automática |

**Compatibilidade reversa:** variáveis `RANKING_*` antigas (`RANKING_PROVIDER`, `RANKING_API_BASE_URL`, `RANKING_API_KEY`, `RANKING_MODEL`) ainda funcionam e mapeiam para `LLM_*`.

Nenhum valor secreto é commitado. Tokens nunca cruzam para o frontend.

---

## 🗂️ Estrutura do projeto

```
.
├── app/
│   ├── __init__.py
│   ├── main.py                # Flask app factory
│   ├── config.py              # Settings (env)
│   ├── forms.py               # WTForms (BriefingForm + SlideEditForm)
│   ├── adapters/
│   │   ├── text_composer.py    # TextComposer (mock + LLM)
│   │   ├── pinterest_client.py # Pinterest v5 + Mock
│   │   └── ranking_provider.py # Inference (LLM) + Mock
│   ├── services/
│   │   ├── generation.py      # Orquestração do carrossel
│   │   ├── session_store.py   # Persistência leve (TTL)
│   │   └── slide_renderer.py  # Pillow — overlay de texto em imagem
│   └── routes/
│       ├── main.py            # /
│       ├── create.py          # /create
│       ├── generate.py        # /generate, /rank
│       ├── preview.py         # /preview/<id>, /edit, /export
│       └── health.py         # /health
├── templates/                 # Jinja2 (base, index, create, preview, health, error)
├── static/                    # CSS, JS
├── tests/                     # pytest
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── requirements-dev.txt
├── .env.example
├── .dockerignore
├── .gitignore
└── run.py
```

---

## 🧪 Testes

```bash
pip install -r requirements-dev.txt
pytest -v tests/
```

Cobertura (66 testes):
- **TextComposer** — split em slides, hashtags, texto curto, texto vazio.
- **Roteiro viral** — distribuição de papéis por nº de slides, ordem `hook…cta`, CTA só no fecho, sem texto duplicado entre headline e body.
- **SlideRenderer** — resolução de fonte TrueType, auto-ajuste do corpo da fonte, caixas brancas do estilo sticker, ausência de overlay escuro, posição do hook vs. valor, quebra de palavra longa, remoção de emoji.
- **Pinterest mock** — geração de SVGs sintéticos.
- **Ranking** — correlação com `raw_text`, fallback sem corpus.
- **Settings** — mock vs LLM configurado, compatibilidade reversa.
- **Forms** — validação de `raw_text` (mín 20 chars), `theme`, `style`, `slides_count`.
- **Rotas** — fluxo completo (`/` → `/create` → `/generate` → `/preview` → `/edit` → `/export` ZIP/PNG/MD).

---

## 🔌 Endpoints

| Método | Rota | Descrição |
|--------|------|-----------|
| GET | `/` | Landing page + status |
| GET | `/create` | Formulário de briefing (texto colado) |
| POST | `/generate` | Executa composição do carrossel |
| POST | `/rank` | Reordena imagens (JSON) |
| GET | `/preview/<id>` | Exibe carrossel com slides editáveis |
| POST | `/preview/<id>/edit` | Atualiza slides editados |
| POST | `/preview/<id>/export` | Baixa ZIP / PNG / Markdown |
| GET | `/health` | Health check JSON |

---

## 🎨 Estilos visuais

Cada estilo produz um layout distinto no PNG renderizado:

| Estilo | Layout | Caso de uso |
|--------|--------|-------------|
| `sticker` | **(padrão)** Caixas brancas arredondadas por linha, texto preto, foto sem escurecimento. Posição varia pelo papel do slide no roteiro | Photo post nativo do TikTok |
| `quote` | Aspas decorativas + headline centralizada + body + CTA inferior | Frases inspiradoras, quotes |
| `list` | Headline à esquerda com barra de destaque + bullets + CTA centralizado | Listas de dicas, passos numerados |
| `tutorial` | Tag "PASSO A PASSO" + headline + body + CTA em caixa colorida | Tutoriais, como-fazer |
| `story` | Tag "HISTÓRIA" + headline grande + body centralizado + CTA | Narrativas, storytelling |

**Dimensões:** 1080×1350px (4:5) — formato ideal para TikTok photo posts e Instagram Reels cover.

### Tipografia

As fontes são detectadas automaticamente, nesta ordem: `static/fonts/` → Liberation/DejaVu (Linux) → Segoe UI/Arial (Windows) → Arial (macOS).

Para trocar a tipografia (ex.: Poppins, para chegar mais perto do visual do TikTok), solte os arquivos em `static/fonts/sticker-bold.ttf` e `static/fonts/sticker-regular.ttf` — ou aponte `SLIDE_FONT_BOLD` / `SLIDE_FONT_REGULAR` para os `.ttf` desejados.

> **Nota:** emoji é removido do PNG (as fontes do sistema não têm esses glifos e o Pillow desenharia um retângulo vazio). O emoji continua na legenda e no Markdown exportado.

---

## 🔐 Segurança

- Tokens são lidos do ambiente e usados apenas no backend.
- CSRF habilitado em todos os forms (Flask-WTF).
- Logs não contêm credenciais.
- Atribuição e link da imagem são exibidos na prévia e no Markdown exportado.
- O `health` endpoint **não** expõe tokens, prompts ou segredos.
- O goviral.ai é acessado manualmente pelo usuário — o ViralPost Studio nunca faz scraping ou automação de login.

---

## ⚠️ Limitações e compliance

- **goviral.ai:** ferramenta externa sem API/token. O usuário é responsável por acessar via login Discord e colar o texto no formulário. O ViralPost Studio não automatiza o acesso.
- **Pinterest:** a busca usa a API oficial v5. Imagens retornadas podem não ter licença comercial — sempre verifique os termos antes de publicar. A atribuição é preservada na exportação.
- **LLM:** o endpoint é opcional. Groq, OpenAI ou qualquer provedor OpenAI-compatible podem ser usados. "Free model" não implica em disponibilidade permanente ou autorização comercial — valide os termos.
- **Persistência:** em memória por processo. Reiniciar o container apaga projetos. Para multi-worker, substitua `SessionStore` por Redis ou DB.
- **Sem scraping:** nenhuma parte do código faz scraping de Pinterest, goviral.ai, Discord ou TikTok.

---

## 🎯 Critérios de aceitação atendidos

- [x] `docker compose up --build` inicia a aplicação.
- [x] `.env.example` documenta todas as configurações.
- [x] Aplicação funciona em modo mock sem credenciais.
- [x] Briefing é validado (raw_text, theme, style, slides_count).
- [x] TextComposer retorna estrutura consistente (slides + hashtags + caption).
- [x] Cliente Pinterest é server-side e trata erros.
- [x] LLM pode ser desligado (provider=mock).
- [x] LLM possui fallback funcional (timeout → mock).
- [x] Usuário pode escolher manualmente a imagem de cada slide.
- [x] Prévia é editável (headline + body + CTA por slide).
- [x] Usuário consegue copiar legenda/hashtags e baixar conteúdo.
- [x] Origem da imagem aparece na interface e no Markdown exportado.
- [x] Nenhum segredo aparece no frontend, logs ou repositório.
- [x] Testes unitários para validação, adapters e fallback.
- [x] README com instalação, configuração e execução.
- [x] Não há scraping nem automação de login não autorizada.

---

## 🛣️ Próximos passos

1. Configurar `LLM_API_BASE_URL` e `LLM_API_KEY` (ex.: Groq) para ativar o roteiro viral com LLM real. Modelos Groq suportados: `qwen/qwen3.6-27b`, `llama-3.3-70b-versatile`, `llama-3.1-8b-instant`, `mixtral-8x7b-32768`, `gemma2-9b-it` (consulte https://console.groq.com/docs/models para a lista atual).
2. Validar escopos do token Pinterest para a busca de Pins.
3. Adicionar uma fonte própria em `static/fonts/` (ex.: Poppins) para aproximar ainda mais do visual do TikTok.
4. Adicionar mais estilos visuais (antes-e-depois, capa de carrossel, etc.).
5. Persistência real (DB ou Redis) para multi-worker.

---

## 📄 Licença

Uso interno. Componentes externos sujeitos aos seus próprios termos (Pinterest API ToS, goviral.ai, modelo de LLM escolhido).
