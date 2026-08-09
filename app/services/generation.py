"""Orquestração: text composer + Pinterest + ranking.

Mudança v0.3: o usuário cola o texto do goviral.ai (URL externa, sem API/token).
A função deste serviço é estruturar o texto em slides, buscar imagens no Pinterest,
ranquear por relevância e preparar a estrutura para o SlideRenderer.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from app.adapters import (
    PinterestClient,
    PinterestImage,
    RankingProvider,
    TextComposer,
    build_pinterest_client,
    build_ranking_provider,
    build_text_composer,
)
from app.adapters.pinterest_client import is_mock_image
from app.config import Settings
from app.services.session_store import SessionStore, StoredProject, get_store

logger = logging.getLogger(__name__)


@dataclass
class GenerationOutcome:
    """Resultado da execução do fluxo de geração."""

    project: StoredProject
    warnings: list[str]

    @property
    def project_id(self) -> str:
        return self.project.project_id


class GenerationService:
    """Ponto único de orquestração do carrossel."""

    def __init__(self, settings: Settings):
        self._settings = settings
        self._composer: TextComposer = build_text_composer(settings)
        self._pinterest: PinterestClient = build_pinterest_client(settings)
        self._ranking: RankingProvider = build_ranking_provider(settings)
        self._store: SessionStore = get_store(settings.session_ttl_minutes)

    # ---- getters de diagnóstico ----
    @property
    def composer_name(self) -> str:
        return getattr(self._composer, "name", "unknown")

    @property
    def pinterest_provider_name(self) -> str:
        return getattr(self._pinterest, "name", "unknown")

    @property
    def ranking_provider_name(self) -> str:
        return getattr(self._ranking, "name", "unknown")

    def store(self) -> SessionStore:
        return self._store

    # ---- fluxo principal ----
    def run(
        self,
        *,
        raw_text: str,
        theme: str,
        niche: str = "",
        keywords: list[str] | None = None,
        style: str = "quote",
        slides_count: int = 6,
        language: str = "pt-BR",
    ) -> GenerationOutcome:
        warnings: list[str] = []

        if self._settings.llm_provider == "mock":
            warnings.append("Composição em modo mock — sem chamada real ao LLM.")

        # 1. Compor carrossel a partir do texto colado
        carousel = self._composer.compose(
            raw_text,
            style=style,
            slides_count=slides_count,
            extra={"theme": theme, "language": language},
        )

        if not carousel.slides:
            warnings.append("Nenhum slide gerado — texto colado está vazio ou inválido.")

        # 2. Buscar imagens no Pinterest
        query = self._build_query(theme, niche, keywords, raw_text)
        try:
            images = self._pinterest.search(query, limit=max(slides_count, 6))
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Pinterest search falhou: %s", type(exc).__name__)
            warnings.append("Busca de imagens falhou — sem resultados.")
            images = []

        if not images:
            warnings.append("Nenhuma imagem retornada pela busca.")
        elif any(is_mock_image(img) for img in images):
            # Cuidado: um cliente real que caiu no fallback continua se chamando
            # "unsplash"/"pinterest_v5" — por isso a checagem é no resultado.
            reason = getattr(self._pinterest, "last_fallback_reason", "")
            detail = reason or (
                "Nenhuma chave de imagens configurada — defina "
                "UNSPLASH_ACCESS_KEY ou PINTEREST_ACCESS_TOKEN."
            )
            warnings.append(
                f"Imagens em modo mock (gradientes sintéticos). Motivo: {detail}"
            )
            logger.warning("Carrossel gerado com imagens mock. Motivo: %s", detail)

        # 3. Ranking (opcional) — briefing inclui raw_text para correlação
        briefing = {
            "theme": theme,
            "niche": niche,
            "keywords": keywords or [],
            "raw_text": raw_text[:600],
            "style": style,
        }
        ranking_results = self._rank_safely(briefing, images, warnings)
        ordered_images = self._merge_ranking(images, ranking_results)

        # 4. Persistir
        project = self._store.create(
            briefing=briefing,
            carousel=carousel.to_dict(),
            images=[img.to_dict() for img in ordered_images],
            ranking=[r.to_dict() for r in ranking_results],
            style=style,
            slides_count=slides_count,
            raw_text=raw_text,
        )
        return GenerationOutcome(project=project, warnings=warnings)

    # ---- helpers ----
    @staticmethod
    def _build_query(
        theme: str,
        niche: str,
        keywords: list[str] | None,
        raw_text: str,
    ) -> str:
        parts: list[str] = []
        if theme:
            parts.append(theme.strip())
        if niche:
            parts.append(niche.strip())
        if keywords:
            parts.extend(str(k).strip() for k in keywords if str(k).strip())
        # Adicionar primeiras 3 palavras significativas do raw_text
        if raw_text and not parts:
            for word in raw_text.split()[:5]:
                word = word.strip(".,;:!?\"'()[]")
                if len(word) >= 4:
                    parts.append(word)
                if len(parts) >= 3:
                    break
        query = " ".join(p for p in parts if p)
        return query or "viral"

    def _rank_safely(
        self,
        briefing: dict[str, Any],
        images: list[PinterestImage],
        warnings: list[str],
    ) -> list[Any]:
        if not self._settings.ranking_enabled:
            warnings.append("Ranking desativado — ordem original mantida.")
            return []
        try:
            return self._ranking.rank(briefing, images)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Ranking falhou (%s) — usando ordem original.", type(exc).__name__)
            warnings.append("Ranking indisponível — ordem original mantida.")
            return []

    @staticmethod
    def _merge_ranking(
        images: list[PinterestImage], ranking: list[Any]
    ) -> list[PinterestImage]:
        if not ranking:
            return images
        score_map = {r.image_id: r.score for r in ranking}
        return sorted(images, key=lambda img: score_map.get(img.image_id, 0.0), reverse=True)
