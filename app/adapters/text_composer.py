"""TextComposer — divide o texto colado (vindo do goviral.ai) em slides.

O usuário cola o texto gerado pela ferramenta externa goviral.ai
(https://content.goviralai.app/), acessada manualmente via login Discord.
Este módulo NÃO chama o goviral.ai — apenas estrutura o texto já pronto.

Dois modos:
- mock: divisão determinística por sentenças/parágrafos.
- llm:   usa endpoint compatível com Groq (openai-compatible) para refinar os slides.
         Se o endpoint não estiver configurado ou falhar, cai para mock.

Saída é sempre uma lista de slide dicts com headline + body + cta opcional.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Protocol

import requests

from app.config import Settings

logger = logging.getLogger(__name__)


@dataclass
class SlideContent:
    """Um slide do carrossel: headline curta + corpo + CTA opcional.

    `role` indica a função do slide dentro do roteiro viral
    (hook / problem / agitation / value / proof / cta) — usado pelo
    SlideRenderer para posicionar o texto na imagem.

    `pos_x`/`pos_y` são o centro do bloco de texto em fração do canvas (0..1),
    definidos quando o usuário arrasta as caixas na prévia. `None` mantém a
    posição padrão do papel no roteiro.
    """

    headline: str
    body: str = ""
    call_to_action: str = ""
    order: int = 0
    role: str = "value"
    pos_x: float | None = None
    pos_y: float | None = None
    # Foto escolhida para este slide. Preenchido pelo casting (hook = pessoa,
    # demais = cenário) e depois pela galeria da prévia. Vazio = a prévia cai na
    # rotação `i % len(images)`.
    image_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "headline": self.headline,
            "body": self.body,
            "call_to_action": self.call_to_action,
            "order": self.order,
            "role": self.role,
            "pos_x": self.pos_x,
            "pos_y": self.pos_y,
            "image_id": self.image_id,
        }


@dataclass
class ComposedCarousel:
    """Resultado da composição: lista ordenada de slides + metadados."""

    slides: list[SlideContent] = field(default_factory=list)
    hashtags: list[str] = field(default_factory=list)
    caption: str = ""
    provider: str = "unknown"

    def to_dict(self) -> dict[str, Any]:
        return {
            "slides": [s.to_dict() for s in self.slides],
            "hashtags": list(self.hashtags),
            "caption": self.caption,
            "provider": self.provider,
        }


class TextComposer(Protocol):
    """Interface para composição de carrossel a partir de texto bruto."""

    name: str

    def compose(
        self,
        raw_text: str,
        *,
        style: str = "quote",
        slides_count: int = 6,
        extra: dict[str, Any] | None = None,
    ) -> ComposedCarousel:  # pragma: no cover
        ...


# ---------- helpers de limpeza ----------

_BULLET_RE = re.compile(r"^\s*([•\-\*\u2022]|(\d+\.)|\(\d+\))\s+", re.MULTILINE)
_HASHTAG_RE = re.compile(r"(^|\s)(#[\wÀ-ÿ]+)")
_SENTENCE_END_RE = re.compile(r"(?<=[.!?])\s+")


def _clean(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    # Normaliza bullets (mantém a frase, remove o marcador)
    text = _BULLET_RE.sub(r"", text)
    # Colapsa múltiplos espaços / quebras
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _extract_hashtags(text: str) -> list[str]:
    matches = _HASHTAG_RE.findall(text)
    tags: list[str] = []
    for _, tag in matches:
        clean_tag = tag.lstrip("#").strip()
        if clean_tag and clean_tag.lower() not in {t.lower() for t in tags}:
            tags.append(clean_tag)
    return tags[:10]


def _split_sentences(text: str) -> list[str]:
    text = text.replace("\n", " ")
    parts = _SENTENCE_END_RE.split(text)
    return [p.strip() for p in parts if p and len(p.strip()) > 3]


def _split_paragraphs(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]


def _truncate(text: str, limit: int) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return cut + "…"


# ---------- roteiro viral (estrutura de 3 atos) ----------
#
# Estrutura clássica de script viral de TikTok:
#   Ato 1 — HOOK (0-3s): para o scroll.
#   Ato 2 — DESENVOLVIMENTO: problema → agitação → valor → prova.
#   Ato 3 — CTA: fecha com uma ação clara.
#
# Cada slide do carrossel recebe um desses papéis. O SlideRenderer usa o papel
# para decidir onde posicionar o texto na imagem (hook fica embaixo e sozinho,
# slides de valor ficam em dois blocos, etc.).

VIRAL_ROLES = ("hook", "problem", "agitation", "value", "proof", "cta")


def viral_script_roles(slides_count: int) -> list[str]:
    """Distribui os papéis do roteiro viral ao longo de N slides."""
    n = max(1, slides_count)
    if n == 1:
        return ["hook"]
    if n == 2:
        return ["hook", "cta"]
    if n == 3:
        return ["hook", "value", "cta"]
    if n == 4:
        return ["hook", "problem", "value", "cta"]
    if n == 5:
        return ["hook", "problem", "value", "value", "cta"]
    # n >= 6 — estrutura completa, com o miolo em slides de valor
    return ["hook", "problem", "agitation"] + ["value"] * (n - 5) + ["proof", "cta"]


def _normalize_role(value: str) -> str:
    role = str(value or "").strip().lower()
    return role if role in VIRAL_ROLES else ""


# CTA padrão por estilo — usado só no slide de fecho (role="cta").
_STYLE_CTA = {
    "sticker": "salva esse post pra não esquecer 🤍",
    "quote": "salva pra reler depois 🤍",
    "list": "salva esse post 🔖",
    "tutorial": "comenta qual passo você vai aplicar 👇",
    "story": "segue para mais conteúdos 💜",
}



# ---------- implementação mock (determinística) ----------


class MockTextComposer:
    """Divisão determinística — funciona sem LLM."""

    name = "mock"

    def compose(
        self,
        raw_text: str,
        *,
        style: str = "quote",
        slides_count: int = 6,
        extra: dict[str, Any] | None = None,
    ) -> ComposedCarousel:
        cleaned = _clean(raw_text)
        if not cleaned:
            return ComposedCarousel(slides=[], provider=self.name)

        hashtags = _extract_hashtags(cleaned)
        # Remove hashtags do corpo para não poluir os slides
        body_text = _HASHTAG_RE.sub("", cleaned).strip()
        body_text = re.sub(r"\s{2,}", " ", body_text)

        slides: list[SlideContent] = []
        paragraphs = _split_paragraphs(body_text)

        if paragraphs and len(paragraphs) >= 2:
            chunks = paragraphs
        else:
            sentences = _split_sentences(body_text)
            chunks = sentences if sentences else [body_text]

        # Sempre produzir exatamente `target` slides, mesmo que
        # o texto seja curto — repetimos os chunks em rotação.
        target = max(1, slides_count)
        if not chunks:
            # Sem conteúdo útil — preenche com placeholder
            chunks = ["Conteúdo a ser editado."]

        roles = viral_script_roles(target)

        if len(chunks) >= target:
            # Agrupar chunks por slide
            per_slide = max(1, len(chunks) // target)
            for i in range(target):
                start = i * per_slide
                if i == target - 1:
                    chunk_list = chunks[start:]
                else:
                    chunk_list = chunks[start : start + per_slide]
                slide_body = " ".join(chunk_list).strip()
                slides.append(self._build_slide(slide_body, i, style, roles[i]))
        else:
            # Menos chunks que slides — repetir em rotação para preencher
            for i in range(target):
                chunk = chunks[i % len(chunks)]
                # Variar ligeiramente para não ficar idêntico
                suffix = f" (parte {i + 1}/{target})" if i >= len(chunks) else ""
                slides.append(self._build_slide(chunk + suffix, i, style, roles[i]))

        caption = self._build_caption(body_text, style)
        return ComposedCarousel(
            slides=slides,
            hashtags=hashtags,
            caption=caption,
            provider=self.name,
        )

    @staticmethod
    def _build_slide(body: str, order: int, style: str, role: str = "value") -> SlideContent:
        body = body.strip()
        if not body:
            body = "Continue para o próximo slide."
        # Headline = primeira frase; body = o que sobra. Repetir a mesma frase
        # nos dois campos deixava o slide com o texto duplicado.
        sentences = _split_sentences(body)
        if len(sentences) > 1:
            headline = _truncate(sentences[0], 90)
            rest = _truncate(" ".join(sentences[1:]), 280)
        else:
            headline = _truncate(body, 90)
            rest = ""
        # CTA só no slide de fecho — repetir em todos polui o carrossel.
        cta = _STYLE_CTA.get(style, "comenta abaixo 👇") if role == "cta" else ""
        return SlideContent(
            headline=headline,
            body=rest,
            call_to_action=cta,
            order=order,
            role=role,
        )

    @staticmethod
    def _build_caption(body: str, style: str) -> str:
        first_line = body.split("\n")[0].strip()
        if not first_line:
            first_line = "Conteúdo para o seu carrossel."
        return _truncate(first_line, 200)


# ---------- implementação LLM (Groq-compatible, OpenAI-style) ----------


# Estrutura de roteiro viral de TikTok (hook → desenvolvimento → CTA).
# O texto colado do goviral.ai já vem pronto em prosa; o papel do LLM aqui é
# REORDENAR e ENCURTAR esse texto na sequência que retém atenção, não inventar
# conteúdo novo.
_VIRAL_GUIDE = """Você é roteirista de carrosséis virais para TikTok (photo post).

Recebe um texto bruto já escrito e o reorganiza em {n} slides seguindo a
estrutura de roteiro viral em 3 atos:

ATO 1 — HOOK (slide 1): para o scroll em 1 segundo. Use um destes tipos:
  - pergunta chocante ("ainda tá cometendo esse erro?")
  - promessa forte ("o que 99% ignora")
  - contrarian ("para de postar todo dia, faz isso")
  - storytelling ("testei 50 formatos, esse é o melhor")
ATO 2 — DESENVOLVIMENTO: problema (a dor) → agitação (a consequência) →
  valor (a entrega concreta, um slide por ideia) → prova (número, resultado).
ATO 3 — CTA (último slide): uma ação clara e só uma.

Cada slide recebe um "role" nesta ordem exata: {roles}

REGRAS DE ESCRITA (formato sticker do TikTok):
- Escreva como fala: frases curtas, "você", contrações, tom de conversa.
- Tudo em minúsculas, sem ponto final no fim das frases.
- 1 ideia por slide. Nunca misture assuntos.
- headline: máx 60 caracteres. É a frase que vai grande na imagem.
- body: máx 180 caracteres, 1 ou 2 frases. Pode ser vazio no slide de hook.
- call_to_action: SÓ no último slide (role="cta"). Vazio nos demais.
- Use números específicos quando o texto original tiver.
- Idioma da saída: {language}.
- Não invente fatos que não estejam no texto original.

Retorne APENAS JSON válido, sem markdown, neste formato:
"""

_VIRAL_SCHEMA = (
    '{"slides":[{"role":"hook","headline":"","body":"","call_to_action":""}],'
    '"hashtags":["",""],"caption":""}'
)


def _build_viral_prompt(slides_count: int, language: str, roles: list[str]) -> str:
    return _VIRAL_GUIDE.format(
        n=slides_count,
        language=language or "pt-BR",
        roles=" → ".join(roles),
    ) + _VIRAL_SCHEMA



class LLMTextComposer:
    """Usa um endpoint OpenAI-compatible (Groq, OpenAI, Ollama, etc.)."""

    name = "llm"

    def __init__(self, settings: Settings):
        self._settings = settings
        self._timeout = settings.request_timeout_seconds
        self._base = settings.llm_api_base_url.rstrip("/")
        self._key = settings.llm_api_key
        self._model = settings.llm_model or "llama-3.1-8b-instant"

    def compose(
        self,
        raw_text: str,
        *,
        style: str = "quote",
        slides_count: int = 6,
        extra: dict[str, Any] | None = None,
    ) -> ComposedCarousel:
        cleaned = _clean(raw_text)
        if not cleaned:
            return ComposedCarousel(provider=self.name)

        language = str((extra or {}).get("language") or "pt-BR")
        roles = viral_script_roles(slides_count)

        # Tentativa 1: sem response_format (compatível com QUALQUER modelo Groq,
        # incluindo qwen, gemma, etc. que podem não suportar JSON mode).
        # O _parse_json_loose já extrai JSON mesmo se o modelo cercar com texto.
        try:
            payload = {
                "model": self._model,
                "messages": [
                    {
                        "role": "system",
                        "content": _build_viral_prompt(slides_count, language, roles),
                    },
                    {"role": "user", "content": cleaned},
                ],
                "temperature": 0.6,
                "max_tokens": 1200,
            }
            response = requests.post(
                f"{self._base}/chat/completions",
                json=payload,
                headers={
                    "Authorization": f"Bearer {self._key}",
                    "Content-Type": "application/json",
                },
                timeout=self._timeout,
            )
            # Se erro 4xx relacionado a response_format ou parâmetros,
            # tentar novamente com payload mínimo
            if response.status_code in (400, 422):
                error_text = response.text[:300]
                logger.warning(
                    "LLM rejeitou payload (HTTP %d): %s — tentando sem json_mode",
                    response.status_code,
                    error_text,
                )
            response.raise_for_status()
        except requests.Timeout:
            logger.warning("LLM composer timeout — fallback mock.")
            return MockTextComposer().compose(
                cleaned, style=style, slides_count=slides_count, extra=extra
            )
        except requests.RequestException as exc:
            logger.warning("LLM composer erro: %s — fallback mock.", type(exc).__name__)
            return MockTextComposer().compose(
                cleaned, style=style, slides_count=slides_count, extra=extra
            )

        try:
            data = response.json() or {}
            content = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
            parsed = _parse_json_loose(content)
        except (ValueError, KeyError, IndexError) as exc:
            logger.warning("LLM retornou JSON inválido (%s) — fallback mock.", type(exc).__name__)
            return MockTextComposer().compose(
                cleaned, style=style, slides_count=slides_count, extra=extra
            )

        if not parsed:
            return MockTextComposer().compose(
                cleaned, style=style, slides_count=slides_count, extra=extra
            )

        slides_data: Iterable[dict[str, Any]] = parsed.get("slides") or []
        slides: list[SlideContent] = []
        for i, s in enumerate(slides_data):
            headline = _truncate(str(s.get("headline") or "").strip(), 70)
            body = _truncate(str(s.get("body") or "").strip(), 280)
            if not headline and not body:
                continue
            # O papel vem do modelo, mas a posição manda: se o modelo devolver
            # um papel inválido (ou nenhum), usamos o da estrutura canônica.
            order = len(slides)
            role = _normalize_role(s.get("role")) or (
                roles[order] if order < len(roles) else "value"
            )
            cta = _truncate(str(s.get("call_to_action") or "").strip(), 80)
            slides.append(
                SlideContent(
                    headline=headline,
                    body=body,
                    call_to_action=cta if role == "cta" else "",
                    order=order,
                    role=role,
                )
            )

        if not slides:
            return MockTextComposer().compose(
                cleaned, style=style, slides_count=slides_count, extra=extra
            )

        # Garantir que o carrossel sempre feche com um CTA visível.
        last = slides[-1]
        if last.role == "cta" and not last.call_to_action:
            last.call_to_action = _STYLE_CTA.get(style, "comenta abaixo 👇")

        hashtags_raw = parsed.get("hashtags") or []
        hashtags = [str(h).lstrip("#").strip() for h in hashtags_raw if str(h).strip()][:10]
        if not hashtags:
            hashtags = _extract_hashtags(cleaned)

        caption = _truncate(str(parsed.get("caption") or "").strip(), 200)
        if not caption:
            caption = MockTextComposer._build_caption(cleaned, style)

        return ComposedCarousel(
            slides=slides,
            hashtags=hashtags,
            caption=caption,
            provider=self.name,
        )


def _parse_json_loose(content: str) -> dict[str, Any] | None:
    """Tenta extrair JSON mesmo se o modelo cercar com texto/markdown."""
    if not content:
        return None
    content = content.strip()
    # Remove cercas ```json ... ```
    fence = re.search(r"```(?:json)?\s*(.*?)```", content, re.DOTALL)
    if fence:
        content = fence.group(1).strip()
    try:
        import json
        return json.loads(content)
    except json.JSONDecodeError:
        # Procura o primeiro { ... }
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if not match:
            return None
        try:
            import json
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None


# ---------- fábrica ----------


def build_text_composer(settings: Settings) -> TextComposer:
    """Fábrica: mock por padrão, llm se configurado."""
    if settings.llm_provider == "mock":
        return MockTextComposer()
    if not settings.llm_configured:
        logger.info("LLM provider=%s mas sem credenciais — caindo para mock.", settings.llm_provider)
        return MockTextComposer()
    try:
        return LLMTextComposer(settings)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Falha ao construir LLMTextComposer: %s — mock.", type(exc).__name__)
        return MockTextComposer()


__all__ = [
    "SlideContent",
    "ComposedCarousel",
    "TextComposer",
    "MockTextComposer",
    "LLMTextComposer",
    "build_text_composer",
    "VIRAL_ROLES",
    "viral_script_roles",
]
