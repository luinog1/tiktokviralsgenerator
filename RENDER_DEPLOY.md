# Deploy no Render — Troubleshooting

## Erro observado

```
#1 [internal] load build definition from Dockerfile
#1 transferring dockerfile: 2B done
error: failed to solve: failed to read dockerfile: open Dockerfile: no such file or directory
```

**Significado:** o Render não encontrou o `Dockerfile` no build context. "2B done" = 2 bytes = essencialmente nada foi transferido. O arquivo **não está** onde o Render está procurando.

---

## Passo 1 — Verificar no GitHub se o Dockerfile foi commitado

Abra: https://github.com/luinog1/tiktokviralsgenerator

Você deve ver o `Dockerfile` **listado na raiz do repo** (não dentro de nenhuma pasta). Se não estiver lá:

```bash
# No seu computador, dentro da pasta do projeto:
git status
git ls-files | grep -i dockerfile
# Se não retornar nada, o Dockerfile NÃO foi commitado
```

### Corrigir:

```bash
cd /caminho/do/seu/repo
git add Dockerfile docker-compose.yml render.yaml
git add app/ tests/ templates/ static/
git add requirements.txt requirements-dev.txt .env.example
git add .dockerignore .gitignore README.md run.py
git commit -m "Adiciona Dockerfile e render.yaml para deploy"
git push origin main
```

---

## Passo 2 — Verificar se há subpasta envolvendo o projeto

Se no GitHub você vê algo como:

```
tiktokviralsgenerator/
└── viralpost-studio/      ← subpasta!
    ├── Dockerfile
    ├── app/
    └── ...
```

O Render não vai achar o Dockerfile na raiz. **Solução:**

### Opção A — Reescrever o git history (recomendado)

```bash
cd /caminho/do/seu/repo
# Mover tudo da subpasta para a raiz
git mv viralpost-studio/* .
git mv viralpost-studio/.* . 2>/dev/null || true
rmdir viralpost-studio
git commit -m "Move arquivos para a raiz do repo"
git push origin main --force
```

### Opção B — Usar `rootDir` no Render

1. No Render: entre no serviço → **Settings** → **Root Directory** → coloque `viralpost-studio` (ou o nome da subpasta)
2. Salve e faça manual deploy

---

## Passo 3 — Recriar o serviço no Render como Blueprint

Com o `render.yaml` já commitado na raiz do repo:

1. No dashboard do Render: **New +** → **Blueprint**
2. Selecione o repo `luinog1/tiktokviralsgenerator`
3. O Render vai detectar o `render.yaml` e criar o serviço automaticamente
4. Branch: `main`
5. Clique em **Apply**

O `render.yaml` já configura:
- Runtime: Docker
- Health check: `/health`
- Variáveis de ambiente com `SECRET_KEY` gerada automaticamente
- Variáveis sensíveis (`UNSPLASH_ACCESS_KEY`, `LLM_API_KEY`, `APIFY_TOKEN`) marcadas como `sync: false` para você preencher no painel

---

## Passo 4 — Configurar variáveis de ambiente no Render

Depois do primeiro deploy, no painel do serviço → **Environment**:

| Variável | Valor |
|----------|-------|
| `IMAGE_PROVIDER` | `auto` (só Unsplash), `pinterest_scrape` (sem token) ou `instagram_pinterest` |
| `UNSPLASH_ACCESS_KEY` | (Access Key do Unsplash — com `auto` e sem ela, o carrossel sai com gradientes) |
| `APIFY_TOKEN` | Token da Apify para buscar Instagram por `@perfil` ou hashtag |
| `APIFY_ACTOR` | `apify~instagram-scraper` (default já declarado no Blueprint) |
| `LLM_PROVIDER` | `mock` (default) ou `openai_compatible` |
| `LLM_API_BASE_URL` | `https://api.groq.com/openai/v1` (se for usar Groq) |
| `LLM_API_KEY` | `gsk_xxx...` |
| `LLM_MODEL` | `llama-3.1-8b-instant` |

Salve → **Manual Deploy** → **Deploy latest commit**.

### Instagram + Pinterest com quantidade controlada

Não existe uma variável nova para a quantidade: ela é escolhida em cada geração
nos formulários `/goviral` e `/create`. Selecione **Instagram + Pinterest** e
use **Fotos do Instagram no modo combinado**. O padrão `1 foto` busca o hook no
Instagram e deixa os outros slides para o Pinterest, guiado por tema e
palavras-chave.

Para um perfil específico, escreva `@usuario` no tema ou nas palavras-chave. O
handle é enviado à Apify, mas removido da query do Pinterest. A Apify recebe a
cota escolhida em `resultsLimit`, `maxItems` e `limit`; portanto, escolher uma
foto não dispara mais o pool mínimo antigo de 12 itens pagos. O mesmo dataset é
reutilizado entre hook e cenário, evitando dois runs iguais para o mesmo perfil.

### Cotas de pessoas, comida e alta resolução

Não há variável nova no Render. Em cada geração, os formulários `/goviral` e
`/create` oferecem **Fotos com pessoas/modelos** e **Fotos de comida**. A cota
de pessoas inclui o hook; comida cobre refeições, smoothie, frutas e bebidas;
o restante usa cenário geral. O app separa as buscas, deduplica resultados e
intercala as categorias para reduzir repetição entre hashtags e palavras-chave.

Com `VISION_ENABLED=true`, o Qwen-VL configurado classifica cada candidata como
`woman`, `man`, `person`, `food` ou `scene`; essa leitura vence o texto e o pool
de origem. Sem visão, as cotas continuam funcionando por metadados e pelas
queries separadas, com menor precisão.

Pinterest e Instagram agora só aceitam fotos que cubram `SLIDE_WIDTH` ×
`SLIDE_HEIGHT` (1080×1350 por padrão). O piso não é relaxado: se a fonte só
trouxer arquivos menores, ela cai no fallback e o motivo aparece na prévia. O
Unsplash pede ao CDN a imagem já em 1080×1350, `fit=crop`, qualidade 85.

### Repetição entre gerações e alternativas por imagem

Também sem variável nova. A busca no Pinterest pede **120 pins por query** (a
biblioteca pagina sozinha; ~4,8s contra ~3,0s dos 40 anteriores) porque o piso
de resolução acima consome a maior parte deles. O piso agora mede a **ampliação
que o `cover` faria**, não a largura bruta: até 1,10× a foto passa, o que
recupera `1024×1536` e `1000×1500` — os dois tamanhos mais comuns do Pinterest,
que eram reprovados por 56px e não têm ampliação visível. Somados, os dois
levam o pool usável de 11 (com 40 pins e piso literal) para **71**. O sorteio é
uma amostra do pool inteiro, e cada imagem do carrossel oferece no mínimo **5
alternativas além da que já recebeu**.

**Se o carrossel sai com gradientes coloridos, é isto:** uma query longa demais
devolve zero resultados, e zero cai no mock — que é determinístico por query, ou
seja, a mesma hashtag passa a devolver os mesmos gradientes para sempre. Nos
logs procure por `retornou 0 imagens`. O app agora normaliza a query (tira `#` e
`@perfil`, remove termos repetidos) e a encurta em três degraus antes de
desistir; quando desiste, o motivo aparece na prévia. Ainda assim, **tema e
palavras-chave curtos rendem muito mais fotos** — `@perfil` só ajuda no
Instagram, e hashtag não é um termo que banco de imagens entenda.

O disco entra nisso: as fotos que já foram para os slides ficam em
`instance/recent_media.json` para a geração seguinte sorteá-las por último. No
Render, **o disco do serviço é efêmero** — sem um disco persistente montado, um
redeploy zera essa memória. Nada quebra quando isso acontece: o pool fundo e o
sorteio continuam valendo, só a camada de memória recomeça do zero. É o mesmo
diretório da pessoa fixada (`pinned_person.json`), então quem já monta disco
para ela cobre os dois.

Depois do deploy, confirme em `/health`:

```json
"images_diagnostic": {"apify_token_set": true}
```

### Geração automática de hooks e scripts

O serviço não precisa acessar `content.goviralai.app` nem receber cookies do
Discord. Em `/goviral`, preencha o briefing, o público, o idioma e o número de
imagens e clique em **Gerar hook e scripts**. O endpoint LLM configurado acima
devolve o painel estruturado, que permanece editável antes de **Gerar
carrossel**. O painel antigo do goviral.ai é apenas uma opção de importação.

Se o botão responder `LLM nao configurado`, confira as quatro variáveis da
tabela e confirme em `/health`:

```json
"providers": {"content_generation": "llm"}
```

Com `LLM_PROVIDER=mock`, a renderização e os testes locais continuam
funcionando, mas a geração automática informa que precisa de um endpoint real.

### Visão (ModelScope) — opcional

O `render.yaml` já declara as quatro variáveis como `sync: false`, então elas
aparecem no painel esperando valor. Nada de código muda: é só preencher.

| Variável | Valor |
|----------|-------|
| `VISION_ENABLED` | `true` |
| `VISION_API_BASE_URL` | `https://api-inference.modelscope.cn/v1` |
| `VISION_API_KEY` | `ms-xxxxxxxx` |
| `VISION_MODEL` | `Qwen/Qwen3-VL-235B-A22B-Instruct` |

A visão tem timeout PRÓPRIO, o `VISION_TIMEOUT_SECONDS` (default `90`) — o VLM
olha até 8 fotos por chamada e é lento demais para o `REQUEST_TIMEOUT_SECONDS`,
que existe para a busca de imagens. Enquanto os dois eram o mesmo número, o
valor que servia ao Unsplash cancelava a visão antes da primeira resposta.
O worker do gunicorn está em `--timeout 180` (Dockerfile) e precisa continuar
maior que o timeout da visão, senão o worker morre antes do fallback.

**O ID do modelo precisa do prefixo da organização.** `Qwen3-VL-235B-A22B-Instruct`
dá 404; o certo é `Qwen/Qwen3-VL-235B-A22B-Instruct`. Como a visão cai
silenciosamente no ranking textual quando falha, o 404 não aparece na interface.

Confirme depois do deploy:

```bash
curl -s https://SEU-SERVICO.onrender.com/health | python -m json.tool
# providers.vision                     → "configured"  (se vier "off", falta variável)
# vision_diagnostic.vision_model_value → confira o prefixo "Qwen/"
```

Se `providers.vision` estiver `configured` mas as fotos não mudarem de
comportamento, veja os **Logs** do serviço. As mensagens dizem exatamente o que
falhou:

- `Vision endpoint HTTP 404: ...` → model id errado (falta o prefixo da org)
- `Vision endpoint HTTP 401` → chave inválida
- `Vision endpoint não respondeu em Ns` → suba `VISION_TIMEOUT_SECONDS` (e
  confira em `/health` se o valor do blueprint chegou de fato à aplicação: o
  número da mensagem é o que está em uso, não o que você escreveu no painel)
- `Vision respondeu, mas nenhum image_id bateu` → o modelo respondeu fora do
  formato pedido; vale trocar de modelo

> Sem essas variáveis o app **não quebra**: o casting (imagem 1 com pessoa)
> continua funcionando pelo metadado da foto e pela busca separada por papel.
> A visão só aumenta a precisão da escolha.

---

## Verificação final do Dockerfile

Confirme que o Dockerfile **no GitHub** tem exatamente este conteúdo (primeira linha):

```dockerfile
FROM python:3.11-slim AS base
ENV PYTHONUNBUFFERED=1 ...
```

Se estiver vazio, houve problema no commit. Re-add:
```bash
git add Dockerfile
git commit -m "Fix Dockerfile"
git push
```

---

## URLs esperadas pós-deploy

- App: `https://viralpost-studio.onrender.com/`
- Health: `https://viralpost-studio.onrender.com/health`

( troque `viralpost-studio` pelo nome do serviço que você criou )

---

## Logs úteis para depuração

No Render → **Logs** do serviço, você deve ver na primeira inicialização:

```
[INFO] Starting gunicorn 22.0.0
[INFO] Listening at: http://0.0.0.0:5000
[INFO] Booting worker with pid: ...
```

Se aparecer erro de `SECRET_KEY` ou CSRF, preencha as variáveis no painel Environment.
