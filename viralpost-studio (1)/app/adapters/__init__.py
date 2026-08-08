"""Adapters externos — interfaces abstratas + mocks + implementações reais.

Mudança v0.3:
- Removido o adapter ViralAI (não há API nem token; o goviral.ai é uma URL
  externa acessada manualmente pelo usuário via login Discord).
- Adicionado TextComposer: estrutura o texto colado pelo usuário em slides
  (mock determinístico ou LLM OpenAI-compatible).
- PinterestClient e RankingProvider mantidos.
"""

from __future__ import annotations

from .text_composer import (
    ComposedCarousel,
    LLMTextComposer,
    MockTextComposer,
    SlideContent,
    TextComposer,
    build_text_composer,
)
from .pinterest_client import (
    PinterestClient,
    MockPinterestClient,
    PinterestImage,
    build_pinterest_client,
)
from .ranking_provider import (
    InferenceRankingProvider,
    MockRankingProvider,
    RankingProvider,
    RankingResult,
    build_ranking_provider,
)

__all__ = [
    # TextComposer
    "ComposedCarousel",
    "SlideContent",
    "TextComposer",
    "MockTextComposer",
    "LLMTextComposer",
    "build_text_composer",
    # Pinterest
    "PinterestClient",
    "MockPinterestClient",
    "PinterestImage",
    "build_pinterest_client",
    # Ranking
    "InferenceRankingProvider",
    "MockRankingProvider",
    "RankingProvider",
    "RankingResult",
    "build_ranking_provider",
]
