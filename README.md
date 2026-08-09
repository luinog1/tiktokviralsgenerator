# ViralPost Studio

Aplicação Flask que transforma o texto gerado pelo **goviral.ai** em um carrossel visual pronto para publicar — combinando o texto colado com imagens da API oficial do Pinterest, composição opcional via LLM e renderização estilo **TikTok photo post** (1080×1350, 4:5).

> **Status:** MVP v0.6 — Ready for building
> **Stack:** Python 3.11 · Flask 3 · Jinja2 · WTForms · Pillow · Docker
> **Idioma inicial:** Português (pt-BR)

---

## 🎯 O que mudou na v0.6

- ✅ **Roteiro por imagem** — em vez de colar o texto inteiro e deixar o LLM fatiar, o formulário agora tem um campo por foto do carrossel: `Imagem 1 (hook)`, `Imagem 2 (problema)`, e assim por diante. O que você cola em cada campo é **exatamente** o que sai naquela imagem, na ordem em que você escolheu. Nenhum LLM reescreve por cima. O modo antigo (colar tudo e deixar fatiar) continua ali, agora como uma escolha explícita.
- ✅ **Colar e distribuir** — se o roteiro do goviral.ai vem numerado (`1.`, `Slide 2:`, `---`), cole tudo na caixa de distribuição e o app separa os blocos nos campos certos. Os marcadores são removidos e o texto fica editável antes de gerar.
- ✅ **Casting de imagens por papel** — a imagem 1 recebe uma foto **com pessoa** e as demais recebem cenário (estética, viagem, comida). É o formato dos photo posts de lifestyle que performam: um rosto para parar o scroll, o resto como b-roll. Configurável em `HOOK_SUBJECT`.
- ✅ **Visão classifica o assunto** — com `VISION_ENABLED=true`, o VLM (Qwen-VL na ModelScope, por exemplo) diz se cada foto tem mulher, homem, pessoa genérica ou só cenário. Esse sinal manda no casting. Sem chave configurada, o casting continua funcionando por busca separada + metadado.

### O roteiro por imagem na prática

```
Imagem 1 (hook)      →  "ninguém acorda às 5h por disciplina"
Imagem 2 (problema)  →  "acorda porque dormiu às 21h
                          ninguém fala essa parte"
Imagem 3 (CTA)       →  "salva pra começar amanhã"
```

A primeira linha de cada bloco vira a **headline** (o texto grande); as linhas seguintes viram o **corpo**. Uma linha só = só headline. O arraste das caixas sobre a foto continua igual — o modo roteiro decide *o quê* e *onde na sequência*, o arraste decide *onde na foto*.

Blocos em branco são descartados e o carrossel encolhe: se você abrir 6 campos e preencher 4, saem 4 slides. No modo roteiro o app **não** inventa CTA nem hashtag que você não escreveu — o texto é seu.

### Casting: hook com pessoa, resto com cenário

O problema: uma busca por `"rotina matinal"` devolve xícara, caderno e janela na primeira página — quase nunca o retrato que um hook precisa. Ranquear melhor não resolve, porque a foto de pessoa simplesmente não está no resultado.

A solução tem três camadas, cada uma cobrindo a falha da anterior:

| Camada | Sinal | Vale quando |
| --- | --- | --- |
| **1. Busca em dois pools** | A query roda duas vezes: `"<tema> woman portrait lifestyle aesthetic"` e `"<tema> aesthetic lifestyle travel food"`. Cada foto lembra de qual pool veio. | Sempre — é o que garante que existe foto de pessoa no conjunto. |
| **2. Metadado** | Palavras no título/descrição (`woman`, `girl`, `portrait`, `mulher`…). O Unsplash descreve as fotos como "a woman sitting on a bed". | Sem VLM configurado. |
| **3. Visão** | O VLM olha a foto e classifica o assunto. Vence as outras duas: a busca de retrato às vezes devolve paisagem, e o metadado às vezes está vazio. | `VISION_ENABLED=true`. |

O resultado é gravado como `image_id` em cada slide — o mesmo campo que a galeria da prévia edita. Ou seja: o casting é um **palpite inicial**, não uma trava. Discordou? Troque a foto na prévia com um clique.

Se nenhuma foto de pessoa aparecer em nenhuma das camadas, o slide de hook fica com a foto melhor ranqueada e um aviso amarelo aparece na prévia — o app diz o que não conseguiu em vez de fingir que deu certo.

---

## 🎯 O que mudou na v0.6

- ✅ **Uma caixa por linha, do tamanho da linha** — a caixa passou a ser desenhada por *bloco*: uma frase de três linhas virava um retângulo com a largura da linha mais longa, e as linhas curtas ficavam com um vão branco de cada lado. O photo post de referência faz o contrário — **cada linha tem a sua etiqueta**, e a borda acompanha o comprimento daquela linha. O que fazia a versão anterior por linha parecer "serrilhada" não era a ideia, era a geometria: as caixas ficavam separadas. Medido no original, o passo entre linhas (**1.196×** o corpo) é *menor* que a altura de uma caixa (**1.48×**), então as etiquetas se **sobrepõem** ~0.29× e a pilha lê como uma mancha branca contínua. Números todos tirados da referência: folga horizontal 0.45× de cada lado, raio 0.22×.
- ✅ **A linha só quebra perto da margem** — a largura útil subiu de 80% para 88% do canvas, e o teto fixo de linhas por caixa (`4/6/2`) saiu. Ele encolhia a fonte com o slide ainda vazio; o texto agora corre até perto da margem da foto e simplesmente ganha mais uma linha, crescendo para baixo. A fonte só cai quando os blocos somados passariam de 84% da altura do slide — que é o comportamento do editor do TikTok, onde o reajuste é do tamanho da fonte, não do número de caixas.
- 🐛 **Arrastar a caixa reescrevia a quebra do texto** — no CSS a caixa era `width: fit-content` e, ao ser arrastada, virava `position: absolute`. Para um elemento absoluto, `fit-content` mede o espaço **da borda esquerda até o fim do contêiner**: quanto mais à direita a caixa ia, menos largura tinha para calcular, então o texto reencaixava em mais linhas — estreitava na horizontal e crescia na vertical durante o arraste, como se a fonte tivesse mudado. Agora a largura de referência é fixa (`width: max-content` com o mesmo teto de 88%), então mover não reflui o texto. `left`/`top` continuam sendo os únicos valores que o arraste grava.
- 🐛 **`Vision não devolveu JSON utilizável` com HTTP 200** — quatro causas somadas, todas silenciosas. (1) O `max_tokens` era fixo em 900 e a resposta de 8 imagens não cabia: o JSON chegava cortado no meio de um item e o parser descartava o documento inteiro, inclusive as avaliações completas. Agora o orçamento é por imagem e os objetos balanceados são recuperados de uma resposta truncada. (2) Os modelos de raciocínio da ModelScope devolvem o texto em `reasoning_content` e deixam `content` vazio — o parser olhava só para `content`. (3) O aviso não dizia o que tinha voltado; agora loga `finish_reason` e o começo da resposta, e aponta a variante Thinking quando o corte foi por tokens. (4) **Aumentar o orçamento não resolvia sozinho**: numa variante Thinking o raciocínio gasta tudo antes de o JSON começar (`finish_reason=length` com 8.605 caracteres de "The user wants me to evaluate 8 images…"). A chamada agora manda `chat_template_kwargs: {"enable_thinking": false}` — o parâmetro do vLLM, que é o servidor por trás da ModelScope API-Inference. Gateway que não conhece o campo devolve `400` na hora e a chamada é repetida sem ele, então quem já funcionava não quebra.
- ✅ **Cada caixa de texto anda sozinha** — antes o arraste movia headline, corpo e CTA juntos, como um bloco só, e não dava para pôr a pergunta no topo da foto e a resposta embaixo (o layout dos photo posts nativos). Agora cada caixa arrasta separada e grava seu próprio centro (`box_positions`). Uma caixa parada continua no empilhamento do papel; duplo clique devolve qualquer uma delas ao padrão.
- ✅ **Um tamanho de fonte só, para todos os tipos** — headline, corpo e CTA saíam de bases diferentes (68/54/52) e encolhiam cada um por conta própria, então o mesmo texto mudava de tamanho conforme o campo em que fosse colado. Agora todas as caixas partem do mesmo corpo e, se o texto não couber, **todas** reduzem juntas.
- ✅ **Resize por caixa no editor** — um controle por caixa na prévia (50%–250%), que multiplica o tamanho comum e vai junto para o PNG exportado.
- ✅ **Caixas coladas no texto** — a caixa branca era dimensionada pela métrica da fonte (`ascent + descent`), que embute ~35% de espaço morto: sobrava borda em cima e embaixo e o resultado parecia um bloco, não a etiqueta do TikTok. Agora a caixa é medida pela mancha de tinta real do texto. Na prévia, o mesmo bug tinha outra causa: `display:inline` dentro de um flex container é ignorado (o filho é blocado e ocupa a largura toda), então cada caixa ganhou seu próprio contêiner `width: fit-content`.
- 🐛 **Visão cancelada em 20s mesmo com 60 no blueprint** — a visão dividia o `REQUEST_TIMEOUT_SECONDS` com a busca de imagens. Os 20s do log eram o *default do código*, não o valor do painel: a variável não chegava à aplicação, e mesmo chegando o número certo para o Unsplash é curto demais para um VLM. Agora a visão tem `VISION_TIMEOUT_SECONDS` (default `90`) e o gunicorn roda com `--timeout 180`, senão o worker morria antes do fallback.

## 🎯 O que mudou na v0.5

- ✅ **Reposicionamento do texto** — no estilo `sticker`, arraste o texto sobre a foto na prévia. A posição é gravada como fração do canvas (o centro da caixa) e o PNG exportado sai igual à prévia. Duplo clique volta à âncora do papel no roteiro.
- ✅ **Qualificação de imagem por visão (opcional)** — com `VISION_ENABLED=true`, um VLM olha as fotos e devolve nota de relevância **e** a região limpa para o texto, que vira `pos_x`/`pos_y` automaticamente. Funciona em qualquer endpoint OpenAI-compatible com `image_url` (ex.: ModelScope API-Inference, que tem tier gratuito). Desligado por padrão; qualquer falha cai no ranking textual.
- 🐛 **Unsplash repetia as mesmas fotos** — `/search/photos` ordena por relevância de forma estável, então a mesma query devolvia sempre a página 1. Parecia cache do app; era determinismo da API. Agora a página é sorteada dentro das 5 primeiras a cada busca, com reentrada quando a query tem acervo curto.

### Como as imagens são qualificadas — dois modos

**Padrão (`RANKING_ENABLED`) — só texto.** O LLM recebe título/descrição de cada foto mais o `raw_text` e devolve uma ordem. Nenhum pixel sai daqui. Consequência: quando o `alt_description` do Unsplash vem vazio ou genérico, o ranking julga quase no escuro. Qwen, Llama ou GPT nesse papel trabalham só com metadado.

**Opcional (`VISION_ENABLED`) — o modelo olha a foto.** Um VLM recebe as imagens e devolve três coisas:

1. **Nota de relevância** olhando a imagem — penaliza foto com texto/logo embutido, muito escura ou poluída no centro, coisas que o metadado nunca revela.
2. **Onde o texto cabe.** O estilo sticker desenha caixas brancas por cima da foto. Sem visão, a posição vem da âncora do papel no roteiro e às vezes cai em cima do rosto. O modelo escolhe uma zona limpa (`top`, `bottom-left`, …) e ela vira `pos_x`/`pos_y` no slide — o mesmo campo que o arraste na prévia grava, então você continua corrigindo por cima.
3. **O assunto da foto** (`woman`, `man`, `person`, `scene`) — é o sinal mais forte do [casting](#casting-hook-com-pessoa-resto-com-cenário), que decide qual foto abre o carrossel. Uma leitura da foto de banco, não identificação de indivíduo: serve só para saber se há alguém em cena.

Pedir uma **zona nomeada** em vez de coordenadas cruas é o que torna a saída estável: VLM erra número solto, mas acerta "topo/meio/base".

Precisa de um endpoint OpenAI-compatible que aceite `image_url`. O **ModelScope API-Inference** serve e tem tier gratuito (~2.000 chamadas/dia, exige conta vinculada à Alibaba Cloud):

```bash
VISION_ENABLED=true
VISION_API_BASE_URL=https://api-inference.modelscope.cn/v1
VISION_API_KEY=ms-xxxxxxxx
VISION_MODEL=Qwen/Qwen3-VL-235B-A22B-Instruct   # ou PaddlePaddle/ERNIE-4.5-VL-28B-A3B-Paddle
```

O ID é **namespaced por organização** no ModelScope. Sem o prefixo, a resposta é 404 e a aplicação cai no ranking textual sem quebrar — confira em `/health` → `vision_diagnostic`.

Dois cuidados de projeto: as fotos vão na versão **pequena** (~400px, `urls.small`) porque 400px basta para julgar composição e a versão cheia multiplicaria os tokens de visão; e no máximo **8 imagens por chamada**, já que a chamada é síncrona dentro do `POST /generate`. Timeout, JSON ilegível, `image_id` alucinado ou visão desligada — qualquer um desses cai no ranking textual de sempre.

A visão tem **timeout próprio** (`VISION_TIMEOUT_SECONDS`, default `90`), separado do `REQUEST_TIMEOUT_SECONDS` da busca de imagens. Enquanto os dois eram o mesmo número, o valor dimensionado para o Unsplash (20s) cancelava o VLM antes da primeira resposta — o log dizia `não respondeu em 20s` e o carrossel caía no ranking textual sem nada estar configurado errado. Dois timeouts porque as duas chamadas não têm nada a ver uma com a outra: uma é um GET de JSON, a outra é um modelo olhando 8 fotos. O worker do gunicorn roda com `--timeout 180`, que precisa ficar acima do timeout da visão para o fallback ter chance de acontecer — worker morto não faz fallback.

#### Quando o log diz `Vision não devolveu JSON utilizável`

HTTP 200 e nenhum veredicto significa que a chamada funcionou e a **resposta** é que não serviu. O aviso agora carrega o `finish_reason` e o começo do que voltou, que é o suficiente para separar os três casos:

| No log | O que aconteceu | O que fazer |
|--------|-----------------|-------------|
| `finish_reason=length` | A resposta foi cortada no limite de tokens. Numa variante **Thinking** o raciocínio consome o orçamento inteiro e o JSON nem começa. | O pedido já manda `enable_thinking: false`; se o log insistir, o provider ignorou o parâmetro — trocar `VISION_MODEL` pela variante **Instruct**. Se a resposta chegou parcial, os itens completos já são aproveitados sozinhos. |
| `finish_reason=stop` + prosa | O modelo respondeu em texto ("Claro! A primeira foto…") em vez de JSON. | Um VLM mais fraco no seguimento de instrução — trocar de modelo. |
| `(resposta vazia)` | Nem `content` nem `reasoning_content` vieram preenchidos. | Verificar cota/limite do provider. |

O orçamento de tokens é calculado por imagem (`700 + 220 × nº de imagens`), não fixo: um veredicto ocupa ~60 tokens e as 8 imagens da chamada não cabiam nos 900 que havia antes. Uma resposta truncada ainda é aproveitada — cada objeto `{...}` completo é lido isoladamente, então perder o último item não custa os outros sete.

Orçamento maior, porém, não salva um modelo de raciocínio: o pensamento cresce junto e continua estourando o teto. Por isso o pedido carrega `chat_template_kwargs: {"enable_thinking": false}`, a forma [documentada pelo vLLM](https://docs.vllm.ai/en/stable/features/reasoning_outputs) de desligar o modo Thinking na série Qwen3 — e o vLLM é o servidor por trás da ModelScope API-Inference. Um gateway que não aceite o campo responde `400` imediatamente, e aí a chamada é refeita sem ele: o custo do experimento é um round-trip que falha rápido, não o timeout de 90s.

Modelos **text-to-image** (Qwen-Image, FLUX, Stable Diffusion) são outra categoria: eles *geram* a foto em vez de qualificar, e substituiriam o Unsplash. Não estão implementados.

---

## 🎯 O que mudou na v0.4

- ✅ **Estilo `sticker` (padrão)** — texto preto em caixas brancas arredondadas, uma por linha, sobre a foto sem escurecer. É o formato de legenda nativo dos photo posts do TikTok.
- ✅ **TikTok Sans empacotada** — `static/fonts/sticker-{bold,regular}.ttf` (SemiBold/Medium), a tipografia oficial do TikTok. Sem isso o servidor caía na Liberation Sans, e a tipografia era o que ainda destoava do visual dos photo posts.
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
- Formulário com **um campo de roteiro por imagem** (rotulado pelo papel do slide) ou textarea única, mais tema, estilo, nº de slides, idioma e keywords.
- Botão "distribuir" que divide um roteiro colado entre os campos, entendendo `Imagem N:`, `2.`, `---` e parágrafos.
- **Casting por papel**: imagem 1 sempre com pessoa (hook), demais com cenário — via busca separada, metadado da foto e visão.
- Composição de carrossel via TextComposer (mock determinístico ou LLM); no modo por imagem, sem LLM no caminho do texto.
- Ordenação no roteiro viral de 3 atos (`hook → problema → agitação → valor → prova → CTA`).
- Renderização estilo sticker do TikTok — caixas brancas arredondadas com texto preto.
- Busca de imagens via API oficial do Pinterest (com fallback mock).
- Ranking opcional de imagens por endpoint LLM (com fallback determinístico).
- Qualificação por **visão** opcional (VLM): nota olhando a foto + posição automática do texto + assunto da foto (pessoa/cenário) para o casting.
- Prévia do carrossel com slides editáveis (headline, body, CTA por slide) e o papel de cada slide visível.
- Reposicionamento e tamanho de **cada caixa de texto** por arraste/controle na prévia (estilo `sticker`), refletidos no PNG exportado.
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
3. No ViralPost Studio (`http://localhost:5000/create`), escolha o nº de slides (3/6/9/12) e como entregar o texto:
   - **Roteiro por imagem** (padrão) — um campo por foto, rotulado com o papel do slide: *Imagem 1 (hook)*, *Imagem 2 (problema)*, e assim por diante. A primeira linha de cada campo vira o texto grande; o resto vira o apoio. Nada de LLM no meio: o que você escreve é o que sai.
   - **Distribuir de uma vez** — dentro do modo por imagem, abra "Colar o roteiro inteiro e distribuir", cole tudo e clique no botão. O servidor divide por `Imagem N:`, `2.`, `---` ou parágrafos e preenche os campos, que continuam editáveis.
   - **Texto corrido** — cole tudo numa caixa só e deixe o LLM estruturar, como antes.
4. Preencha tema, estilo (**sticker** recomendado — ou quote/list/tutorial/story) e as palavras-chave da busca de imagens.
5. Clique em "Gerar carrossel". Com o casting ligado, a imagem 1 recebe uma foto com pessoa e as demais recebem cenário.
6. Na prévia, cada slide mostra seu papel e de onde veio a foto do hook (visão, metadado ou busca). Edite os textos e troque a imagem pela galeria.
7. No estilo `sticker`, **arraste cada caixa** sobre a foto para reposicionar (duplo clique volta ao padrão) e use o controle de tamanho de cada caixa se quiser texto maior. Clique em "Salvar edições" para gravar.
8. Exporte: **ZIP** (carrossel completo) ou **PNG** (slide único) ou **Markdown** (texto).

---

## ⚙️ Variáveis de ambiente

| Variável | Default | Descrição |
|----------|---------|-----------|
| `FLASK_ENV` | `development` | Ambiente Flask |
| `SECRET_KEY` | `dev-insecure-change-me` | **Definir em produção** |
| `DEBUG` | `true` | Modo debug |
| `PINTEREST_ACCESS_TOKEN` | (vazio) | Token da API oficial v5. Vazio → tenta Unsplash |
| `PINTEREST_API_BASE_URL` | `https://api.pinterest.com/v5` | Base URL da API |
| `UNSPLASH_ACCESS_KEY` | (vazio) | Access Key do Unsplash. Usada quando não há token Pinterest. Vazio → mock |
| `LLM_PROVIDER` | `mock` | `mock` ou `openai_compatible` |
| `LLM_API_BASE_URL` | (vazio) | Endpoint OpenAI-compatible (ex.: `https://api.groq.com/openai/v1`) |
| `LLM_API_KEY` | (vazio) | Token do LLM (ex.: `gsk_...` para Groq) |
| `LLM_MODEL` | (vazio) | Nome do modelo. Ex.: `qwen/qwen3.6-27b`, `llama-3.3-70b-versatile`, `gpt-4o-mini` |
| `RANKING_ENABLED` | `true` | Liga/desliga ranking de imagens (reusa LLM) |
| `HOOK_SUBJECT` | `woman` | Casting da imagem 1: `woman`, `person` ou `off` (desliga o casting) |
| `HOOK_QUERY_HINTS` | (auto) | Termos da busca de retrato. Vazio → `<HOOK_SUBJECT> portrait lifestyle aesthetic` |
| `SCENE_QUERY_HINTS` | `aesthetic lifestyle travel food` | Termos da busca das imagens secundárias |
| `VISION_ENABLED` | `false` | Ranking **olhando** a foto + posição automática do texto |
| `VISION_API_BASE_URL` | (herda `LLM_*`) | Endpoint OpenAI-compatible com suporte a `image_url` |
| `VISION_API_KEY` | (herda `LLM_*`) | Token do provider de visão |
| `VISION_MODEL` | (vazio) | ID do VLM. **Sem default** — ex.: `Qwen/Qwen3-VL-235B-A22B-Instruct` |
| `REQUEST_TIMEOUT_SECONDS` | `20` | Timeout HTTP da busca de imagens e do LLM de texto |
| `VISION_TIMEOUT_SECONDS` | `90` | Timeout só do VLM — separado porque o modelo olha até 8 fotos por chamada |
| `SESSION_TTL_MINUTES` | `60` | TTL dos projetos em memória |
| `SLIDE_WIDTH` | `1080` | Largura do slide PNG |
| `SLIDE_HEIGHT` | `1350` | Altura do slide PNG (4:5 = TikTok/Instagram) |
| `SLIDE_FONT_BOLD` | (auto) | Caminho para um `.ttf` bold. Vazio → detecção automática |
| `SLIDE_FONT_REGULAR` | (auto) | Caminho para um `.ttf` regular. Vazio → detecção automática |

**Compatibilidade reversa:** variáveis `RANKING_*` antigas (`RANKING_PROVIDER`, `RANKING_API_BASE_URL`, `RANKING_API_KEY`, `RANKING_MODEL`) ainda funcionam e mapeiam para `LLM_*`.

Nenhum valor secreto é commitado. Tokens nunca cruzam para o frontend.

### De onde vêm as imagens

A prioridade é `PINTEREST_ACCESS_TOKEN` → `UNSPLASH_ACCESS_KEY` → **mock** (gradientes SVG sintéticos). Se as duas chaves estiverem vazias, o carrossel sai com gradientes coloridos em vez de fotos.

O `/search/pins/` do Pinterest exige **Standard Access** (aprovação manual da Pinterest). O Unsplash não exige aprovação — crie um app em [unsplash.com/oauth/applications](https://unsplash.com/oauth/applications) e copie a **Access Key**.

**Por que a mesma query devolve fotos diferentes agora:** o `/search/photos` do Unsplash ordena por relevância e essa ordem é estável — a página 1 de "café da manhã" é sempre a mesma. Não havia cache no app; era determinismo da API. Cada busca agora sorteia uma página entre 1 e 5 (`UnsplashClient._PAGE_WINDOW`), o que renova o resultado sem cair em fotos irrelevantes. A página escolhida aparece no log `INFO`. Se a query tem acervo curto e a página sorteada vem vazia, a busca reentra dentro do `total_pages` em vez de cair no gradiente mock.

Para confirmar o que está ativo:

```bash
curl -s http://localhost:5000/health | python -m json.tool
# providers.images        → "pinterest_v5" | "unsplash" | "mock"
# providers.casting       → "woman" | "person" | "off"
# providers.vision        → "configured" | "off"
# images_diagnostic.using_mock → true quando o carrossel sai com gradiente
# vision_diagnostic.vision_model_value → o id do VLM, causa comum de 404
```

> O `.env` é lido pelo `python-dotenv` no app factory, então `python run.py` e `docker compose up` enxergam as mesmas variáveis. Variáveis reais do ambiente (Render, docker-compose) têm prioridade sobre o arquivo.

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
│   │   ├── script_parser.py    # Roteiro por imagem — blocos → slides (sem LLM)
│   │   ├── pinterest_client.py # Pinterest v5 + Unsplash + Mock
│   │   ├── ranking_provider.py # Inference (LLM) + Mock
│   │   └── vision_provider.py  # VLM — nota + posição do texto + assunto da foto
│   ├── services/
│   │   ├── generation.py      # Orquestração do carrossel
│   │   ├── casting.py         # Qual foto em qual slide (hook = pessoa)
│   │   ├── session_store.py   # Persistência leve (TTL)
│   │   └── slide_renderer.py  # Pillow — overlay de texto em imagem
│   └── routes/
│       ├── main.py            # /
│       ├── create.py          # /create, /script/split
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

Cobertura (234 testes):
- **TextComposer** — split em slides, hashtags, texto curto, texto vazio.
- **Roteiro por imagem** — primeira linha vira headline e o resto o body, rótulos `Imagem N:` removidos, campo vazio herda o papel, blocos além do nº de slides descartados, hashtags e CTA preservados.
- **Distribuição do roteiro colado** — separadores `Imagem N:`, `2.`, `---` e parágrafo; teto no nº de slides com o total encontrado reportado; texto vazio e contagem inválida.
- **Casting** — hook recebe pessoa por visão, por metadado (`alt_description`) e por pool de busca, nessa ordem; parte do corpo ("woman's hands") não conta como retrato; fotos de cenário nunca caem no slide 1; aviso quando não há foto com pessoa; `HOOK_SUBJECT=off` volta à rotação.
- **Roteiro viral** — distribuição de papéis por nº de slides, ordem `hook…cta`, CTA só no fecho, sem texto duplicado entre headline e body.
- **SlideRenderer** — resolução de fonte TrueType, auto-ajuste do corpo da fonte, caixas brancas do estilo sticker, ausência de overlay escuro, posição do hook vs. valor, quebra de palavra longa, remoção de emoji.
- **Uma caixa por linha** — cada linha do bloco ganha uma caixa com a largura da própria linha (linha curta não herda a largura da longa); as caixas se sobrepõem para a pilha sair contínua, sem vão entre elas; headline e corpo continuam sendo dois blocos separados; a altura da caixa não muda por a linha ter ou não descendente.
- **Quebra de linha por altura** — a fonte só encolhe quando os blocos passariam da altura útil do slide (não por contar linhas), e nenhuma palavra é descartada quando o texto cresce.
- **Tamanho uniforme** — headline, corpo e CTA saem no mesmo corpo de fonte; texto longo encolhe as três caixas juntas, nunca uma só.
- **Caixa colada no texto** — a geometria bate com a do photo post de referência (passo entre linhas menor que a caixa, folga lateral proporcional ao corpo da fonte), e o `box_scale` aumenta a caixa junto com a fonte.
- **Reposicionamento** — `pos_x`/`pos_y` vencem a âncora do papel, clamp dentro do canvas, slide sem posição mantém o comportamento antigo, e cada caixa (`box_positions`) move-se sem arrastar as outras.
- **Pinterest mock** — geração de SVGs sintéticos.
- **Unsplash** — rotação de páginas entre buscas iguais, reentrada quando a página sorteada passa do fim do acervo, motivo do fallback por status HTTP.
- **Ranking** — correlação com `raw_text`, fallback sem corpus.
- **Visão (VLM)** — envia a thumb e não a foto cheia, teto de imagens por chamada equilibrado entre os dois pools, orçamento de tokens que cresce com o nº de imagens, `enable_thinking: false` no pedido e repetição sem o campo quando o gateway devolve 400, parse de âncora → `pos_*` e de `subject` (com sinônimos: `female`/`girl` → `woman`), `<think>`/cerca markdown na resposta, JSON vindo em `reasoning_content` com `content` vazio, `content` devolvido como lista de partes, recuperação dos veredictos inteiros de uma resposta cortada no limite de tokens (inclusive com `}` dentro de string), nota fora de faixa, `image_id` alucinado ou duplicado, gradiente mock sem chamada, timeout e 404 caindo no ranking textual, e resposta inútil registrada no log com `finish_reason` e o conteúdo.
- **Busca em dois pools** — uma query por papel, cada foto marcada com sua origem, fotos repetidas entre os pools deduplicadas, falha de uma busca não derruba a geração.
- **Settings** — mock vs LLM configurado, compatibilidade reversa, visão desligada por default e herança das credenciais `LLM_*`, `HOOK_*`/`SCENE_QUERY_HINTS` customizáveis.
- **Forms** — validação de `raw_text` (mín 20 chars) só no modo automático, mínimo de 2 blocos no modo roteiro, `theme`, `style`, `slides_count`, parse de `text_positions`, `box_positions` e `box_scales` (inclui valores inválidos e escalas fora dos limites), POST legado sem o campo de modo continua válido.
- **Visão** — timeout próprio (não o HTTP da busca de imagens), default com folga acima dele, e fallback silencioso em timeout/404/JSON ilegível.
- **Rotas** — fluxo completo (`/` → `/create` → `/generate` → `/preview` → `/edit` → `/export` ZIP/PNG/MD), round-trip da posição arrastada até o PNG, ordem dos blocos preservada da submissão à prévia, e `POST /script/split`.

---

## 🔌 Endpoints

| Método | Rota | Descrição |
|--------|------|-----------|
| GET | `/` | Landing page + status |
| GET | `/create` | Formulário de briefing (roteiro por imagem ou texto corrido) |
| POST | `/script/split` | Divide um roteiro colado em blocos por imagem (JSON) |
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
| `sticker` | **(padrão)** Uma caixa branca arredondada por **linha**, do tamanho daquela linha, texto preto, foto sem escurecimento. As caixas se sobrepõem e a pilha lê como uma mancha contínua. O texto corre até perto da margem antes de quebrar. Um tamanho de fonte só para headline/corpo/CTA; cada bloco arrasta e redimensiona sozinho na prévia | Photo post nativo do TikTok |
| `quote` | Aspas decorativas + headline centralizada + body + CTA inferior | Frases inspiradoras, quotes |
| `list` | Headline à esquerda com barra de destaque + bullets + CTA centralizado | Listas de dicas, passos numerados |
| `tutorial` | Tag "PASSO A PASSO" + headline + body + CTA em caixa colorida | Tutoriais, como-fazer |
| `story` | Tag "HISTÓRIA" + headline grande + body centralizado + CTA | Narrativas, storytelling |

**Dimensões:** 1080×1350px (4:5) — formato ideal para TikTok photo posts e Instagram Reels cover.

### Tipografia

O projeto **empacota TikTok Sans** em `static/fonts/` — a tipografia oficial do TikTok:

| Arquivo | Corte | Usado em |
|---------|-------|----------|
| `static/fonts/sticker-bold.ttf` | TikTok Sans **SemiBold** (wght 600) | headline e CTA |
| `static/fonts/sticker-regular.ttf` | TikTok Sans **Medium** (wght 500) | corpo do texto |

SemiBold/Medium em vez de Bold/Regular porque o texto nativo do TikTok é de peso médio — Bold fica pesado demais dentro da caixa branca e Regular fica fino demais sobre a foto.

O Google Fonts publica TikTok Sans **apenas como fonte variável**, com default **Light 300**. Os arquivos aqui são instâncias estáticas geradas com `fontTools` — soltar o `.ttf` variável cru renderizaria os slides finos demais, sem erro nenhum. O processo está documentado em [static/fonts/README.md](static/fonts/README.md).

A detecção segue esta ordem: `static/fonts/` → Liberation/DejaVu (Linux) → Segoe UI/Arial (Windows) → Arial (macOS). Ou seja, os arquivos empacotados vencem as fontes do sistema em qualquer ambiente — o render fica igual no Docker e no dev local.

Para trocar a tipografia, substitua esses dois `.ttf` (estáticos) ou aponte `SLIDE_FONT_BOLD` / `SLIDE_FONT_REGULAR` para outros caminhos.

> TikTok Sans é distribuída sob SIL Open Font License 1.1 (`static/fonts/OFL.txt`), copyright 2024 TikTok Inc.

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
- [x] Roteiro pode ser escrito imagem por imagem, com um campo por foto do carrossel.
- [x] Roteiro colado inteiro é distribuído entre os campos e continua editável.
- [x] Primeira foto recebe pessoa; as demais, cenário — com aviso quando não dá.
- [x] Prévia é editável (headline + body + CTA por slide).
- [x] Posição e tamanho de cada caixa são ajustáveis na prévia e o PNG exportado respeita o ajuste.
- [x] Usuário consegue copiar legenda/hashtags e baixar conteúdo.
- [x] Origem da imagem aparece na interface e no Markdown exportado.
- [x] Nenhum segredo aparece no frontend, logs ou repositório.
- [x] Testes unitários para validação, adapters e fallback.
- [x] README com instalação, configuração e execução.
- [x] Não há scraping nem automação de login não autorizada.

---

## 🛣️ Próximos passos

1. Configurar `VISION_API_KEY` + `VISION_MODEL` na ModelScope (Qwen-VL) para o casting decidir por visão em vez de busca/metadado. É a única peça pendente das features desta versão — o resto já funciona sem chave.
2. Configurar `LLM_API_BASE_URL` e `LLM_API_KEY` (ex.: Groq) para ativar o roteiro viral com LLM real. Modelos Groq suportados: `qwen/qwen3.6-27b`, `llama-3.3-70b-versatile`, `llama-3.1-8b-instant`, `mixtral-8x7b-32768`, `gemma2-9b-it` (consulte https://console.groq.com/docs/models para a lista atual).
3. Validar escopos do token Pinterest para a busca de Pins.
4. Adicionar mais estilos visuais (antes-e-depois, capa de carrossel, etc.).
4. Persistência real (DB ou Redis) para multi-worker.
5. Mover a chamada de visão para fora do `POST /generate` (fila ou refinamento sob demanda na prévia), tirando a latência do VLM do caminho da primeira renderização.

---

## 📄 Licença

Uso interno. Componentes externos sujeitos aos seus próprios termos (Pinterest API ToS, goviral.ai, modelo de LLM escolhido).
