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


# ---------- Fallback silencioso para mock ----------


class _FakeResponse:
    """Resposta HTTP mínima para simular erro da API sem tocar a rede."""

    def __init__(self, status_code: int, payload: dict | None = None):
        self.status_code = status_code
        self.text = str(payload or "")
        self._payload = payload or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)


def test_unsplash_403_falls_back_to_mock_with_a_reason(monkeypatch):
    """O caso que não aparecia: a chave está configurada, o cliente é o real,
    mas a API recusa e o carrossel sai com gradiente. Antes isso era silencioso
    — só um logger.warning que ninguém lê no painel do Render."""
    from app.adapters.pinterest_client import UnsplashClient, is_mock_image

    client = UnsplashClient(access_key="chave-valida-mas-limitada")
    monkeypatch.setattr(
        "app.adapters.pinterest_client.requests.get",
        lambda *a, **k: _FakeResponse(403, {"errors": ["Rate Limit Exceeded"]}),
    )

    images = client.search("cafe da manha", limit=4)

    assert images, "o fallback deve devolver imagens, não lista vazia"
    assert all(is_mock_image(img) for img in images)
    assert client.name == "unsplash", "o nome do cliente segue sendo o real"
    assert "403" in client.last_fallback_reason
    assert "Demo" in client.last_fallback_reason


def test_unsplash_401_explains_the_wrong_key(monkeypatch):
    from app.adapters.pinterest_client import UnsplashClient

    client = UnsplashClient(access_key="secret-key-em-vez-de-access-key")
    monkeypatch.setattr(
        "app.adapters.pinterest_client.requests.get",
        lambda *a, **k: _FakeResponse(401, {"errors": ["OAuth error"]}),
    )
    client.search("qualquer", limit=2)
    assert "Access Key" in client.last_fallback_reason


def _unsplash_payload(photo_id: str = "abc123") -> dict:
    return {
        "total": 400,
        "total_pages": 40,
        "results": [{
            "id": photo_id,
            "urls": {"regular": f"https://images.unsplash.com/{photo_id}.jpg"},
            "links": {"html": f"https://unsplash.com/photos/{photo_id}"},
            "alt_description": "cafe",
            "user": {"name": "Alguem", "username": "alguem"},
        }],
    }


def test_unsplash_rotates_pages_across_searches(monkeypatch):
    """A mesma query devolvia sempre a página 1 — parecia cache, mas era a
    ordenação por relevância do Unsplash, que é estável. Sortear a página é o
    que renova as fotos sem o usuário mudar os termos."""
    from app.adapters.pinterest_client import UnsplashClient

    pages: list[int] = []

    def _capture(*args, **kwargs):
        pages.append(kwargs["params"]["page"])
        return _FakeResponse(200, _unsplash_payload())

    monkeypatch.setattr("app.adapters.pinterest_client.requests.get", _capture)
    client = UnsplashClient(access_key="chave-boa")
    for _ in range(40):
        client.search("cafe da manha", limit=6)

    assert len(set(pages)) > 1, "a página não variou entre buscas iguais"
    assert all(1 <= p <= UnsplashClient._PAGE_WINDOW for p in pages)


def test_unsplash_retries_page_one_when_the_drawn_page_is_past_the_end(monkeypatch):
    """Query com pouco acervo: a página sorteada volta vazia e a busca precisa
    reentrar dentro do total_pages em vez de cair no gradiente mock."""
    from app.adapters.pinterest_client import UnsplashClient, is_mock_image

    calls: list[int] = []

    def _thin_catalog(*args, **kwargs):
        page = kwargs["params"]["page"]
        calls.append(page)
        if page > 1:
            return _FakeResponse(200, {"total": 1, "total_pages": 1, "results": []})
        return _FakeResponse(200, _unsplash_payload("only-one"))

    monkeypatch.setattr("app.adapters.pinterest_client.requests.get", _thin_catalog)
    monkeypatch.setattr("app.adapters.pinterest_client.random.randint", lambda a, b: 4)

    images = UnsplashClient(access_key="chave-boa").search("termo raro", limit=6)

    assert calls == [4, 1]
    assert len(images) == 1
    assert not is_mock_image(images[0])


def test_successful_unsplash_search_leaves_no_fallback_reason(monkeypatch):
    from app.adapters.pinterest_client import UnsplashClient, is_mock_image

    payload = {"results": [{
        "id": "abc123",
        "urls": {"regular": "https://images.unsplash.com/photo-1.jpg"},
        "links": {"html": "https://unsplash.com/photos/abc123"},
        "alt_description": "cafe",
        "user": {"name": "Alguem", "username": "alguem"},
    }]}
    monkeypatch.setattr(
        "app.adapters.pinterest_client.requests.get",
        lambda *a, **k: _FakeResponse(200, payload),
    )
    client = UnsplashClient(access_key="chave-boa")
    images = client.search("cafe", limit=4)

    assert len(images) == 1
    assert not is_mock_image(images[0])
    assert client.last_fallback_reason == ""
