"""Melhoria opcional do painel — o botão do /goviral.

O texto que o goviral entrega às vezes sai com parágrafos longos demais para a
caixa de um photo post. Este módulo pede a um LLM a versão melhor de cada peça
— hook mais afiado, parágrafos mais curtos, mesma ideia, mesma voz — e devolve
os parágrafos na MESMA ordem e quantidade, para o chamador remontar o painel
sem mudar a distribuição. Junto vem um script de fecho promovendo o goviral
app, que o chamador acrescenta como a última imagem do carrossel.

É deliberadamente OPCIONAL e fora do caminho de geração: o fluxo do painel
continua determinístico e sem LLM. Quem clica no botão vê o texto melhorado
DENTRO da caixa de colar, ainda editável, antes de gerar.

Qualquer falha (mock, sem credencial, timeout, JSON ruim, contagem errada)
devolve `None`: o chamador avisa e o texto original fica como está — nunca um
texto meio-melhorado. As exceções tolerantes: hook vazio na resposta mantém o
original, e promo ausente cai num texto fixo — nenhum dos dois muda a
distribuição, que é a única coisa que o botão promete não mexer.
"""

from __future__ import annotations

import logging
import re

import requests

from app.config import Settings
from app.adapters.text_composer import _parse_json_loose

logger = logging.getLogger(__name__)

# Alvo de tamanho por parágrafo. A caixa de baixo do slide comporta 280; o
# ponto ideal de leitura no feed fica bem antes disso.
PARAGRAPH_CHAR_TARGET = 120
# O hook cabe 160 (HOOK_TEXT_LIMIT) — o alvo fica antes para sobrar respiro.
HOOK_CHAR_TARGET = 90

# Fecho quando o modelo não devolve o campo "goviral": a promessa do botão —
# uma das imagens promove o app — não pode depender de o LLM obedecer.
GOVIRAL_PROMO_FALLBACK = [
    "esses scripts saíram prontos do goviral app, em segundos",
    "testa e me conta se o teu alcance não muda",
]

_ENHANCE_PROMPT = """Você melhora carrosséis virais de TikTok (photo post) criados no goviral app.

Recebe um JSON com "hook" e {count} parágrafos, numerados de "1" a "{count}".
Reescreva TUDO melhor e mais curto, seguindo a mesma linha do original:
- hook: a mesma promessa, mais afiada — máx {hook_target} caracteres, sem
  saudação e sem pergunta genérica
- parágrafos: corte palavras e rodeios; mantenha a ideia, os números e a voz
  do autor; máx {target} caracteres, 1 ou 2 frases curtas
- escreva como fala: minúsculas, "você", sem ponto final no fim
- mesmo idioma do original; não invente fatos que não estejam no texto
- NÃO junte, divida nem pule parágrafos: responda TODOS os {count} números,
  cada um com a versão curta do parágrafo daquele número
- "goviral": 2 frases curtas promovendo o goviral app — a ferramenta que gerou
  esses scripts — na mesma voz, convidando quem lê a testar

Retorne APENAS JSON válido, sem markdown, com os MESMOS {count} números como
chaves de "paragraphs":
{{"hook": "…", "paragraphs": {{"1": "…", "2": "…", "{count}": "…"}}, "goviral": ["frase 1", "frase 2"]}}
"""


def enhance_panel(
    settings: Settings, hook: str, paragraphs: list[str]
) -> dict | None:
    """Painel melhorado: hook novo, parágrafos na mesma ordem, script promo.

    Devolve `{"hook": str, "paragraphs": list[str], "promo": list[str]}` ou
    `None` em falha. Os parágrafos vão e voltam NUMERADOS ("1"…"N"): é o que
    torna o alinhamento verificável item a item. Uma lista sem números
    convidava o modelo a imitar o exemplo do prompt — ele devolvia 2 itens para
    10 parágrafos, e a resposta inteira era descartada. A validação dos
    parágrafos continua estrita: número faltando ou parágrafo vazio descartam
    tudo, porque um parágrafo trocado de lugar mudaria a distribuição pelas
    imagens.
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
                    target=PARAGRAPH_CHAR_TARGET,
                    hook_target=HOOK_CHAR_TARGET,
                    count=len(paragraphs),
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {"hook": hook, **numbered}, ensure_ascii=False
                ),
            },
        ],
        "temperature": 0.4,
        # JSON mode: no Groq, garante JSON válido e tira o raciocínio de
        # `content` — um modelo de raciocínio em `reasoning_format=raw` (o
        # default) devolvia o <think> no lugar do JSON.
        "response_format": {"type": "json_object"},
        # Desliga o raciocínio no Qwen 3.6 27B (parâmetro do Groq): sem isso o
        # modelo gastava o orçamento INTEIRO pensando e o JSON nem começava
        # (finish_reason=length com a resposta toda dentro de <think>).
        "reasoning_effort": "none",
        # ~60 tokens por parágrafo encurtado, com folga para o invólucro JSON
        # e para o retry sem reasoning_effort, onde o modelo pensa antes.
        "max_tokens": 4096 + 90 * len(paragraphs),
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
        # Nem todo endpoint OpenAI-compatible aceita response_format ou
        # reasoning_effort — um 400 imediato repete sem os dois, com o motivo
        # no log (sem ele, o 400 anterior ficou sem diagnóstico).
        if response.status_code in (400, 422):
            logger.warning(
                "Melhoria: endpoint rejeitou o payload (HTTP %d: %.300s) — "
                "repetindo sem json_mode/reasoning_effort.",
                response.status_code,
                response.text,
            )
            payload.pop("response_format", None)
            payload.pop("reasoning_effort", None)
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
        logger.warning("Melhoria falhou: %s", type(exc).__name__)
        return None
    except (ValueError, KeyError, IndexError) as exc:
        logger.warning("Melhoria: resposta ilegível (%s).", type(exc).__name__)
        return None

    # No retry sem reasoning_effort o pensamento vem em <think>…</think> antes
    # do JSON — fora daqui, ou o `{` de um exemplo pensado enganaria o parser.
    content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL)

    parsed = _parse_json_loose(content) or {}
    result = parsed.get("paragraphs")
    # Modelo que ignore os números e devolva a lista crua ainda é aproveitável —
    # mas só com a contagem exata, que é o que garante o alinhamento.
    if isinstance(result, list) and len(result) == len(paragraphs):
        result = {str(i + 1): p for i, p in enumerate(result)}
    if not isinstance(result, dict):
        logger.warning(
            "Melhoria: esperava %d parágrafos numerados, veio %s "
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
                "Melhoria: parágrafo %d ausente ou vazio na resposta — descartada.", i
            )
            return None
        cleaned.append(value)

    new_hook = " ".join(str(parsed.get("hook") or "").split()) or hook
    promo = _clean_promo(parsed.get("goviral"))
    return {"hook": new_hook, "paragraphs": cleaned, "promo": promo}


def _clean_promo(raw: object) -> list[str]:
    """Frases do script promo, toleradas em qualquer forma — ou o fallback."""
    if isinstance(raw, str):
        raw = [raw]
    if isinstance(raw, dict):
        raw = [raw[k] for k in sorted(raw)]
    if not isinstance(raw, list):
        return list(GOVIRAL_PROMO_FALLBACK)
    cleaned = [" ".join(str(item).split()) for item in raw if str(item).strip()]
    return cleaned[:2] or list(GOVIRAL_PROMO_FALLBACK)


__all__ = [
    "enhance_panel",
    "PARAGRAPH_CHAR_TARGET",
    "HOOK_CHAR_TARGET",
    "GOVIRAL_PROMO_FALLBACK",
]
