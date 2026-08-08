"""Ranking de imagens — opcional, com fallback determinístico.

Mudança v0.3: usa as mesmas credenciais do LLM composer (LLM_API_BASE_URL,
LLM_API_KEY, LLM_MODEL). Compatibilidade reversa com RANKING_*.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any, Iterable, Protocol

import requests

from app.config import Settings
from app.adapters.pinterest_client import PinterestImage

logger = logging.getLogger(__name__)


@dataclass
class RankingResult:
    """Resultado de ranking para uma imagem."""

    image_id: str
    score: float
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "image_id": self.image_id,
            "score": round(self.score, 4),
            "reason": self.reason,
        }


class RankingProvider(Protocol):
    """Interface para ranking de imagens."""

    name: str

    def rank(
        self, briefing: dict[str, Any], images: list[PinterestImage]
    ) -> list[RankingResult]:  # pragma: no cover
        ...


class MockRankingProvider:
    """Ranking determinístico baseado em sobreposição textual simples.

    Funciona sem rede e sem credenciais.
    """

    name = "mock"

    def rank(
        self, briefing: dict[str, Any], images: list[PinterestImage]
    ) -> list[RankingResult]:
        # Após a refatoração, o "briefing" contém o texto colado em 'raw_text'.
        # Usamos essa string + keywords para correlação textual.
        theme = str(briefing.get("theme") or "").lower()
        keywords = [str(k).lower() for k in (briefing.get("keywords") or []) if k]
        raw_text = str(briefing.get("raw_text") or "").lower()
        corpus_tokens = {theme, *keywords}
        # Tokens do texto colado (até 8 mais relevantes por frequência)
        for token in raw_text.split():
            token = token.strip(".,;:!?\"'()[]")
            if len(token) >= 4:
                corpus_tokens.add(token)
        corpus_tokens.discard("")

        if not corpus_tokens:
            return [
                RankingResult(
                    image_id=img.image_id,
                    score=0.5 + (i % 5) * 0.07,
                    reason="Ordem original (sem briefing para correlacionar).",
                )
                for i, img in enumerate(images)
            ]

        scored: list[RankingResult] = []
        for img in images:
            text = f"{img.title} {img.description}".lower()
            hits = sum(1 for token in corpus_tokens if token and token in text)
            score = 0.3 + 0.05 * hits
            score = min(score, 0.98)
            reason = (
                f"Correlação textual com briefing ({hits} token(s) em comum)."
                if hits > 0
                else "Sem correlação textual direta; ordem preservada."
            )
            scored.append(RankingResult(image_id=img.image_id, score=score, reason=reason))

        return scored


class InferenceRankingProvider:
    """Ranking via endpoint OpenAI-compatible (Groq, OpenAI, etc.).

    Envia apenas metadados textuais — nunca imagem binária.
    """

    name = "inference"

    def __init__(self, settings: Settings):
        self._settings = settings
        self._timeout = settings.request_timeout_seconds
        self._base = settings.llm_api_base_url.rstrip("/")
        self._key = settings.llm_api_key
        self._model = settings.llm_model or "llama-3.1-8b-instant"

    def rank(
        self, briefing: dict[str, Any], images: list[PinterestImage]
    ) -> list[RankingResult]:
        if not self._settings.llm_configured or self._settings.llm_provider == "mock":
            return MockRankingProvider().rank(briefing, images)

        system_prompt = (
            "Você avalia relevância de imagens para um carrossel. "
            "Recebe um briefing textual e uma lista de imagens candidatas. "
            "Para cada imagem, retorne score de 0 a 1 (1 = perfeitamente relevante) "
            "e uma razão curta (máx 100 chars). "
            'Responda APENAS JSON: {"results":[{"image_id":"","score":0.0,"reason":""}]}.'
        )

        user_payload = {
            "briefing": {
                "theme": briefing.get("theme"),
                "raw_text": (briefing.get("raw_text") or "")[:600],
                "keywords": briefing.get("keywords"),
                "style": briefing.get("style"),
            },
            "candidates": [
                {
                    "image_id": img.image_id,
                    "title": img.title,
                    "description": img.description[:200],
                }
                for img in images
            ],
        }

        try:
            import json
            response = requests.post(
                f"{self._base}/chat/completions",
                json={
                    "model": self._model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
                    ],
                    "temperature": 0.2,
                    "max_tokens": 800,
                },
                headers={
                    "Authorization": f"Bearer {self._key}",
                    "Content-Type": "application/json",
                },
                timeout=self._timeout,
            )
            # Log explícito se 4xx — ajuda a diagnosticar modelo inválido
            if response.status_code >= 400:
                logger.warning(
                    "Ranking endpoint HTTP %d: %s",
                    response.status_code,
                    response.text[:300],
                )
            response.raise_for_status()
        except requests.Timeout:
            logger.warning("Ranking endpoint timeout — fallback mock.")
            return MockRankingProvider().rank(briefing, images)
        except requests.RequestException as exc:
            logger.warning("Ranking endpoint erro: %s — fallback mock.", type(exc).__name__)
            return MockRankingProvider().rank(briefing, images)

        try:
            data = response.json() or {}
            content = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
            parsed = _parse_json_loose(content)
        except (ValueError, KeyError, IndexError) as exc:
            logger.warning("Ranking JSON inválido (%s) — fallback mock.", type(exc).__name__)
            return MockRankingProvider().rank(briefing, images)

        if not parsed:
            return MockRankingProvider().rank(briefing, images)

        results_raw: Iterable[dict[str, Any]] = parsed.get("results") or []
        parsed_results: list[RankingResult] = []
        seen_ids: set[str] = set()
        for item in results_raw:
            image_id = str(item.get("image_id") or "")
            if not image_id or image_id in seen_ids:
                continue
            seen_ids.add(image_id)
            score_raw = item.get("score", 0)
            try:
                score = float(score_raw)
            except (TypeError, ValueError):
                score = 0.0
            if math.isnan(score) or math.isinf(score):
                score = 0.0
            score = max(0.0, min(1.0, score))
            parsed_results.append(
                RankingResult(
                    image_id=image_id,
                    score=score,
                    reason=str(item.get("reason") or "")[:200],
                )
            )

        covered = {r.image_id for r in parsed_results}
        for img in images:
            if img.image_id not in covered:
                parsed_results.append(
                    RankingResult(
                        image_id=img.image_id,
                        score=0.0,
                        reason="Sem retorno do endpoint — fallback preservado.",
                    )
                )

        return parsed_results


def _parse_json_loose(content: str) -> dict[str, Any] | None:
    """Tenta extrair JSON mesmo se o modelo cercar com texto/markdown."""
    if not content:
        return None
    import json
    import re
    content = content.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", content, re.DOTALL)
    if fence:
        content = fence.group(1).strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if not match:
            return None
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None


def build_ranking_provider(settings: Settings) -> RankingProvider:
    """Fábrica de ranking — respeita LLM_PROVIDER e RANKING_ENABLED."""
    if not settings.ranking_enabled:
        return MockRankingProvider()
    if settings.llm_provider == "mock":
        return MockRankingProvider()
    try:
        return InferenceRankingProvider(settings)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Falha ao construir inference provider: %s — mock.", type(exc).__name__)
        return MockRankingProvider()
