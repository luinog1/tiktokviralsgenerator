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
    assert settings.image_provider == "auto"
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


def test_unsplash_without_a_key_fails_fast_and_offline(monkeypatch):
    """Só o modo combinado (unsplash_pinterest) constrói o cliente sem chave.
    A falha é local — sem gastar um round-trip fadado ao 401 — e o motivo diz
    "sem chave", não "chave recusada", que mandaria conferir uma chave que
    não existe."""
    from app.adapters.pinterest_client import UnsplashClient, is_mock_image

    def _explode(*a, **k):
        raise AssertionError("sem chave a busca não deveria ir à rede")

    monkeypatch.setattr("app.adapters.pinterest_client.requests.get", _explode)
    client = UnsplashClient(access_key="")
    images = client.search("cafe", limit=2)

    assert all(is_mock_image(img) for img in images)
    assert "UNSPLASH_ACCESS_KEY" in client.last_fallback_reason


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


def test_unsplash_advances_the_page_on_every_search(monkeypatch):
    """A mesma query devolvia sempre a página 1 — parecia cache, mas era a
    ordenação por relevância do Unsplash, que é estável.

    A página **avança** em vez de ser sorteada: um sorteio em 1..N repete a
    página anterior uma vez em cada N, e uma vez em cada N é o suficiente para
    o usuário ver a mesma foto em duas gerações seguidas. Andando em sequência,
    a janela inteira é gasta antes de qualquer repetição.
    """
    from app.adapters.pinterest_client import UnsplashClient

    pages: list[int] = []

    def _capture(*args, **kwargs):
        pages.append(kwargs["params"]["page"])
        return _FakeResponse(200, _unsplash_payload())

    monkeypatch.setattr("app.adapters.pinterest_client.requests.get", _capture)
    client = UnsplashClient(access_key="chave-boa")
    janela = UnsplashClient._PAGE_WINDOW
    for _ in range(janela):
        client.search("cafe da manha", limit=6)

    assert pages == list(range(1, janela + 1)), "a página não andou em sequência"

    # Fim da janela: volta à 1 (a relevância cai rápido depois dela).
    client.search("cafe da manha", limit=6)
    assert pages[-1] == 1


def test_unsplash_keeps_a_separate_page_per_query(monkeypatch):
    """O cursor é por query: o de "cafe" não pode empurrar "treino" para o meio
    do catálogo dele."""
    from app.adapters.pinterest_client import UnsplashClient

    pages: list[tuple[str, int]] = []

    def _capture(*args, **kwargs):
        params = kwargs["params"]
        pages.append((params["query"], params["page"]))
        return _FakeResponse(200, _unsplash_payload())

    monkeypatch.setattr("app.adapters.pinterest_client.requests.get", _capture)
    client = UnsplashClient(access_key="chave-boa")
    client.search("cafe da manha", limit=6)
    client.search("cafe da manha", limit=6)
    client.search("treino em casa", limit=6)

    assert pages == [
        ("cafe da manha", 1),
        ("cafe da manha", 2),
        ("treino em casa", 1),
    ]


def test_unsplash_retries_page_one_when_the_cursor_is_past_the_end(monkeypatch):
    """Query com pouco acervo: a página do cursor volta vazia e a busca precisa
    reentrar dentro do total_pages em vez de cair no gradiente mock."""
    from app.adapters.pinterest_client import UnsplashClient, is_mock_image
    from app.services import search_cursor

    calls: list[int] = []

    def _thin_catalog(*args, **kwargs):
        page = kwargs["params"]["page"]
        calls.append(page)
        if page > 1:
            return _FakeResponse(200, {"total": 1, "total_pages": 1, "results": []})
        return _FakeResponse(200, _unsplash_payload("only-one"))

    monkeypatch.setattr("app.adapters.pinterest_client.requests.get", _thin_catalog)
    search_cursor.save_cursor("unsplash_search", "termo raro", page=3)

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


def test_unsplash_requests_the_final_slide_size_at_high_quality(monkeypatch):
    from urllib.parse import parse_qs, urlsplit

    from app.adapters.pinterest_client import UnsplashClient

    payload = _unsplash_payload("high-quality")
    monkeypatch.setattr(
        "app.adapters.pinterest_client.requests.get",
        lambda *a, **k: _FakeResponse(200, payload),
    )

    image = UnsplashClient(
        access_key="chave-boa", target_size=(1080, 1350)
    ).search("smoothie", limit=1)[0]
    params = parse_qs(urlsplit(image.image_url).query)

    assert params["w"] == ["1080"]
    assert params["h"] == ["1350"]
    assert params["fit"] == ["crop"]
    assert params["q"] == ["85"]


# ---------- a regra do slide 1: o hook sozinho, numa caixa ----------


def test_mock_composer_leaves_the_hook_alone_on_the_first_slide():
    """A primeira foto mostra a frase do hook — sem apoio e sem CTA."""
    composer = MockTextComposer()
    carousel = composer.compose(
        "ninguém acorda às 5h por disciplina. acorda porque dormiu às 21h. "
        "comece pela hora de dormir. o resto se ajeita sozinho.",
        style="sticker",
        slides_count=3,
    )

    hook = carousel.slides[0]
    assert hook.role == "hook"
    assert hook.headline
    assert hook.body == ""
    assert hook.call_to_action == ""


def test_mock_composer_still_uses_two_boxes_on_the_other_slides():
    """A regra vale para o hook, não para o carrossel inteiro."""
    composer = MockTextComposer()
    carousel = composer.compose(
        "primeira frase do texto. segunda frase que explica. terceira frase. "
        "quarta frase com o exemplo. quinta frase fechando o assunto. "
        "sexta frase para o fim.",
        style="sticker",
        slides_count=3,
    )

    assert any(s.body for s in carousel.slides[1:])


def _pasted_script() -> str:
    """O formato em que o roteiro é colado: linha em branco entre as caixas,
    intervalo maior entre as imagens, e nenhum ponto final (é texto de sticker).
    """
    return (
        "ninguém acorda às 5h por disciplina\n"
        "\n\n"
        "acorda porque dormiu às 21h\n"
        "\n"
        "ninguém fala essa parte\n"
        "\n\n"
        "o corpo não negocia sono\n"
        "\n"
        "você só troca a hora da dívida\n"
        "\n\n"
        "salva pra começar amanhã\n"
        "\n"
        "e comenta que horas você dorme"
    )


def test_mock_composer_keeps_the_pasted_paragraphs_apart():
    """Sem isso TODOS os slides saíam com o texto colado inteiro.

    O `\\s{2,}` que limpava os espaços duplos deixados pelas hashtags incluía o
    `\\n`: as linhas em branco desapareciam, o texto virava um parágrafo só e o
    composer repetia esse parágrafo em rotação por todos os slides — inclusive
    no slide 1, que é o hook.
    """
    carousel = MockTextComposer().compose(
        _pasted_script(), style="sticker", slides_count=4
    )

    textos = [f"{s.headline} {s.body}".strip() for s in carousel.slides]
    assert len(set(textos)) == 4, textos


def test_mock_composer_gives_the_hook_only_the_first_paragraph():
    """O hook é o primeiro trecho e nada mais — nem o começo do slide 2."""
    carousel = MockTextComposer().compose(
        _pasted_script(), style="sticker", slides_count=4
    )

    hook = carousel.slides[0]
    assert hook.headline == "ninguém acorda às 5h por disciplina"
    assert hook.body == ""
    assert hook.call_to_action == ""


def test_mock_composer_maps_each_pasted_chunk_to_a_box():
    """Uma linha em branco no texto colado = a outra caixa da mesma imagem."""
    carousel = MockTextComposer().compose(
        _pasted_script(), style="sticker", slides_count=4
    )

    assert carousel.slides[1].headline == "acorda porque dormiu às 21h"
    assert carousel.slides[1].body == "ninguém fala essa parte"


def _llm_settings():
    return Settings.from_env({
        "LLM_PROVIDER": "openai_compatible",
        "LLM_API_BASE_URL": "https://api.groq.com/openai/v1",
        "LLM_API_KEY": "gsk_test",
        "LLM_MODEL": "llama-3.1-8b-instant",
    })


def _llm_reply(slides: list[dict]) -> _FakeResponse:
    import json
    content = json.dumps({"slides": slides, "hashtags": ["foco"], "caption": "legenda"})
    return _FakeResponse(200, {"choices": [{"message": {"content": content}}]})


def test_llm_hook_slide_is_one_box_even_when_the_model_writes_a_body(monkeypatch):
    """O prompt proíbe apoio no slide 1, mas o modelo desobedece — a regra do
    produto não pode depender de o modelo ter obedecido.

    O apoio que o modelo inventa é apagado, não colado à frase: colar inflava o
    hook com texto a mais (a informação continua nos outros slides). Diferente
    do roteiro manual, onde o apoio é texto do usuário e entra na caixa.
    """
    from app.adapters.text_composer import LLMTextComposer

    monkeypatch.setattr(
        "app.adapters.text_composer.requests.post",
        lambda *a, **k: _llm_reply([
            {"role": "hook", "headline": "ninguém acorda às 5h por disciplina",
             "body": "e ninguém fala essa parte", "call_to_action": "salva aí"},
            {"role": "value", "headline": "comece pela hora de dormir",
             "body": "o resto se ajeita", "call_to_action": ""},
            {"role": "cta", "headline": "agora é com você",
             "body": "", "call_to_action": "salva pra tentar amanhã"},
        ]),
    )

    carousel = LLMTextComposer(_llm_settings()).compose("texto", slides_count=3)

    hook = carousel.slides[0]
    assert hook.body == ""
    assert hook.call_to_action == ""
    # Só a frase do hook — o apoio desobediente não entra na caixa.
    assert hook.headline == "ninguém acorda às 5h por disciplina"
    assert carousel.slides[1].body == "o resto se ajeita"


def test_llm_hook_sent_in_the_body_field_still_becomes_the_hook(monkeypatch):
    """Modelo que inverte os campos (headline vazia, frase no body) não pode
    deixar o slide 1 em branco — o body vale como a frase nesse caso."""
    from app.adapters.text_composer import LLMTextComposer

    monkeypatch.setattr(
        "app.adapters.text_composer.requests.post",
        lambda *a, **k: _llm_reply([
            {"role": "hook", "headline": "", "body": "a frase que para o scroll"},
            {"role": "cta", "headline": "fecho", "call_to_action": "salva"},
        ]),
    )

    carousel = LLMTextComposer(_llm_settings()).compose("texto", slides_count=2)

    assert carousel.slides[0].headline == "a frase que para o scroll"
    assert carousel.slides[0].body == ""


def test_llm_first_slide_is_the_hook_whatever_role_the_model_returns(monkeypatch):
    from app.adapters.text_composer import LLMTextComposer

    monkeypatch.setattr(
        "app.adapters.text_composer.requests.post",
        lambda *a, **k: _llm_reply([
            {"role": "value", "headline": "a primeira frase", "body": "apoio"},
            {"role": "cta", "headline": "fecho", "call_to_action": "salva"},
        ]),
    )

    carousel = LLMTextComposer(_llm_settings()).compose("texto", slides_count=2)

    assert carousel.slides[0].role == "hook"
    assert carousel.slides[0].body == ""
    # O papel virou hook, então o apoio segue a regra do LLM: apagado.
    assert carousel.slides[0].headline == "a primeira frase"


def test_llm_hook_is_not_cut_at_the_headline_limit(monkeypatch):
    """A caixa do hook cabe 160 caracteres; cortar em 70 alterava a frase.

    O corte era aplicado antes de o slide ser reconhecido como hook, então uma
    frase de 80 caracteres voltava com "…" no meio — texto alterado sem que a
    caixa precisasse disso.
    """
    from app.adapters.text_composer import HOOK_TEXT_LIMIT, LLMTextComposer

    hook = "ninguém acorda às cinco da manhã por disciplina e essa é a parte que ninguém conta"
    assert 70 < len(hook) <= HOOK_TEXT_LIMIT
    monkeypatch.setattr(
        "app.adapters.text_composer.requests.post",
        lambda *a, **k: _llm_reply([
            {"role": "hook", "headline": hook},
            {"role": "cta", "headline": "fecho", "call_to_action": "salva"},
        ]),
    )

    carousel = LLMTextComposer(_llm_settings()).compose("texto", slides_count=2)

    assert carousel.slides[0].headline == hook
    # A regra do corte continua valendo nos outros slides.
    assert len(carousel.slides[1].headline) <= 70


@pytest.mark.parametrize("first_slide", [
    {"role": "hook", "headline": "a frase", "body": "apoio", "call_to_action": "cta"},
    {"role": "hook", "headline": "", "body": "a frase veio no campo errado"},
    {"role": "value", "headline": "sem papel de hook", "body": "apoio"},
    {"role": "hook", "headline": "   ", "body": "só o body tem texto"},
])
def test_llm_first_slide_never_comes_out_without_text(monkeypatch, first_slide):
    """A imagem 1 é a única que ninguém desliza sem ler — vazia é o pior caso.

    Cada variação é uma forma de o modelo desobedecer ao prompt do slide 1.
    Nenhuma delas pode terminar em caixa vazia.
    """
    from app.adapters.text_composer import LLMTextComposer

    monkeypatch.setattr(
        "app.adapters.text_composer.requests.post",
        lambda *a, **k: _llm_reply([
            first_slide,
            {"role": "cta", "headline": "fecho", "call_to_action": "salva"},
        ]),
    )

    carousel = LLMTextComposer(_llm_settings()).compose(
        "o texto colado do goviral, com uma frase que serve de reserva.",
        slides_count=2,
    )

    assert carousel.slides[0].role == "hook"
    assert carousel.slides[0].headline.strip()


def test_the_prompt_spells_out_the_hook_rule_and_the_role_order():
    from app.adapters.text_composer import _build_viral_prompt

    prompt = _build_viral_prompt(6, "pt-BR", viral_script_roles(6))

    assert "hook" in prompt.lower()
    assert "VAZIO no slide 1" in prompt
    assert "hook → problem → agitation" in prompt
    assert "pt-BR" in prompt


def test_the_token_budget_grows_with_the_number_of_slides(monkeypatch):
    """Com o teto fixo de antes, o JSON de 12 slides chegava cortado e o
    carrossel inteiro caía no mock sem dizer por quê."""
    from app.adapters.text_composer import LLMTextComposer

    budgets: list[int] = []

    def _capture(*args, **kwargs):
        budgets.append(kwargs["json"]["max_tokens"])
        return _llm_reply([{"role": "hook", "headline": "frase"}])

    monkeypatch.setattr("app.adapters.text_composer.requests.post", _capture)
    composer = LLMTextComposer(_llm_settings())
    composer.compose("texto", slides_count=3)
    composer.compose("texto", slides_count=12)

    small, large = budgets
    assert large > small
    assert large >= 12 * 90


def test_unsplash_shortens_the_query_when_it_finds_nothing(monkeypatch):
    """Medido em produção: `lifestyle cozy #aesthetic #praia #vibe bellebres
    girly aesthetic lifestyle travel interior workspace` devolvia 0 imagens. E
    0 imagens cai no mock, que é DETERMINÍSTICO por query — a mesma hashtag
    passava a devolver os mesmos gradientes para sempre."""
    from app.adapters.pinterest_client import UnsplashClient, is_mock_image

    queries: list[str] = []

    def _only_short_queries_work(*args, **kwargs):
        query = kwargs["params"]["query"]
        queries.append(query)
        if len(query.split()) > 6:
            return _FakeResponse(200, {"total": 0, "total_pages": 0, "results": []})
        return _FakeResponse(200, _unsplash_payload("achou"))

    monkeypatch.setattr(
        "app.adapters.pinterest_client.requests.get", _only_short_queries_work
    )

    images = UnsplashClient(access_key="chave-boa").search(
        "lifestyle cozy #aesthetic #praia #vibe bellebres girly "
        "aesthetic lifestyle travel interior workspace",
        limit=6,
    )

    assert len(images) == 1
    assert not is_mock_image(images[0])
    assert "#" not in queries[0] and "praia" in queries[0]
    assert len(queries[-1].split()) <= 6


def test_unsplash_says_why_when_even_the_short_query_finds_nothing(monkeypatch):
    """O motivo tem que chegar à prévia: gradiente sem explicação é o que faz
    parecer que o app cacheou o resultado."""
    from app.adapters.pinterest_client import UnsplashClient, is_mock_image

    monkeypatch.setattr(
        "app.adapters.pinterest_client.requests.get",
        lambda *a, **k: _FakeResponse(200, {"total": 0, "total_pages": 0, "results": []}),
    )

    client = UnsplashClient(access_key="chave-boa")
    images = client.search("termo que nao existe em lugar nenhum", limit=4)

    assert all(is_mock_image(img) for img in images)
    assert "não tem fotos" in client.last_fallback_reason


def test_unsplash_leaves_recently_used_photos_for_last(monkeypatch):
    """A fonte ativa em produção é o Unsplash — sem isto a memória de fotos só
    valeria para quem usa pinterest_scrape."""
    from app.adapters.pinterest_client import UnsplashClient, media_identity

    payload = {"total": 3, "total_pages": 1, "results": [
        {
            "id": f"foto-{i}",
            "urls": {"regular": f"https://images.unsplash.com/photo-{i}.jpg"},
            "links": {"html": f"https://unsplash.com/photos/foto-{i}"},
            "alt_description": "cafe",
            "user": {"name": "A", "username": "a"},
        }
        for i in range(3)
    ]}
    monkeypatch.setattr(
        "app.adapters.pinterest_client.requests.get",
        lambda *a, **k: _FakeResponse(200, payload),
    )

    ja_usadas = [media_identity("https://images.unsplash.com/photo-0.jpg")]
    images = UnsplashClient(access_key="chave-boa", avoid_media=ja_usadas).search(
        "cafe", limit=2
    )

    assert [img.image_id for img in images] == ["foto-1", "foto-2"]


def test_unsplash_asks_for_more_photos_than_the_carousel_uses(monkeypatch):
    """A galeria da prévia precisa de alternativas, e a memória precisa de
    folga para ter o que preferir."""
    from app.adapters.pinterest_client import UnsplashClient

    per_pages: list[int] = []

    def _capture(*args, **kwargs):
        per_pages.append(kwargs["params"]["per_page"])
        return _FakeResponse(200, _unsplash_payload())

    monkeypatch.setattr("app.adapters.pinterest_client.requests.get", _capture)
    UnsplashClient(access_key="chave-boa").search("cafe", limit=6)

    assert per_pages[0] == 12
