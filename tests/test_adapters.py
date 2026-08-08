"""Testes dos adapters — TextComposer, Pinterest mock e Ranking."""

from __future__ import annotations

import pytest

from app.adapters import (
    MockPinterestClient,
    MockRankingProvider,
    MockTextComposer,
)
from app.adapters.pinterest_client import PinterestImage
from app.adapters.text_composer import viral_script_roles
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


# ---------- Roteiro viral ----------


@pytest.mark.parametrize("n", [1, 2, 3, 4, 5, 6, 9, 12])
def test_viral_roles_have_exact_length(n):
    roles = viral_script_roles(n)
    assert len(roles) == n


@pytest.mark.parametrize("n", [3, 6, 9, 12])
def test_viral_roles_open_with_hook_and_close_with_cta(n):
    roles = viral_script_roles(n)
    assert roles[0] == "hook"
    assert roles[-1] == "cta"


def test_viral_roles_full_structure_for_six_slides():
    assert viral_script_roles(6) == [
        "hook", "problem", "agitation", "value", "proof", "cta",
    ]


def test_mock_composer_assigns_viral_roles_in_order():
    composer = MockTextComposer()
    text = (
        "Você posta todo dia e não cresce. O problema não é o algoritmo. "
        "É que seu primeiro segundo não prende ninguém. "
        "Comece pelo conflito, não pelo contexto. "
        "Testei em 30 vídeos e o tempo de exibição subiu 450%. "
        "Salva esse post para aplicar hoje."
    )
    carousel = composer.compose(text, style="sticker", slides_count=6)
    roles = [s.role for s in carousel.slides]
    assert roles == ["hook", "problem", "agitation", "value", "proof", "cta"]


def test_mock_composer_puts_cta_only_on_last_slide():
    """CTA repetido em todo slide polui o carrossel — só o fecho leva."""
    composer = MockTextComposer()
    carousel = composer.compose(
        "Primeira ideia aqui. Segunda ideia aqui. Terceira ideia aqui. "
        "Quarta ideia. Quinta ideia. Sexta ideia final.",
        style="sticker",
        slides_count=6,
    )
    assert carousel.slides[-1].call_to_action
    assert all(not s.call_to_action for s in carousel.slides[:-1])


def test_mock_composer_does_not_duplicate_headline_in_body():
    """Headline e body iguais fazem o slide mostrar a mesma frase duas vezes."""
    composer = MockTextComposer()
    carousel = composer.compose(
        "Primeira frase do slide. Segunda frase com o detalhe. "
        "Terceira frase encerrando o assunto.",
        style="sticker",
        slides_count=3,
    )
    for slide in carousel.slides:
        assert slide.body != slide.headline
        if slide.body:
            assert not slide.body.startswith(slide.headline)


def test_slide_content_roundtrips_role_through_dict():
    """O papel precisa sobreviver ao store/edição, senão o layout se perde."""
    composer = MockTextComposer()
    carousel = composer.compose("Texto de teste com tamanho suficiente.", slides_count=3)
    for slide in carousel.slides:
        assert slide.to_dict()["role"] == slide.role


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


def test_settings_auto_detects_llm_when_key_and_base_set():
    """Se o usuário definir LLM_API_KEY e LLM_API_BASE_URL mas esquecer
    LLM_PROVIDER (deixar como mock), a aplicação deve auto-detectar e usar
    openai_compatible — evita o bug comum de "configurei tudo mas continua em mock".
    """
    env = {
        "LLM_PROVIDER": "mock",  # usuário esqueceu de mudar
        "LLM_API_BASE_URL": "https://api.groq.com/openai/v1",
        "LLM_API_KEY": "gsk_test",
        "LLM_MODEL": "llama-3.1-8b-instant",
    }
    settings = Settings.from_env(env)
    assert settings.llm_provider == "openai_compatible"
    assert settings.llm_configured is True


def test_settings_does_not_auto_detect_when_only_key_set():
    """Se só tiver LLM_API_KEY mas não LLM_API_BASE_URL, não ativa LLM."""
    env = {
        "LLM_PROVIDER": "mock",
        "LLM_API_KEY": "gsk_test",
    }
    settings = Settings.from_env(env)
    assert settings.llm_provider == "mock"


def test_settings_respects_explicit_mock_even_with_creds():
    """Se o usuário explicitamente colocar mock e NÃO definir key/base,
    deve continuar em mock mesmo que a key esteja definida no ambiente."""
    # Este teste valida que a auto-detecção só ativa quando AMBAS
    # key e base_url estão definidas
    env = {"LLM_PROVIDER": "mock", "LLM_API_BASE_URL": "https://api.groq.com/openai/v1"}
    settings = Settings.from_env(env)
    assert settings.llm_provider == "mock"  # sem key, não ativa
