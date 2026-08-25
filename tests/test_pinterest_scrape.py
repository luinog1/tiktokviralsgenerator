"""Testes do Pinterest sem token — o cliente que fala com o `pinterest-dl`.

Nenhum teste toca a rede: a biblioteca é injetada por fakes que devolvem os
mesmos objetos que o `pinterest-dl` devolve (`id`, `src`, `alt`, `origin`,
`resolution`), que é o contrato do qual este adapter depende.

São **dois** caminhos e por isso dois fakes. O normal é a paginação por
bookmark (`_load_pinterest_pager` → `Api`/`ResponseParser`), que retoma de onde
a geração anterior parou; a reserva é o `search()` da biblioteca
(`_load_pinterest_dl` → `PinterestDL.with_api`), que sempre começa do topo e
entra quando a paginação não está disponível. `install_fake` desliga a
paginação para testar a reserva; `install_pager` testa o caminho normal.
"""

from __future__ import annotations

import pytest

from app.adapters.pinterest_client import (
    MockPinterestClient,
    PinterestScrapeClient,
    UnsplashClient,
    _pinimg_thumb,
    _covers_slide,
    _query_attempts,
    build_pinterest_client,
    is_mock_image,
    media_identity,
)
from app.config import IMAGE_PROVIDERS, Settings


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

    def related(self, url, num, min_resolution, **kwargs):
        self._calls.append({"url": url, "num": num, "min_resolution": min_resolution})
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
    """A reserva: o `search()` da biblioteca, com a paginação por cursor fora.

    A paginação é desligada de propósito. Sem isso, `_load_pinterest_pager`
    devolveria as classes REAIS da biblioteca instalada e a busca sairia para a
    rede — o oposto do que esta suíte promete.
    """

    def _install(medias, **kwargs):
        monkeypatch.setattr(
            "app.adapters.pinterest_client._load_pinterest_dl",
            lambda: _fake_library(medias, **kwargs),
        )
        monkeypatch.setattr(
            "app.adapters.pinterest_client._load_pinterest_pager", lambda: None
        )
    return _install


class _FakePinResponse:
    """O que `Api.get_search` devolve — só o que o pager lê."""

    def __init__(self, medias, bookmarks):
        self.resource_response = {"data": {"results": list(medias)}}
        self._bookmarks = list(bookmarks)

    def get_bookmarks(self):
        return list(self._bookmarks)


def _fake_pager(pages, calls=None, error=None):
    """Substituto de `(Api, ResponseParser)` — páginas indexadas por bookmark.

    `pages` é `{bookmark_de_entrada: (medias, bookmarks_de_saida)}`, com `""`
    representando "sem cursor", isto é, o topo do acervo.
    """
    calls = calls if calls is not None else []

    class _FakeApi:
        def __init__(self, url, cookies=None, timeout=5, dump=None):
            self.url = url
            self.timeout = timeout

        def get_search(self, num, bookmarks):
            key = bookmarks[-1] if bookmarks else ""
            calls.append({"url": self.url, "num": num, "bookmarks": list(bookmarks)})
            if error:
                raise error
            medias, out = pages.get(key, ([], ["-end-"]))
            return _FakePinResponse(medias, out)

        get_related_images = get_search

    class _FakeParser:
        @staticmethod
        def from_responses(data, min_resolution, **kwargs):
            if not data:
                from pinterest_dl.exceptions import EmptyResponseError

                raise EmptyResponseError("vazio")
            return list(data)

    return _FakeApi, _FakeParser


@pytest.fixture
def install_pager(monkeypatch):
    """O caminho normal: paginação por bookmark, com o `search()` fora."""

    def _install(pages, calls=None, error=None):
        monkeypatch.setattr(
            "app.adapters.pinterest_client._load_pinterest_pager",
            lambda: _fake_pager(pages, calls, error),
        )
        monkeypatch.setattr(
            "app.adapters.pinterest_client._load_pinterest_dl", lambda: None
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
    """O casting procura "woman" no `alt` — é o sinal que vale sem VLM."""
    from app.services.casting import _focus

    install_fake([
        _FakeMedia(
            id=1,
            src="https://i.pinimg.com/originals/aa/bb/cc/x.jpg",
            alt="a woman sitting in front of a window",
        )
    ])

    image = PinterestScrapeClient().search("tema", limit=1)[0]

    assert _focus(image) == "person"


def test_a_pin_without_alt_falls_back_to_the_query_as_title(install_fake):
    install_fake([
        _FakeMedia(id=7, src="https://i.pinimg.com/originals/aa/bb/cc/x.jpg", alt=None)
    ])

    image = PinterestScrapeClient().search("cafe da manha", limit=1)[0]

    assert image.title == "cafe da manha"
    # …mas só para exibir. A query descreve a busca, não a foto: o casting lê
    # o `alt`, e sem legenda ele fica vazio em vez de virar "comida".
    assert image.alt == ""


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


def test_a_small_photo_is_rejected_instead_of_being_upscaled(install_fake):
    """O piso é estrito: uma origem pequena nunca entra no PNG final."""
    install_fake(_lo_res(6))

    images = PinterestScrapeClient(min_resolution=(1080, 1350)).search("tema", limit=4)

    assert len(images) == 4
    assert all(is_mock_image(img) for img in images)


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
    """A busca vem ordenada por relevância e essa ordem é estável — sem sortear,
    o mesmo tema devolveria as mesmas fotos toda vez.

    O `> 1` sozinho não prova nada, e foi por isso que o defeito sobreviveu a
    esta suíte: a janela contígua antiga tinha N−L+1 saídas possíveis e passava
    no `> 1` repetindo quase tudo. Com o pool filtrado valendo 11 pins e uma
    janela de 10, duas gerações repetiam 9,4 de 10 fotos. O que separa amostra
    de janela é a **descontinuidade**: os ids são sequenciais, então uma janela
    de 4 tem sempre `max - min == 3`.
    """
    install_fake(_media_batch(40))
    client = PinterestScrapeClient()

    draws = [
        [int(img.image_id) for img in client.search("mesmo tema", limit=4)]
        for _ in range(30)
    ]

    assert len({tuple(d) for d in draws}) > 1
    assert any(max(d) - min(d) > 3 for d in draws)
    # Sortear do pool inteiro também é o que dá material para a galeria da
    # prévia: 30 sorteios de 4 têm que varrer bem mais que os 4 primeiros pins.
    assert len({image_id for draw in draws for image_id in draw}) > 20


def test_photos_from_recent_carousels_go_to_the_end_of_the_draw(install_fake):
    """`avoid` é preferência, não veto: o que já saiu só perde a vez."""
    medias = _media_batch(40)
    install_fake(medias)
    ja_usadas = [media_identity(m.src) for m in medias[:36]]

    client = PinterestScrapeClient(avoid_media=ja_usadas)
    draw = {img.image_id for img in client.search("mesmo tema", limit=4)}

    assert draw == {str(m.id) for m in medias[36:]}


def test_an_exhausted_memory_still_returns_a_carousel(install_fake):
    """Acervo inteiro já usado não pode devolver carrossel vazio."""
    medias = _media_batch(40)
    install_fake(medias)

    client = PinterestScrapeClient(avoid_media=[media_identity(m.src) for m in medias])

    assert len(client.search("mesmo tema", limit=4)) == 4


def test_one_search_is_one_call_into_the_library(install_fake):
    """A paginação é da biblioteca (50 por requisição, 0,2s entre elas) — o
    adapter não pode paginar por fora, senão cada pool viraria N chamadas.

    O pool pedido é fundo de propósito: com o piso estrito de 1080×1350, medido
    em 2026-08-22, 40 pins deixavam 11 acima do piso e 120 deixam 40.
    """
    calls: list[dict] = []
    install_fake(_media_batch(40), calls=calls)

    PinterestScrapeClient().search("tema", limit=6)

    assert len(calls) == 1
    assert calls[0]["num"] == PinterestScrapeClient._POOL_SIZE  # noqa: SLF001


def test_the_timeout_comes_from_the_settings(monkeypatch):
    timeouts: list[float] = []
    monkeypatch.setattr(
        "app.adapters.pinterest_client._load_pinterest_dl",
        lambda: _fake_library(_media_batch(4), timeouts=timeouts),
    )
    monkeypatch.setattr(
        "app.adapters.pinterest_client._load_pinterest_pager", lambda: None
    )

    PinterestScrapeClient(timeout=42).search("tema", limit=2)

    assert timeouts == [42]


# ---------- pins relacionados (pessoa fixada) ----------


_PIN_URL = "https://www.pinterest.com/pin/55169164192029389/"


def test_related_maps_pins_into_the_same_image_shape(install_fake):
    install_fake(_media_batch(4))

    images = PinterestScrapeClient().related(_PIN_URL, limit=4)

    assert len(images) == 4
    assert all(img.image_id and img.image_url for img in images)
    assert all(img.thumb_url.startswith("https://i.pinimg.com/474x/") for img in images)


def test_related_asks_the_library_for_the_pin_url(install_fake):
    calls: list[dict] = []
    install_fake(_media_batch(4), calls=calls)

    PinterestScrapeClient().related(_PIN_URL, limit=4)

    assert calls[0]["url"] == _PIN_URL
    # O piso continua sendo aplicado no pool recebido, não na biblioteca —
    # mesmo motivo da busca por query (paginação + sleep dentro do POST).
    assert calls[0]["min_resolution"] == (0, 0)


def test_related_applies_the_resolution_floor(install_fake):
    install_fake(_lo_res(10) + _hi_res(5))

    images = PinterestScrapeClient(min_resolution=(1080, 1350)).related(_PIN_URL, limit=4)

    assert all(img.image_id.startswith("20") for img in images)


def test_related_failure_returns_empty_not_mock(install_fake):
    """[] em vez de gradiente: quem chama tem um fallback melhor — a busca de
    retrato por query de sempre."""
    install_fake([], error=RuntimeError("payload mudou"))

    assert PinterestScrapeClient().related(_PIN_URL, limit=4) == []


def test_related_without_the_library_returns_empty(monkeypatch):
    monkeypatch.setattr(
        "app.adapters.pinterest_client._load_pinterest_dl", lambda: None
    )
    monkeypatch.setattr(
        "app.adapters.pinterest_client._load_pinterest_pager", lambda: None
    )

    assert PinterestScrapeClient().related(_PIN_URL, limit=4) == []


def test_related_with_no_results_returns_empty(install_fake):
    install_fake([])

    assert PinterestScrapeClient().related(_PIN_URL, limit=4) == []


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
        "app.adapters.pinterest_client._load_pinterest_pager", lambda: None
    )
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


def test_the_removed_official_token_is_ignored_everywhere(monkeypatch):
    """A API oficial v5 saiu (exigia Standard Access que o projeto nunca teve).
    Um PINTEREST_ACCESS_TOKEN sobrando no ambiente do Render não pode mudar
    nada — nem virar um cliente, nem desviar a escada do `auto`."""
    monkeypatch.setenv("UNSPLASH_ACCESS_KEY", "")
    settings = Settings.from_env({"PINTEREST_ACCESS_TOKEN": "pina_token"})

    assert isinstance(build_pinterest_client(settings), MockPinterestClient)
    assert not hasattr(settings, "pinterest_access_token")
    # E o valor não é mais um provider escolhível.
    assert "pinterest_v5" not in IMAGE_PROVIDERS
    assert Settings.from_env(
        {"IMAGE_PROVIDER": "pinterest_v5"}
    ).image_provider == "auto"


def test_auto_still_prefers_unsplash_when_there_is_a_key(monkeypatch):
    monkeypatch.setenv("UNSPLASH_ACCESS_KEY", "chave")

    assert isinstance(build_pinterest_client(Settings.from_env({})), UnsplashClient)


def test_forcing_mock_ignores_a_configured_unsplash_key(monkeypatch):
    monkeypatch.setenv("UNSPLASH_ACCESS_KEY", "chave")
    settings = Settings.from_env({"IMAGE_PROVIDER": "mock"})

    assert isinstance(build_pinterest_client(settings), MockPinterestClient)


def test_an_impossible_choice_falls_back_down_the_ladder(monkeypatch):
    """IMAGE_PROVIDER=unsplash sem chave: melhor a escada de sempre que um
    cliente que só sabe responder erro."""
    monkeypatch.setenv("UNSPLASH_ACCESS_KEY", "")
    settings = Settings.from_env({"IMAGE_PROVIDER": "unsplash"})

    assert isinstance(build_pinterest_client(settings), MockPinterestClient)


# ---------- piso de resolução por fator de ampliação ----------


class _Res:
    """Só o `.resolution` que o piso lê."""

    def __init__(self, w, h):
        self.resolution = (w, h)


def test_the_floor_measures_upscaling_not_raw_width():
    """`1024×1536` é o tamanho nº 1 do acervo do Pinterest e cobre o slide com
    1,055× de ampliação — invisível. O piso literal reprovava por 56px."""
    assert _covers_slide(_Res(1024, 1536), (1080, 1350))
    assert _covers_slide(_Res(1000, 1500), (1080, 1350))
    assert _covers_slide(_Res(1080, 1350), (1080, 1350))


def test_the_floor_still_rejects_what_would_arrive_blurry():
    """A tolerância é para ampliação que não se vê, não para relaxar o piso:
    736×981 precisaria de 1,38× e chega borrado ao feed."""
    assert not _covers_slide(_Res(736, 981), (1080, 1350))
    assert not _covers_slide(_Res(474, 711), (1080, 1350))
    assert not _covers_slide(_Res(0, 0), (1080, 1350))


def test_a_wide_photo_is_rejected_by_the_height_it_lacks():
    """O slide é 4:5: uma foto deitada larguíssima não cobre a altura."""
    assert not _covers_slide(_Res(4000, 500), (1080, 1350))


def test_no_floor_configured_accepts_anything():
    assert _covers_slide(_Res(10, 10), (0, 0))


# ---------- a query que não achava nada ----------


def test_hashtags_and_profile_handles_leave_the_keyword_search():
    """`#praia` vira token desconhecido e `@perfil` é alvo do Instagram — os
    dois chegam aqui porque o mesmo formulário alimenta as três fontes."""
    attempts = _query_attempts("praia #verao @bellebres sol")

    assert attempts[0] == "praia verao sol"


def test_a_repeated_term_does_not_take_two_slots():
    """O tema e as dicas de casting se sobrepõem: `lifestyle` e `aesthetic`
    chegavam duas vezes no log de produção."""
    attempts = _query_attempts("lifestyle cozy aesthetic aesthetic lifestyle travel")

    assert attempts[0] == "lifestyle cozy aesthetic travel"


def test_the_shortened_query_keeps_the_theme_and_the_casting_hints():
    """Encurtar pela cauda salvaria o tema e perderia `woman portrait`, que é o
    que faz a foto de pessoa aparecer no hook."""
    query = (
        "lifestyle cozy praia vibe bellebres girly moda verao "
        "woman portrait lifestyle aesthetic"
    )

    attempts = _query_attempts(query)

    assert len(attempts) == 3
    assert attempts[0].startswith("lifestyle cozy")
    assert "woman portrait" in attempts[1]
    assert attempts[1].startswith("lifestyle cozy")
    assert attempts[2] == "lifestyle cozy praia"


def test_a_short_query_is_not_shortened():
    assert _query_attempts("rotina matinal") == ["rotina matinal"]


def test_an_empty_query_has_nothing_to_try():
    assert _query_attempts("  @so  #  ") == []


def test_the_search_retries_shorter_when_the_first_try_finds_nothing(monkeypatch):
    """Zero pins cai no mock, e o mock é determinístico por query: a mesma
    hashtag devolveria os mesmos gradientes para sempre."""
    calls: list[dict] = []
    medias = _media_batch(20)

    class _EmptyUntilShort:
        @staticmethod
        def with_api(timeout=10, **kwargs):
            class _S:
                def search(self, query, num, min_resolution, **kw):
                    calls.append(query)
                    # Só a query mais curta acha alguma coisa.
                    return list(medias) if len(query.split()) <= 3 else []
            return _S()

    monkeypatch.setattr(
        "app.adapters.pinterest_client._load_pinterest_dl", lambda: _EmptyUntilShort
    )
    monkeypatch.setattr(
        "app.adapters.pinterest_client._load_pinterest_pager", lambda: None
    )
    found = PinterestScrapeClient().search(
        "lifestyle cozy praia vibe bellebres girly moda verao aesthetic", limit=4
    )

    assert len(calls) == 3
    assert len(found) == 4
    assert not any(is_mock_image(img) for img in found)


# ---------- paginação por cursor: a busca não repete a geração anterior ----------


def _pin(n, resolution=(1024, 1536)):
    return _FakeMedia(
        id=n,
        src=f"https://i.pinimg.com/originals/ab/cd/ef/p{n}.jpg",
        alt=f"a woman drinking coffee number {n}",
        origin=f"https://www.pinterest.com/pin/{n}/",
        resolution=resolution,
    )


def _stream(*page_sizes):
    """Um acervo paginado: `{bookmark_entrada: (pins, bookmark_saida)}`.

    A última página termina em `-end-`, como a API faz quando o acervo acaba.
    """
    pages: dict[str, tuple[list, list]] = {}
    start = 0
    for index, size in enumerate(page_sizes):
        key = "" if index == 0 else f"bm{index}"
        out = [f"bm{index + 1}"] if index + 1 < len(page_sizes) else ["-end-"]
        pages[key] = ([_pin(start + i) for i in range(size)], out)
        start += size
    return pages


def test_the_second_generation_reads_the_page_after_the_first(install_pager):
    """O defeito principal: a busca é determinística.

    Medido em 2026-08-24, `pinterest-dl` devolve os MESMOS 50 pins na MESMA
    ordem em duas chamadas seguidas — e sortear um recorte disso não resolve,
    porque dois sorteios num pool pequeno se sobrepõem por aritmética e o
    ranking reordena os dois pelo mesmo critério. Guardar o bookmark faz a
    segunda geração ler a página SEGUINTE, sem overlap possível.
    """
    install_pager(_stream(30, 30, 30))
    client = PinterestScrapeClient(min_resolution=(1080, 1350))

    primeira = {img.image_id for img in client.search("rotina matinal", limit=6)}
    segunda = {img.image_id for img in client.search("rotina matinal", limit=6)}

    assert primeira and segunda
    assert not (primeira & segunda), "a segunda geração repetiu fotos da primeira"


def test_the_cursor_is_per_query_not_global(install_pager):
    """Duas queries diferentes paginam streams diferentes: o cursor de uma não
    pode empurrar a outra para o meio do acervo dela."""
    calls: list[dict] = []
    install_pager(_stream(30, 30), calls=calls)
    client = PinterestScrapeClient(min_resolution=(1080, 1350))

    client.search("rotina matinal", limit=6)
    calls.clear()
    client.search("treino em casa", limit=6)

    assert calls, "a segunda query não buscou"
    assert calls[0]["bookmarks"] == [], "a outra query começou do meio do acervo"


def test_the_end_of_the_catalog_rewinds_the_cursor(install_pager):
    """Acervo esgotado tem que continuar devolvendo carrossel: o `-end-` volta
    o cursor ao topo em vez de deixar a busca vazia para sempre."""
    install_pager(_stream(30))
    client = PinterestScrapeClient(min_resolution=(1080, 1350))

    primeira = client.search("tema curto", limit=6)
    segunda = client.search("tema curto", limit=6)

    assert len(primeira) == 6
    assert len(segunda) == 6


def test_paging_stops_as_soon_as_there_are_enough_usable_pins(install_pager):
    """Cada página é uma requisição dentro do POST /generate. O laço para no
    alvo de pins ACIMA DO PISO, não num número de pins brutos — foi o piso que
    virou o gargalo quando ele deixou de ceder."""
    calls: list[dict] = []
    install_pager(_stream(50, 50, 50, 50, 50, 50), calls=calls)

    PinterestScrapeClient(min_resolution=(1080, 1350)).search("tema", limit=6)

    assert len(calls) == 1, "50 pins acima do piso já cobrem o alvo de 24"


def test_a_page_of_small_photos_does_not_end_the_search(install_pager):
    """Página inteira abaixo do piso não é "acervo no fim": é motivo para
    paginar mais, porque o piso é o que reprova metade do que vem."""
    pages = {
        "": ([_pin(i, resolution=(474, 711)) for i in range(50)], ["bm1"]),
        "bm1": ([_pin(100 + i) for i in range(50)], ["-end-"]),
    }
    install_pager(pages)

    found = PinterestScrapeClient(min_resolution=(1080, 1350)).search("tema", limit=6)

    assert len(found) == 6
    assert all(int(img.image_id) >= 100 for img in found)


def test_a_broken_cursor_restarts_from_the_top(install_pager, monkeypatch):
    """Bookmark envelhecido (o acervo da query mudou) não pode zerar a busca —
    recomeçar do topo é melhor que devolver gradiente."""
    from app.services import search_cursor

    search_cursor.save_cursor("pinterest_search", "tema", bookmarks=["bm-que-morreu"])
    install_pager(_stream(30, 30))

    found = PinterestScrapeClient(min_resolution=(1080, 1350)).search("tema", limit=6)

    assert len(found) == 6


def test_the_pager_failing_falls_back_to_the_library_search(monkeypatch):
    """A paginação lê classes internas da biblioteca. Se elas mudarem de forma,
    a busca cai no `search()` de sempre — carrossel repetido ainda é melhor que
    carrossel de gradiente."""
    monkeypatch.setattr(
        "app.adapters.pinterest_client._load_pinterest_pager",
        lambda: _fake_pager({}, error=RuntimeError("a lib mudou")),
    )
    monkeypatch.setattr(
        "app.adapters.pinterest_client._load_pinterest_dl",
        lambda: _fake_library(_media_batch(40)),
    )

    found = PinterestScrapeClient().search("tema", limit=4)

    assert len(found) == 4
    assert not any(is_mock_image(img) for img in found)


def test_related_pins_also_advance_a_cursor(install_pager):
    """Os relacionados de um pin também vêm sempre na mesma ordem — sem cursor,
    a pessoa fixada rendia o mesmo hook em toda geração."""
    install_pager(_stream(30, 30, 30))
    client = PinterestScrapeClient(min_resolution=(1080, 1350))

    primeira = {img.image_id for img in client.related(_PIN_URL, limit=6)}
    segunda = {img.image_id for img in client.related(_PIN_URL, limit=6)}

    assert primeira and segunda
    assert not (primeira & segunda)


def test_the_search_cursor_and_the_related_cursor_are_separate(install_pager):
    """Busca e "mais como este" são streams diferentes: compartilhar posição
    faria uma pular o começo da outra."""
    calls: list[dict] = []
    install_pager(_stream(30, 30), calls=calls)
    client = PinterestScrapeClient(min_resolution=(1080, 1350))

    client.search(_PIN_URL, limit=6)
    calls.clear()
    client.related(_PIN_URL, limit=6)

    assert calls[0]["bookmarks"] == []
