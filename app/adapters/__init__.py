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
    viral_script_roles,
)
from .pinterest_client import (
    PinterestClient,
    MockPinterestClient,
    PinterestImage,
    PinterestScrapeClient,
    build_pinterest_client,
    pinterest_scrape_available,
)
from .ranking_provider import (
    InferenceRankingProvider,
    MockRankingProvider,
    RankingProvider,
    RankingResult,
    build_ranking_provider,
)
from .vision_provider import (
    VisionRankingProvider,
    VisionVerdict,
    build_vision_provider,
)
from .script_parser import (
    blocks_from_slides,
    compose_from_blocks,
    parse_manual_script,
    split_blocks,
)

__all__ = [
    # TextComposer
    "ComposedCarousel",
    "SlideContent",
    "TextComposer",
    "MockTextComposer",
    "LLMTextComposer",
    "build_text_composer",
    "viral_script_roles",
    # Pinterest
    "PinterestClient",
    "MockPinterestClient",
    "PinterestImage",
    "PinterestScrapeClient",
    "build_pinterest_client",
    "pinterest_scrape_available",
    # Ranking
    "InferenceRankingProvider",
    "MockRankingProvider",
    "RankingProvider",
    "RankingResult",
    "build_ranking_provider",
    # Vision (VLM) — ranking olhando a foto + posição do texto
    "VisionRankingProvider",
    "VisionVerdict",
    "build_vision_provider",
]
