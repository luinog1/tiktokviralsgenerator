"""Testes dos adapters — TextComposer, Pinterest mock e Ranking."""

from __future__ import annotations

import pytest

from app.adapters import (
    MockPinterestClient,
    MockRankingProvider,
    MockTextComposer,
)
from app.adapters.pinterest_client import PinterestImage
from app.config import Settings


# ---------- TextComposer ----------


def test_mock_composer_splits_into_slides():
    composer = MockTextComposer()
    text = (
        "5 dicas para uma rotina matinal produtiva.\n"
        "1. Acorde cedo e beba água.\n"
        "2. Faça exercício por 15 minutos.\n"
        "3. Escreva 3 prioridades do dia.\n"
        "4. Evite redes sociais na primeira hora.\n"
        "5. Tome um café da manhã nutritivo.\n\n"
        "#produtividade #rotina"
    )
    carousel = composer.compose(text, style="list", slides_count=5)
    assert carousel.provider == "mock"
    assert len(carousel.slides) == 5
    assert all(s.headline for s in carousel.slides)
    assert "produtividade" in carousel.hashtags
    assert carousel.caption


def test_mock_composer_handles_short_text():
    """Mesmo com pouco conteúdo, o composer deve gerar o número solicitado de slides
    (repetindo os chunks em rotação se necessário)."""
    composer = MockTextComposer()
    carousel = composer.compose("Texto curto.", style="quote", slides_count=6)
    assert len(carousel.slides) == 6
    # Todos os slides devem ter headline
    assert all(s.headline for s in carousel.slides)


def test_mock_composer_empty_text_returns_empty():
    composer = MockTextComposer()
    carousel = composer.compose("", style="quote", slides_count=6)
    assert carousel.slides == []
    assert carousel.hashtags == []


def test_mock_composer_strips_hashtags_from_body():
    composer = MockTextComposer()
    carousel = composer.compose(
        "Texto com hashtag no final. #foco #habitos",
        style="quote",
        slides_count=3,
    )
    assert "foco" in carousel.hashtags
    assert "habitos" in carousel.hashtags
    # As hashtags não devem aparecer no body
    for slide in carousel.slides:
        assert "#foco" not in slide.body
        assert "#habitos" not in slide.body


# ---------- Pinterest ----------


def test_mock_pinterest_returns_svg_data_uri():
    client = MockPinterestClient()
    images = client.search("café", limit=4)
    assert len(images) == 4
    for img in images:
        assert img.image_url.startswith("data:image/svg+xml")
        assert img.source_url.startswith("https://www.pinterest.com")


# ---------- Ranking ----------


def test_mock_ranking_uses_raw_text_for_correlation():
    provider = MockRankingProvider()
    briefing = {
        "theme": "café",
        "keywords": ["latte"],
        "raw_text": "manhã cheia de energia e latte para começar o dia",
    }
    images = [
        PinterestImage(image_id="1", image_url="", source_url="", title="Latte da manhã", description=""),
        PinterestImage(image_id="2", image_url="", source_url="", title="Paisagem genérica", description="sem termos"),
    ]
    results = provider.rank(briefing, images)
    assert len(results) == 2
    r1 = next(r for r in results if r.image_id == "1")
    r2 = next(r for r in results if r.image_id == "2")
    assert r1.score > r2.score


def test_mock_ranking_without_corpus_returns_default():
    provider = MockRankingProvider()
    images = [PinterestImage(image_id=str(i), image_url="", source_url="", title="", description="") for i in range(3)]
    results = provider.rank({"theme": "", "raw_text": ""}, images)
    assert len(results) == 3


# ---------- Settings ----------


def test_settings_factory_picks_mock_when_no_token():
    settings = Settings.from_env({})
    assert settings.pinterest_configured is False
    assert settings.llm_provider == "mock"
    assert settings.llm_configured is True  # mock é "configurado" por definição


def test_settings_factory_picks_openai_compatible_when_configured():
    env = {
        "LLM_PROVIDER": "openai_compatible",
        "LLM_API_BASE_URL": "https://api.groq.com/openai/v1",
        "LLM_API_KEY": "gsk_test",
        "LLM_MODEL": "llama-3.1-8b-instant",
    }
    settings = Settings.from_env(env)
    assert settings.llm_provider == "openai_compatible"
    assert settings.llm_configured is True


def test_settings_factory_inference_without_creds_is_unconfigured():
    env = {"LLM_PROVIDER": "openai_compatible"}
    settings = Settings.from_env(env)
    assert settings.llm_configured is False


def test_settings_backward_compat_with_ranking_legacy():
    """Variáveis RANKING_* antigas ainda funcionam (compatibilidade reversa)."""
    env = {
        "RANKING_PROVIDER": "inference",
        "RANKING_API_BASE_URL": "https://api.groq.com/openai/v1",
        "RANKING_API_KEY": "gsk_test",
        "RANKING_MODEL": "llama-3.1-8b-instant",
    }
    settings = Settings.from_env(env)
    assert settings.llm_provider == "openai_compatible"
    assert settings.llm_api_base_url == "https://api.groq.com/openai/v1"
    assert settings.llm_model == "llama-3.1-8b-instant"


def test_settings_slide_dimensions():
    settings = Settings.from_env({"SLIDE_WIDTH": "1080", "SLIDE_HEIGHT": "1350"})
    assert settings.slide_width == 1080
    assert settings.slide_height == 1350
