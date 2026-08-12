"""Testes do Pinterest sem token — o cliente que fala com o `pinterest-dl`.

Nenhum teste toca a rede: a biblioteca é injetada por um fake que devolve os
mesmos objetos que o `pinterest-dl` devolve (`id`, `src`, `alt`, `origin`,
`resolution`), que é o contrato do qual este adapter depende.
"""

from __future__ import annotations

import pytest

from app.adapters.pinterest_client import (
    MockPinterestClient,
    PinterestScrapeClient,
    PinterestV5Client,
    UnsplashClient,
    _pinimg_thumb,
    build_pinterest_client,
    is_mock_image,
)
from app.config import Settings


class _FakeMedia:
    """O que o `pinterest-dl` devolve — só os campos que o adapter lê."""

    def __init__(self, id, src, alt="", origin="", resolution=(800, 1200)):
        self.id = id
        self.src = src
        self.alt = alt
        self.origin = origin
        self.resolution = resolution


class _FakeScraper:
    def __init__(self, medias, calls, error=None):
        self._medias = medias
        self._calls = calls
        self._error = error

    def search(self, query, num, min_resolution, **kwargs):
        self._calls.append({"query": query, "num": num, "min_resolution": min_resolution})
        if self._error:
            raise self._error
        return list(self._medias)


def _fake_library(medias, calls=None, error=None, timeouts=None):
    """Substituto de `PinterestDL` — expõe só o `with_api` que o adapter usa."""
    calls = calls if calls is not None else []

    class _FakePinterestDL:
        @staticmethod
        def with_api(timeout=10, **kwargs):
            if timeouts is not None:
                timeouts.append(timeout)
            return _FakeScraper(medias, calls, error)

    return _FakePinterestDL


@pytest.fixture
def install_fake(monkeypatch):
    def _install(medias, **kwargs):
        monkeypatch.setattr(
            "app.adapters.pinterest_client._load_pinterest_dl",
            lambda: _fake_library(medias, **kwargs),
        )
    return _install


def _media_batch(n=10, resolution=(800, 1200)):
    return [
        _FakeMedia(
            id=1000 + i,
            src=f"https://i.pinimg.com/originals/ab/cd/ef/pin{i}.jpg",
            alt=f"a woman drinking coffee number {i}",
            origin=f"https://www.pinterest.com/pin/{1000 + i}/",
            resolution=resolution,
        )
        for i in range(n)
    ]


# ---------- mapeamento pin → PinterestImage ----------


def test_maps_a_pin_into_the_image_shape_the_app_uses(install_fake):
    install_fake([
        _FakeMedia(
            id=55169164192029389,
            src="https://i.pinimg.com/originals/c3/b1/76/hash.jpg",
            alt="a woman sitting on a couch holding a cup",
            origin="https://www.pinterest.com/pin/55169164192029389/",
        )
    ])

    image = PinterestScrapeClient().search("rotina matinal", limit=1)[0]

    # O id do pin chega como número da biblioteca e vira string aqui: é chave de
    # dicionário no casting, na galeria e no ranking.
    assert image.image_id == "55169164192029389"
    assert isinstance(image.image_id, str)
    assert image.image_url == "https://i.pinimg.com/originals/c3/b1/76/hash.jpg"
    assert image.source_url == "https://www.pinterest.com/pin/55169164192029389/"
    assert image.title == "a woman sitting on a couch holding a cup"
    assert image.attribution_text


def test_alt_text_feeds_the_casting_by_metadata(install_fake):
    """O casting procura "woman" no título — é o sinal que vale sem VLM."""
    from app.services.casting import _describes_person

    install_fake([
        _FakeMedia(
            id=1,
            src="https://i.pinimg.com/originals/aa/bb/cc/x.jpg",
            alt="a woman sitting in front of a window",
        )
    ])

    image = PinterestScrapeClient().search("tema", limit=1)[0]

    assert _describes_person(image)


def test_a_pin_without_alt_falls_back_to_the_query_as_title(install_fake):
    install_fake([
        _FakeMedia(id=7, src="https://i.pinimg.com/originals/aa/bb/cc/x.jpg", alt=None)
    ])

    image = PinterestScrapeClient().search("cafe da manha", limit=1)[0]

    assert image.title == "cafe da manha"


def test_a_pin_without_origin_still_links_back_to_pinterest(install_fake):
    install_fake([
        _FakeMedia(id=42, src="https://i.pinimg.com/originals/aa/bb/cc/x.jpg", origin="")
    ])

    image = PinterestScrapeClient().search("tema", limit=1)[0]

    assert image.source_url == "https://www.pinterest.com/pin/42/"


# ---------- thumb para o VLM ----------


def test_thumb_uses_the_resized_path_of_the_same_photo():
    thumb = _pinimg_thumb("https://i.pinimg.com/originals/c3/b1/76/hash.jpg")

    assert thumb == "https://i.pinimg.com/474x/c3/b1/76/hash.jpg"


def test_thumb_of_a_png_pin_is_requested_as_jpg():
    """O caminho redimensionado do CDN serve só JPEG: pedir `.png` ali
    responde 403, e a visão ficaria sem foto para olhar."""
    thumb = _pinimg_thumb("https://i.pinimg.com/originals/c3/b1/76/hash.png")

    assert thumb == "https://i.pinimg.com/474x/c3/b1/76/hash.jpg"


@pytest.mark.parametrize("src", [
    "https://example.com/foto.jpg",
    "https://i.pinimg.com/originals/sem-extensao",
    "",
])
def test_thumb_is_empty_when_the_url_is_not_a_cdn_photo(src):
    # Vazio faz o `vision_url` cair na foto cheia, que é o comportamento certo:
    # melhor um token a mais que uma URL inventada que responde 404.
    assert _pinimg_thumb(src) == ""


def test_every_image_carries_a_thumb_for_the_vlm(install_fake):
    install_fake(_media_batch(4))

    images = PinterestScrapeClient().search("tema", limit=4)

    assert all(img.thumb_url.startswith("https://i.pinimg.com/474x/") for img in images)
    assert all(img.vision_url == img.thumb_url for img in images)


# ---------- seleção: retrato e rotação ----------


def test_portrait_photos_win_when_there_are_enough(install_fake):
    landscape = [
        _FakeMedia(id=i, src=f"https://i.pinimg.com/originals/a/b/c/l{i}.jpg",
                   resolution=(1600, 900))
        for i in range(6)
    ]
    portrait = [
        _FakeMedia(id=100 + i, src=f"https://i.pinimg.com/originals/a/b/c/p{i}.jpg",
                   resolution=(800, 1200))
        for i in range(4)
    ]
    install_fake(landscape + portrait)

    images = PinterestScrapeClient().search("tema", limit=3)

    assert all(img.image_id.startswith("10") for img in images), (
        "o slide é 4:5 — foto deitada perde metade da cena no recorte"
    )


def test_landscape_is_better_than_no_photo(install_fake):
    """Sem retrato suficiente, o pool inteiro vale: gradiente é pior."""
    install_fake(_media_batch(5, resolution=(1600, 900)))

    images = PinterestScrapeClient().search("tema", limit=4)

    assert len(images) == 4
    assert not any(is_mock_image(img) for img in images)


def test_a_pin_without_resolution_does_not_break_the_selection(install_fake):
    install_fake([
        _FakeMedia(id=1, src="https://i.pinimg.com/originals/a/b/c/x.jpg", resolution=None),
        _FakeMedia(id=2, src="https://i.pinimg.com/originals/a/b/c/y.jpg", resolution=(0, 0)),
    ])

    images = PinterestScrapeClient().search("tema", limit=2)

    assert len(images) == 2


# ---------- seleção: piso de resolução ----------


def _hi_res(n, start=200):
    return [
        _FakeMedia(id=start + i, src=f"https://i.pinimg.com/originals/a/b/c/hi{i}.jpg",
                   resolution=(1440, 1800))
        for i in range(n)
    ]


def _lo_res(n, start=300):
    return [
        _FakeMedia(id=start + i, src=f"https://i.pinimg.com/originals/a/b/c/lo{i}.jpg",
                   resolution=(474, 711))
        for i in range(n)
    ]


def test_photos_smaller_than_the_slide_are_left_out(install_fake):
    """474x711 esticado para 1080x1350 chega ao feed borrado — e o VLM não tem
    como reprovar isso, porque ele julga uma thumb de 474px."""
    install_fake(_lo_res(12) + _hi_res(5))

    images = PinterestScrapeClient(min_resolution=(1080, 1350)).search("tema", limit=4)

    assert all(img.image_id.startswith("20") for img in images), [
        img.image_id for img in images
    ]


def test_resolution_beats_orientation_when_both_cannot_be_had(install_fake):
    """Foto pequena em pé perde para foto grande deitada: o recorte de cover
    perde metade da cena, a ampliação estraga a foto inteira."""
    landscape_hi = [
        _FakeMedia(id=200 + i, src=f"https://i.pinimg.com/originals/a/b/c/lh{i}.jpg",
                   resolution=(1920, 1440))
        for i in range(4)
    ]
    install_fake(_lo_res(10) + landscape_hi)

    images = PinterestScrapeClient(min_resolution=(1080, 1350)).search("tema", limit=4)

    assert all(img.image_id.startswith("20") for img in images)


def test_a_small_photo_is_still_better_than_a_gradient(install_fake):
    """Tema sem acervo em alta: o piso cai em vez de o carrossel virar mock."""
    install_fake(_lo_res(6))

    images = PinterestScrapeClient(min_resolution=(1080, 1350)).search("tema", limit=4)

    assert len(images) == 4
    assert not any(is_mock_image(img) for img in images)


def test_a_pin_without_resolution_does_not_pass_the_floor(install_fake):
    """Medida ausente não é prova de alta resolução — com 40 pins no pool, dá
    para exigir prova em vez de dar o benefício da dúvida."""
    unknown = [
        _FakeMedia(id=300 + i, src=f"https://i.pinimg.com/originals/a/b/c/u{i}.jpg",
                   resolution=None)
        for i in range(10)
    ]
    install_fake(unknown + _hi_res(5))

    images = PinterestScrapeClient(min_resolution=(1080, 1350)).search("tema", limit=4)

    assert all(img.image_id.startswith("20") for img in images)


def test_the_floor_comes_from_the_slide_size(monkeypatch):
    """O piso é o próprio slide: exigir mais seria arbitrário, menos deixaria
    entrar foto que o render precisa ampliar."""
    settings = Settings.from_env({
        "IMAGE_PROVIDER": "pinterest_scrape",
        "SLIDE_WIDTH": "1080",
        "SLIDE_HEIGHT": "1350",
    })

    client = build_pinterest_client(settings)

    assert client._min_resolution == (1080, 1350)  # noqa: SLF001


def test_the_library_still_gets_no_floor_of_its_own(install_fake):
    """O `min_resolution` da biblioteca corta ANTES de contar os pins: para
    fechar o pool ela pagina de novo, com um sleep por página, dentro do
    POST /generate. O corte é feito no pool já recebido."""
    calls: list[dict] = []
    install_fake(_hi_res(40), calls=calls)

    PinterestScrapeClient(min_resolution=(1080, 1350)).search("tema", limit=4)

    assert calls[0]["min_resolution"] == (0, 0)
    assert len(calls) == 1


def test_the_same_query_does_not_always_return_the_same_photos(install_fake):
    """A busca vem ordenada por relevância e essa ordem é estável — sem sortear
    o ponto de corte, o mesmo tema devolveria as mesmas fotos toda vez."""
    install_fake(_media_batch(40))
    client = PinterestScrapeClient()

    first_ids = {
        tuple(img.image_id for img in client.search("mesmo tema", limit=4))
        for _ in range(25)
    }

    assert len(first_ids) > 1


def test_one_search_is_one_request(install_fake):
    """Pedir mais de 50 dispararia uma segunda página e um sleep, dentro do
    POST /generate."""
    calls: list[dict] = []
    install_fake(_media_batch(40), calls=calls)

    PinterestScrapeClient().search("tema", limit=6)

    assert len(calls) == 1
    assert calls[0]["num"] <= 50


def test_the_timeout_comes_from_the_settings(install_fake, monkeypatch):
    timeouts: list[float] = []
    monkeypatch.setattr(
        "app.adapters.pinterest_client._load_pinterest_dl",
        lambda: _fake_library(_media_batch(4), timeouts=timeouts),
    )

    PinterestScrapeClient(timeout=42).search("tema", limit=2)

    assert timeouts == [42]


# ---------- falhas: sempre com motivo, nunca com exceção ----------


def test_a_failed_scrape_falls_back_to_mock_with_a_reason(install_fake):
    install_fake([], error=RuntimeError("payload mudou"))
    client = PinterestScrapeClient()

    images = client.search("tema", limit=4)

    assert images, "o fallback deve devolver imagens, não lista vazia"
    assert all(is_mock_image(img) for img in images)
    assert client.name == "pinterest_scrape", "o nome do cliente segue sendo o real"
    assert "RuntimeError" in client.last_fallback_reason


def test_no_results_falls_back_to_mock_with_a_reason(install_fake):
    install_fake([])
    client = PinterestScrapeClient()

    images = client.search("tema sem pin nenhum", limit=4)

    assert all(is_mock_image(img) for img in images)
    assert client.last_fallback_reason


def test_a_pin_without_src_is_not_a_photo(install_fake):
    install_fake([_FakeMedia(id=1, src=""), _FakeMedia(id=2, src="")])
    client = PinterestScrapeClient()

    images = client.search("tema", limit=2)

    assert all(is_mock_image(img) for img in images)


def test_missing_library_explains_how_to_install_it(monkeypatch):
    monkeypatch.setattr(
        "app.adapters.pinterest_client._load_pinterest_dl", lambda: None
    )
    client = PinterestScrapeClient()

    images = client.search("tema", limit=3)

    assert all(is_mock_image(img) for img in images)
    assert "pinterest-dl" in client.last_fallback_reason


def test_the_reason_is_cleared_between_searches(install_fake):
    install_fake(_media_batch(4))
    client = PinterestScrapeClient()
    client.last_fallback_reason = "de uma busca anterior"

    client.search("tema", limit=2)

    assert client.last_fallback_reason == ""


# ---------- escolha do provider ----------


@pytest.fixture(autouse=True)
def _no_unsplash_key(monkeypatch):
    monkeypatch.delenv("UNSPLASH_ACCESS_KEY", raising=False)


def test_image_provider_defaults_to_auto():
    assert Settings.from_env({}).image_provider == "auto"


def test_an_unknown_image_provider_falls_back_to_auto():
    """Erro de digitação vira a escada de sempre, não um boot quebrado."""
    assert Settings.from_env({"IMAGE_PROVIDER": "pintrest"}).image_provider == "auto"


def test_image_provider_is_case_insensitive():
    settings = Settings.from_env({"IMAGE_PROVIDER": "Pinterest_Scrape"})
    assert settings.image_provider == "pinterest_scrape"


def test_choosing_the_scraper_gives_the_scrape_client():
    settings = Settings.from_env({"IMAGE_PROVIDER": "pinterest_scrape"})

    assert isinstance(build_pinterest_client(settings), PinterestScrapeClient)


def test_auto_never_picks_the_scraper_on_its_own():
    """Scraping é escolha explícita: sem chave nenhuma o carrossel sai em mock,
    e não raspando o Pinterest por conta própria."""
    settings = Settings.from_env({})

    assert isinstance(build_pinterest_client(settings), MockPinterestClient)


def test_the_scraper_wins_over_the_official_token_when_chosen():
    settings = Settings.from_env({
        "IMAGE_PROVIDER": "pinterest_scrape",
        "PINTEREST_ACCESS_TOKEN": "pina_token",
    })

    assert isinstance(build_pinterest_client(settings), PinterestScrapeClient)


def test_auto_still_prefers_the_official_token():
    settings = Settings.from_env({"PINTEREST_ACCESS_TOKEN": "pina_token"})

    assert isinstance(build_pinterest_client(settings), PinterestV5Client)


def test_auto_still_prefers_unsplash_when_there_is_a_key(monkeypatch):
    monkeypatch.setenv("UNSPLASH_ACCESS_KEY", "chave")

    assert isinstance(build_pinterest_client(Settings.from_env({})), UnsplashClient)


def test_forcing_mock_ignores_the_configured_token():
    settings = Settings.from_env({
        "IMAGE_PROVIDER": "mock",
        "PINTEREST_ACCESS_TOKEN": "pina_token",
    })

    assert isinstance(build_pinterest_client(settings), MockPinterestClient)


def test_an_impossible_choice_falls_back_down_the_ladder(monkeypatch):
    """IMAGE_PROVIDER=unsplash sem chave: melhor a escada de sempre que um
    cliente que só sabe responder erro."""
    monkeypatch.setenv("UNSPLASH_ACCESS_KEY", "")
    settings = Settings.from_env({
        "IMAGE_PROVIDER": "unsplash",
        "PINTEREST_ACCESS_TOKEN": "pina_token",
    })

    assert isinstance(build_pinterest_client(settings), PinterestV5Client)
