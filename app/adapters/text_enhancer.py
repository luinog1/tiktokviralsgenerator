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

Recebe uma lista JSON de parágrafos. Reescreva CADA um mais curto e simples:
- corte palavras e rodeios; mantenha a ideia, os números e a voz do autor
- no máximo {target} caracteres por parágrafo, 1 ou 2 frases curtas
- escreva como fala: minúsculas, "você", sem ponto final no fim
- mesmo idioma do original; não invente nada que não esteja no texto
- NÃO junte, divida, reordene nem remova parágrafos: mesma quantidade, mesma ordem

Retorne APENAS JSON válido, sem markdown:
{{"paragraphs": ["", ""]}}
"""


def enhance_paragraphs(
    settings: Settings, paragraphs: list[str]
) -> list[str] | None:
    """Versão simplificada de cada parágrafo, na mesma ordem. `None` = falha.

    A validação é estrita — contagem diferente ou item vazio descartam a
    resposta inteira: um parágrafo trocado de lugar mudaria a distribuição
    pelas imagens, que é a única coisa que o botão promete não mexer.
    """
    if not paragraphs:
        return None
    if settings.llm_provider == "mock" or not settings.llm_configured:
        return None

    import json

    payload = {
        "model": settings.llm_model or "llama-3.1-8b-instant",
        "messages": [
            {
                "role": "system",
                "content": _ENHANCE_PROMPT.format(target=PARAGRAPH_CHAR_TARGET),
            },
            {
                "role": "user",
                "content": json.dumps(paragraphs, ensure_ascii=False),
            },
        ],
        "temperature": 0.4,
        # ~60 tokens por parágrafo encurtado, com folga para o invólucro JSON.
        "max_tokens": 200 + 90 * len(paragraphs),
    }
    try:
        response = requests.post(
            f"{settings.llm_api_base_url.rstrip('/')}/chat/completions",
            json=payload,
            headers={
                "Authorization": f"Bearer {settings.llm_api_key}",
                "Content-Type": "application/json",
            },
            timeout=settings.request_timeout_seconds,
        )
        response.raise_for_status()
        content = (
            (response.json().get("choices") or [{}])[0]
            .get("message", {})
            .get("content", "")
        )
    except requests.RequestException as exc:
        logger.warning("Simplificação falhou: %s", type(exc).__name__)
        return None
    except (ValueError, KeyError, IndexError) as exc:
        logger.warning("Simplificação: resposta ilegível (%s).", type(exc).__name__)
        return None

    parsed = _parse_json_loose(content) or {}
    result = parsed.get("paragraphs")
    if not isinstance(result, list) or len(result) != len(paragraphs):
        logger.warning(
            "Simplificação: esperava %d parágrafos, veio %s — descartada.",
            len(paragraphs),
            len(result) if isinstance(result, list) else type(result).__name__,
        )
        return None
    cleaned = [" ".join(str(p or "").split()) for p in result]
    if not all(cleaned):
        logger.warning("Simplificação devolveu parágrafo vazio — descartada.")
        return None
    return cleaned


__all__ = ["enhance_paragraphs", "PARAGRAPH_CHAR_TARGET"]
