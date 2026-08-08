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
- Variáveis sensíveis (`PINTEREST_ACCESS_TOKEN`, `LLM_API_KEY`) marcadas como `sync: false` para você preencher no painel

---

## Passo 4 — Configurar variáveis de ambiente no Render

Depois do primeiro deploy, no painel do serviço → **Environment**:

| Variável | Valor |
|----------|-------|
| `PINTEREST_ACCESS_TOKEN` | (seu token da API v5 do Pinterest) |
| `LLM_PROVIDER` | `mock` (default) ou `openai_compatible` |
| `LLM_API_BASE_URL` | `https://api.groq.com/openai/v1` (se for usar Groq) |
| `LLM_API_KEY` | `gsk_xxx...` |
| `LLM_MODEL` | `llama-3.1-8b-instant` |

Salve → **Manual Deploy** → **Deploy latest commit**.

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
