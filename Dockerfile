FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Dependências do sistema — Pillow precisa de libjpeg/zlib.
# fonts-liberation/fonts-dejavu são OBRIGATÓRIAS: a imagem slim não traz
# nenhuma fonte TrueType e o Pillow cairia na fonte bitmap padrão, que ignora
# o tamanho pedido e renderiza os slides com texto minúsculo.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libjpeg-dev \
    zlib1g-dev \
    libfreetype6-dev \
    liblcms2-dev \
    libwebp-dev \
    fonts-liberation \
    fonts-dejavu-core \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app/

# Usuário não-root
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

ENV FLASK_ENV=production \
    PORT=5000

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -fsS http://127.0.0.1:5000/health || exit 1

# --timeout: o default do gunicorn é 30s e mata o worker que passar disso. O
# POST /generate é síncrono e carrega a chamada de visão dentro dele
# (VISION_TIMEOUT_SECONDS, default 90s) — com o default o worker morreria antes
# de a visão responder, e a requisição voltaria como erro em vez de cair no
# ranking textual. Tem que ser maior que o timeout da visão.
#
# --workers 1: os projetos vivem na memória DO PROCESSO (SessionStore). Com 2
# workers, o /generate criava o carrossel num processo e o "Salvar edição" e o
# "Baixar ZIP" abriam conexão nova e caíam no outro processo na metade das
# vezes — 404 "Projeto não encontrado" com o carrossel recém-gerado na tela.
# (Requisições em sequência rápida reusam a conexão e acertam o worker; depois
# de editar por uns minutos, a conexão fecha e o POST sorteia.) A concorrência
# vem das threads; multi-worker exige store externo (Redis/DB), como o README
# documenta em "Limitações".
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "1", "--threads", "8", \
     "--timeout", "180", \
     "--access-logfile", "-", "--error-logfile", "-", "run:app"]
