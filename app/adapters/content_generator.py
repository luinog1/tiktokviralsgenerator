"""Generate a complete Go Viral-style panel from a short creator brief.

The public Go Viral dashboard has no API, so the application cannot fetch its
content reliably. This adapter produces the same canonical Hook/Script/
Paragraph structure with the OpenAI-compatible LLM that is already configured
for text composition. The generated panel then follows the existing parser,
image search, preview, and renderer paths without any special cases.

Model output is treated as untrusted input. A result is accepted only when it
contains the requested number of scripts and exactly two non-empty text boxes
per script. Partial JSON, missing scripts, or empty paragraphs discard the
whole response instead of silently changing the carousel layout.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import requests

from app.adapters.text_composer import _parse_json_loose
from app.config import Settings

logger = logging.getLogger(__name__)

HOOK_LIMIT = 160
PARAGRAPH_1_LIMIT = 70
PARAGRAPH_2_LIMIT = 280

LANGUAGE_NAMES = {
    "auto": "o mesmo idioma predominante do briefing",
    "pt-BR": "portugues do Brasil",
    "en-US": "English (US)",
    "es-ES": "espanol de Espana",
}

_GENERATOR_PROMPT = """Voce cria roteiros de slideshow para TikTok seguindo o formato Go Viral.

IDIOMA: escreva somente em {language}. Nao traduza fatos, nomes ou valores.

FORMATO OBRIGATORIO:
- gere 1 hook e exatamente {script_count} scripts, totalizando {slide_count} imagens
- o hook vai sozinho na imagem 1 e deve ter no maximo {hook_limit} caracteres
- cada script tem exatamente 2 caixas: paragraph_1 com no maximo {p1_limit}
  caracteres e paragraph_2 com no maximo {p2_limit} caracteres
- cada script fecha uma ideia completa; nenhuma frase depende da proxima imagem
- retorne tambem um tema curto e palavras-chave visuais para buscar as fotos

REGRAS DE CONTEUDO:
- use um hook comprovado: jornada + aprendizado, erro + consequencia, bastidor
  pouco falado, linha do tempo, contraste ou resultado especifico
- o hook precisa dizer claramente o assunto e abrir curiosidade sem clickbait vazio
- construa uma progressao: contexto, dificuldade, virada, aprendizado e fechamento
- use narrativa pessoal somente quando o briefing trouxer fatos pessoais; se nao
  trouxer, escreva como conselho ou observacao e nao invente uma experiencia
- preserve exatamente numeros, datas, ganhos, resultados e acontecimentos fornecidos
- nunca invente autoridade, emprego, evento, depoimento, metrica ou resultado
- escreva como uma pessoa fala: concreto, relacionavel, sem jargao de marketing
- mantenha a capitalizacao consistente e use no maximo 1 emoji natural por caixa
- nunca use travessao longo; use virgula, ponto ou hifen simples
- evite saudacao, introducao, hashtags, instrucoes visuais e frases sobre ser IA
- o ultimo script deve fechar a historia com payoff, incentivo ou uma acao clara
{app_rule}

Retorne APENAS JSON valido, sem markdown. O JSON deve seguir exatamente:
{{
  "hook": "texto",
  "scripts": [
    {{"position": 1, "paragraph_1": "caixa de cima", "paragraph_2": "caixa de baixo"}}
  ],
  "image_theme": "tema visual curto",
  "image_keywords": ["palavra visual 1", "palavra visual 2"]
}}
"""


def generate_content_panel(
    settings: Settings,
    *,
    brief: str,
    audience: str = "",
    language: str = "auto",
    slide_count: int = 6,
    include_app: bool = True,
) -> dict[str, Any] | None:
    """Return a validated generated panel, or ``None`` on any LLM failure."""
    brief = " ".join(str(brief or "").split())
    audience = " ".join(str(audience or "").split())
    if not brief or not 3 <= slide_count <= 12:
        return None
    if settings.llm_provider == "mock" or not settings.llm_configured:
        return None

    language = language if language in LANGUAGE_NAMES else "auto"
    script_count = slide_count - 1
    app_rule = (
        "- reserve um dos 2 ultimos scripts para mencionar naturalmente o "
        '"Go Viral app" como ferramenta usada antes de postar; nao invente '
        "numeros de crescimento causados pelo app"
        if include_app
        else "- nao mencione nenhum aplicativo ou produto que nao esteja no briefing"
    )
    prompt = _GENERATOR_PROMPT.format(
        language=LANGUAGE_NAMES[language],
        script_count=script_count,
        slide_count=slide_count,
        hook_limit=HOOK_LIMIT,
        p1_limit=PARAGRAPH_1_LIMIT,
        p2_limit=PARAGRAPH_2_LIMIT,
        app_rule=app_rule,
    )
    user_input = {
        "brief": brief,
        "audience": audience or "nao informado",
        "requested_language": language,
        "total_images": slide_count,
    }
    payload = {
        "model": settings.llm_model or "llama-3.1-8b-instant",
        "messages": [
            {"role": "system", "content": prompt},
            {
                "role": "user",
                "content": json.dumps(user_input, ensure_ascii=False),
            },
        ],
        "temperature": 0.7,
        "response_format": {"type": "json_object"},
        "reasoning_effort": "none",
        "max_tokens": 4096 + 120 * script_count,
    }

    def _post(body: dict[str, Any]):
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
        # OpenAI supports JSON mode, while some compatible providers reject
        # response_format or reasoning_effort. Keep the existing app contract:
        # one minimal retry preserves compatibility with both kinds of endpoint.
        if response.status_code in (400, 422):
            logger.warning(
                "Gerador de conteudo: endpoint rejeitou payload (HTTP %d: %.300s); "
                "repetindo sem json_mode/reasoning_effort.",
                response.status_code,
                response.text,
            )
            payload.pop("response_format", None)
            payload.pop("reasoning_effort", None)
            response = _post(payload)
        response.raise_for_status()
        choice = (response.json().get("choices") or [{}])[0]
        message = choice.get("message") or {}
        content = message.get("content") or ""
        if not str(content).strip():
            content = message.get("reasoning") or message.get("reasoning_content") or ""
    except requests.RequestException as exc:
        logger.warning("Gerador de conteudo falhou: %s", type(exc).__name__)
        return None
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        logger.warning("Gerador de conteudo: resposta ilegivel (%s).", type(exc).__name__)
        return None

    content = re.sub(r"<think>.*?</think>", "", str(content), flags=re.DOTALL)
    parsed = _parse_json_loose(content)
    if not isinstance(parsed, dict):
        logger.warning("Gerador de conteudo: resposta sem JSON utilizavel.")
        return None

    result = _normalize_result(
        parsed,
        script_count=script_count,
        brief=brief,
        language=language,
        include_app=include_app,
    )
    if result is None:
        return None
    result["raw_text"] = format_panel(result["hook"], result["scripts"])
    result["blocks"] = [
        result["hook"],
        *[
            f"{script['paragraph_1']}\n\n{script['paragraph_2']}"
            for script in result["scripts"]
        ],
    ]
    return result


def format_panel(hook: str, scripts: list[dict[str, Any]]) -> str:
    """Build the exact canonical text consumed by ``goviral_parser``."""
    lines = ["Hook", hook, "Scripts"]
    for number, script in enumerate(scripts, start=1):
        lines.extend(
            [
                f"Script {number}",
                f"Position {number}",
                "Paragraph 1:",
                str(script["paragraph_1"]),
                "Paragraph 2:",
                str(script["paragraph_2"]),
            ]
        )
    return "\n".join(lines)


def _normalize_result(
    parsed: dict[str, Any],
    *,
    script_count: int,
    brief: str,
    language: str,
    include_app: bool,
) -> dict[str, Any] | None:
    hook = _clean_text(parsed.get("hook"), HOOK_LIMIT)
    scripts_raw = parsed.get("scripts")
    if isinstance(scripts_raw, dict):
        scripts_raw = [scripts_raw[key] for key in _ordered_keys(scripts_raw)]
    if not hook or not isinstance(scripts_raw, list) or len(scripts_raw) != script_count:
        logger.warning(
            "Gerador de conteudo: esperava hook + %d scripts, recebeu %s.",
            script_count,
            type(scripts_raw).__name__,
        )
        return None

    scripts: list[dict[str, Any]] = []
    for position, raw in enumerate(scripts_raw, start=1):
        if not isinstance(raw, dict):
            return None
        p1 = _first_text(raw, "paragraph_1", "paragraph1", "headline", "title")
        p2 = _first_text(raw, "paragraph_2", "paragraph2", "body", "text")
        p1 = _clean_text(p1, PARAGRAPH_1_LIMIT)
        p2 = _clean_text(p2, PARAGRAPH_2_LIMIT)
        if not p1 or not p2:
            logger.warning(
                "Gerador de conteudo: script %d sem as duas caixas.", position
            )
            return None
        scripts.append(
            {
                "position": position,
                "paragraph_1": p1,
                "paragraph_2": p2,
            }
        )

    if include_app and not _mentions_go_viral(hook, scripts):
        # The guideline requires an explicit app plug. Reserve the penultimate
        # script for it when the model ignores the rule, leaving the final
        # script free to close the story or deliver the CTA.
        target = max(0, len(scripts) - 2)
        fallback = _app_script(language, sample=f"{hook} {brief}")
        scripts[target]["paragraph_1"] = fallback[0]
        scripts[target]["paragraph_2"] = fallback[1]

    theme = _clean_text(parsed.get("image_theme"), 100)
    if not theme:
        theme = _clean_text(brief, 100)
    keywords = _clean_keywords(parsed.get("image_keywords"))
    return {
        "hook": hook,
        "scripts": scripts,
        "theme": theme,
        "keywords": keywords,
    }


def _first_text(raw: dict[str, Any], *keys: str) -> object:
    for key in keys:
        value = raw.get(key)
        if value is not None and str(value).strip():
            return value
    paragraphs = raw.get("paragraphs")
    if isinstance(paragraphs, list):
        index = 0 if "paragraph_1" in keys else 1
        return paragraphs[index] if len(paragraphs) > index else ""
    if isinstance(paragraphs, dict):
        key = "1" if "paragraph_1" in keys else "2"
        return paragraphs.get(key) or ""
    return ""


def _clean_text(value: object, limit: int) -> str:
    text = " ".join(str(value or "").split())
    # The creator guide explicitly rejects long dashes as an AI tell.
    text = re.sub(r"\s*[\u2013\u2014]\s*", " - ", text)
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    cut = text[: max(0, limit - 3)].rsplit(" ", 1)[0].rstrip(" ,.;:-")
    return f"{cut or text[: limit - 3]}..."


def _clean_keywords(raw: object) -> list[str]:
    if isinstance(raw, str):
        raw = raw.split(",")
    if not isinstance(raw, list):
        return []
    result: list[str] = []
    for item in raw:
        value = _clean_text(item, 60)
        if value and value.lower() not in {word.lower() for word in result}:
            result.append(value)
    return result[:8]


def _ordered_keys(data: dict[Any, Any]) -> list[Any]:
    def order(key: Any) -> tuple[int, str]:
        match = re.search(r"\d+", str(key))
        return (int(match.group()) if match else 10_000, str(key))

    return sorted(data, key=order)


def _mentions_go_viral(hook: str, scripts: list[dict[str, Any]]) -> bool:
    sample = " ".join(
        [
            hook,
            *[
                f"{script['paragraph_1']} {script['paragraph_2']}"
                for script in scripts
            ],
        ]
    )
    return bool(re.search(r"\bgo\s*viral(?:\s+app)?\b", sample, re.IGNORECASE))


def _app_script(language: str, *, sample: str = "") -> tuple[str, str]:
    if language == "auto":
        language = _detect_language(sample)
    if language == "en-US":
        return (
            "what changed the way i post",
            "i started checking my videos in the Go Viral app before posting, so i could fix weak hooks and unclear pacing first",
        )
    if language == "es-ES":
        return (
            "lo que cambio mi forma de publicar",
            "empece a revisar mis videos en Go Viral app antes de publicar, para corregir hooks flojos y un ritmo poco claro",
        )
    return (
        "o que mudou meu jeito de postar",
        "comecei a revisar meus videos no Go Viral app antes de postar, para corrigir hooks fracos e um ritmo confuso",
    )


def _detect_language(sample: str) -> str:
    words = set(re.findall(r"[a-zA-ZÀ-ÿ']+", sample.lower()))
    english = len(words & {"the", "and", "you", "i", "it", "was", "is", "my", "to", "but"})
    spanish = len(words & {"que", "para", "con", "una", "como", "pero", "mis", "los", "las"})
    portuguese = len(words & {"que", "não", "nao", "você", "voce", "de", "para", "com", "mais", "uma"})
    if english > max(spanish, portuguese):
        return "en-US"
    if spanish > portuguese:
        return "es-ES"
    return "pt-BR"


__all__ = [
    "generate_content_panel",
    "format_panel",
    "HOOK_LIMIT",
    "PARAGRAPH_1_LIMIT",
    "PARAGRAPH_2_LIMIT",
]
