"""Simplificação opcional dos parágrafos do painel — o botão do /goviral.

O texto que o goviral entrega às vezes sai com parágrafos longos demais para a
caixa de um photo post. Este módulo pede a um LLM a versão mais curta de cada
parágrafo — menos palavras, mesma ideia, mesma voz — e devolve na MESMA ordem e
quantidade, para o chamador remontar o painel sem mudar a distribuição.

É deliberadamente OPCIONAL e fora do caminho de geração: o fluxo do painel
continua determinístico e sem LLM. Quem clica no botão vê o texto simplificado
DENTRO da caixa de colar, ainda editável, antes de gerar. O hook não passa por
aqui — hook bom já é curto, e reescrevê-lo seria mexer justamente na frase que o
usuário escolheu para parar o scroll.

Qualquer falha (mock, sem credencial, timeout, JSON ruim, contagem errada)
devolve `None`: o chamador avisa e o texto original fica como está — nunca um
texto meio-simplificado.
"""

from __future__ import annotations

import logging

import requests

from app.config import Settings
from app.adapters.text_composer import _parse_json_loose

logger = logging.getLogger(__name__)

# Alvo de tamanho por parágrafo. A caixa de baixo do slide comporta 280; o
# ponto ideal de leitura no feed fica bem antes disso.
PARAGRAPH_CHAR_TARGET = 120

_ENHANCE_PROMPT = """Você encurta parágrafos de carrosséis virais de TikTok (photo post).

Recebe um JSON com {count} parágrafos, numerados de "1" a "{count}". Reescreva
CADA UM deles mais curto e simples:
- corte palavras e rodeios; mantenha a ideia, os números e a voz do autor
- no máximo {target} caracteres por parágrafo, 1 ou 2 frases curtas
- escreva como fala: minúsculas, "você", sem ponto final no fim
- mesmo idioma do original; não invente nada que não esteja no texto
- NÃO junte, divida nem pule parágrafos: responda TODOS os {count} números,
  cada um com a versão curta do parágrafo daquele número

Retorne APENAS JSON válido, sem markdown, com os MESMOS {count} números como
chaves:
{{"paragraphs": {{"1": "versão curta do parágrafo 1", "2": "…", "{count}": "…"}}}}
"""


def enhance_paragraphs(
    settings: Settings, paragraphs: list[str]
) -> list[str] | None:
    """Versão simplificada de cada parágrafo, na mesma ordem. `None` = falha.

    Os parágrafos vão e voltam NUMERADOS ("1"…"N"): é o que torna o alinhamento
    verificável item a item. Uma lista sem números convidava o modelo a imitar o
    exemplo do prompt — ele devolvia 2 itens para 10 parágrafos, e a resposta
    inteira era descartada. A validação continua estrita: número faltando ou
    parágrafo vazio descartam tudo, porque um parágrafo trocado de lugar mudaria
    a distribuição pelas imagens — a única coisa que o botão promete não mexer.
    """
    if not paragraphs:
        return None
    if settings.llm_provider == "mock" or not settings.llm_configured:
        return None

    import json

    numbered = {str(i + 1): p for i, p in enumerate(paragraphs)}
    payload = {
        "model": settings.llm_model or "llama-3.1-8b-instant",
        "messages": [
            {
                "role": "system",
                "content": _ENHANCE_PROMPT.format(
                    target=PARAGRAPH_CHAR_TARGET, count=len(paragraphs)
                ),
            },
            {
                "role": "user",
                "content": json.dumps(numbered, ensure_ascii=False),
            },
        ],
        "temperature": 0.4,
        # JSON mode: no Groq, garante JSON válido e tira o raciocínio de
        # `content` — um modelo de raciocínio em `reasoning_format=raw` (o
        # default) devolvia o <think> no lugar do JSON e a resposta inteira
        # era descartada como "NoneType".
        "response_format": {"type": "json_object"},
        # ~60 tokens por parágrafo encurtado, com folga para o invólucro JSON.
        # A base é generosa porque um modelo de raciocínio gasta o orçamento
        # pensando ANTES do JSON — com 200 de base, 10 parágrafos voltavam
        # cortados no meio (finish_reason=length) e nada era aproveitado.
        "max_tokens": 2048 + 90 * len(paragraphs),
    }

    def _post(body: dict):
        return requests.post(
            f"{settings.llm_api_base_url.rstrip('/')}/chat/completions",
            json=body,
            headers={
                "Authorization": f"Bearer {settings.llm_api_key}",
                "Content-Type": "application/json",
            },
            timeout=settings.request_timeout_seconds,
        )

    try:
        response = _post(payload)
        # Nem todo endpoint OpenAI-compatible aceita response_format — um 400
        # imediato repete sem o campo, como o vision faz com enable_thinking.
        if response.status_code in (400, 422):
            logger.warning(
                "Simplificação: endpoint rejeitou json_mode (HTTP %d) — repetindo sem ele.",
                response.status_code,
            )
            payload.pop("response_format", None)
            response = _post(payload)
        response.raise_for_status()
        choice = (response.json().get("choices") or [{}])[0]
        finish_reason = choice.get("finish_reason")
        message = choice.get("message") or {}
        content = message.get("content") or ""
        if not content.strip():
            # Modelo de raciocínio com `content` vazio pode ter posto a
            # resposta no campo de raciocínio (Groq: `reasoning`).
            content = message.get("reasoning") or message.get("reasoning_content") or ""
    except requests.RequestException as exc:
        logger.warning("Simplificação falhou: %s", type(exc).__name__)
        return None
    except (ValueError, KeyError, IndexError) as exc:
        logger.warning("Simplificação: resposta ilegível (%s).", type(exc).__name__)
        return None

    parsed = _parse_json_loose(content) or {}
    result = parsed.get("paragraphs")
    # Modelo que ignore os números e devolva a lista crua ainda é aproveitável —
    # mas só com a contagem exata, que é o que garante o alinhamento.
    if isinstance(result, list) and len(result) == len(paragraphs):
        result = {str(i + 1): p for i, p in enumerate(result)}
    if not isinstance(result, dict):
        logger.warning(
            "Simplificação: esperava %d parágrafos numerados, veio %s "
            "(finish_reason=%s; resposta: %.120s) — descartada.",
            len(paragraphs),
            f"lista de {len(result)}" if isinstance(result, list) else type(result).__name__,
            finish_reason,
            content.strip() or "(vazia)",
        )
        return None
    cleaned: list[str] = []
    for i in range(1, len(paragraphs) + 1):
        value = " ".join(str(result.get(str(i)) or "").split())
        if not value:
            logger.warning(
                "Simplificação: parágrafo %d ausente ou vazio na resposta — descartada.", i
            )
            return None
        cleaned.append(value)
    return cleaned


__all__ = ["enhance_paragraphs", "PARAGRAPH_CHAR_TARGET"]
