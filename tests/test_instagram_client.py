"""Testes do Instagram sem token e da busca combinada Instagram + Pinterest.

Nenhum teste toca a rede: o `requests.get` do módulo é trocado por um fake que
devolve os dois formatos de payload dos endpoints web do Instagram (GraphQL do
perfil e seções v1 da hashtag) — o contrato do qual o adapter depende.
"""

from __future__ import annotations

import pytest
import requests

from app.adapters.pinterest_client import (
    CombinedImageClient,
    InstagramScrapeClient,
    MockPinterestClient,
    PinterestImage,
    PinterestScrapeClient,
    UnsplashClient,
    build_pinterest_client,
    is_mock_image,
)
from app.config import Settings


class _FakeResponse:
    def __init__(self, payload=None, status_code=200, text="", headers=None):
        self._payload = payload
        self.status_code = status_code
        self.text = text or ("" if payload is not None else "<html>login</html>")
        self.headers = headers or {}

    def json(self):
        if self._payload is None:
            raise requests.exceptions.JSONDecodeError("Expecting value", "<html>", 0)
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


@pytest.fixture
def fake_get(monkeypatch):
    """Instala um fake de requests.get e devolve a lista de chamadas feitas."""

    def _install(response):
        calls = []
        # Uma lista de respostas serve para simular respostas em sequência:
        # uma resposta por chamada, na ordem.
        queue = list(response) if isinstance(response, list) else None

        def _get(url, params=None, headers=None, timeout=None,
                 allow_redirects=True):
            calls.append({
                "url": url,
                "params": params or {},
                "headers": headers or {},
                "timeout": timeout,
                "allow_redirects": allow_redirects,
            })
            current = queue.pop(0) if queue is not None else response
            if isinstance(current, Exception):
                raise current
            return current

        monkeypatch.setattr("app.adapters.pinterest_client.requests.get", _get)
        return calls

    return _install


@pytest.fixture
def fake_post(monkeypatch):
    """Instala um fake de requests.post (a Apify) e devolve as chamadas."""

    def _install(response):
        calls = []
        queue = list(response) if isinstance(response, list) else None

        def _post(url, params=None, json=None, timeout=None):
            calls.append(
                {"url": url, "params": params or {}, "json": json or {}, "timeout": timeout}
            )
            current = queue.pop(0) if queue is not None else response
            if isinstance(current, Exception):
                raise current
            return current

        monkeypatch.setattr("app.adapters.pinterest_client.requests.post", _post)
        return calls

    return _install


def _apify_item(i=0, width=1080, height=1350, **over):
    """Item do dataset do apify/instagram-scraper (resultsType=posts)."""
    item = {
        "id": f"31415{i}",
        "type": "Image",
        "shortCode": f"Cabc{i}",
        "caption": f"legenda {i}",
        "url": f"https://www.instagram.com/p/Cabc{i}/",
        "displayUrl": f"https://scontent.cdninstagram.com/apify{i}.jpg",
        "alt": f"May be an image of 1 person, foto {i}",
        "ownerUsername": "fulana",
        "dimensionsWidth": width,
        "dimensionsHeight": height,
    }
    item.update(over)
    return item


def _profile_node(i=0, width=1080, height=1440, is_video=False, code=None):
    return {
        "node": {
            "id": f"31415{i}",
            "shortcode": code or f"Cabc{i}",
            "display_url": f"https://scontent.cdninstagram.com/full{i}.jpg",
            "thumbnail_src": f"https://scontent.cdninstagram.com/thumb{i}.jpg",
            "dimensions": {"width": width, "height": height},
            "is_video": is_video,
            "accessibility_caption": f"May be an image of 1 person, photo {i}",
            "owner": {"username": "fulana"},
        }
    }


def _profile_payload(nodes, is_private=False):
    return {
        "data": {
            "user": {
                "is_private": is_private,
                "edge_owner_to_timeline_media": {"edges": nodes},
            }
        }
    }


def _v1_media(i=0, width=1200, height=1500, media_type=1):
    return {
        "media": {
            "pk": f"9000{i}",
            "code": f"Dtag{i}",
            "media_type": media_type,
            "original_width": width,
            "original_height": height,
            "image_versions2": {
                "candidates": [
                    {"url": f"https://scontent.cdninstagram.com/big{i}.jpg",
                     "width": width, "height": height},
                    {"url": f"https://scontent.cdninstagram.com/small{i}.jpg",
                     "width": 320, "height": 400},
                ]
            },
            "caption": {"text": f"legenda {i}"},
            "user": {"username": "beltrana"},
        }
    }


def _tag_payload(medias):
    return {"data": {"top": {"sections": [{"layout_content": {"medias": medias}}]}}}


# ---------- derivação de hashtag e @perfil ----------


def test_tag_comes_from_the_query_without_the_casting_hints():
    client = InstagramScrapeClient(hint_words="woman portrait lifestyle aesthetic".split())
    assert client._tag_from("rotina matinal woman portrait lifestyle aesthetic") == (
        "rotinamatinal"
    )


def test_tag_drops_accents_and_punctuation():
    client = InstagramScrapeClient()
    assert client._tag_from("café da manhã!") == "cafedamanha"


def test_an_explicit_hashtag_wins_over_the_derived_one():
    client = InstagramScrapeClient(hint_words=["aesthetic"])
    assert client._tag_from("rotina matinal #morningroutine aesthetic") == (
        "morningroutine"
    )


def test_an_at_profile_in_the_query_switches_to_profile_search():
    from app.adapters.pinterest_client import _ig_username

    assert _ig_username("fotos de @Fulana.Silva hoje") == "fulana.silva"
    assert _ig_username("rotina matinal") == ""


# ---------- busca por perfil ----------


def test_profile_search_maps_the_graphql_node_into_the_app_shape(fake_get):
    calls = fake_get(_FakeResponse(_profile_payload([_profile_node(0)])))

    image = InstagramScrapeClient().search("@fulana", limit=1)[0]

    assert calls[0]["url"].endswith("/api/v1/users/web_profile_info/")
    assert calls[0]["params"] == {"username": "fulana"}
    # O header do site web é o que libera o acesso anônimo.
    assert calls[0]["headers"]["x-ig-app-id"]
    assert image.image_id == "ig-314150"
    assert image.image_url == "https://scontent.cdninstagram.com/full0.jpg"
    assert image.thumb_url == "https://scontent.cdninstagram.com/thumb0.jpg"
    assert image.source_url == "https://www.instagram.com/p/Cabc0/"
    # O accessibility_caption alimenta o casting por metadado.
    assert "person" in image.title
    assert "@fulana" in image.attribution_text


def test_videos_stay_out_of_the_pool(fake_get):
    fake_get(_FakeResponse(_profile_payload([
        _profile_node(0, is_video=True),
        _profile_node(1),
    ])))
    images = InstagramScrapeClient().search("@fulana", limit=8)
    assert [img.image_id for img in images] == ["ig-314151"]


def test_a_private_profile_falls_back_with_the_reason(fake_get):
    fake_get(_FakeResponse(_profile_payload([_profile_node(0)], is_private=True)))
    client = InstagramScrapeClient()
    images = client.search("@fulana", limit=4)
    assert all(is_mock_image(img) for img in images)
    assert "privado" in client.last_fallback_reason


# ---------- busca por hashtag ----------


def test_tag_search_reads_the_v1_sections_payload(fake_get):
    calls = fake_get(_FakeResponse(_tag_payload([_v1_media(0), _v1_media(1)])))

    images = InstagramScrapeClient().search("rotina matinal", limit=2)

    assert calls[0]["url"].endswith("/api/v1/tags/web_info/")
    assert calls[0]["params"] == {"tag_name": "rotinamatinal"}
    assert {img.image_id for img in images} == {"ig-90000", "ig-90001"}
    assert images[0].image_url.startswith("https://scontent.cdninstagram.com/big")
    # A menor candidata vira a thumb do VLM.
    assert "small" in images[0].thumb_url


def test_tag_search_reads_the_graphql_fallback_payload(fake_get):
    fake_get(_FakeResponse({
        "data": {
            "hashtag": {
                "edge_hashtag_to_media": {"edges": [_profile_node(7)]}
            }
        }
    }))
    images = InstagramScrapeClient().search("morningroutine", limit=1)
    assert images[0].image_id == "ig-314157"


def test_the_same_post_in_top_and_recent_counts_once(fake_get):
    payload = {
        "data": {
            "top": {"sections": [{"layout_content": {"medias": [_v1_media(0)]}}]},
            "recent": {"sections": [{"layout_content": {"medias": [_v1_media(0)]}}]},
        }
    }
    fake_get(_FakeResponse(payload))
    images = InstagramScrapeClient().search("rotina", limit=8)
    assert [img.image_id for img in images] == ["ig-90000"]


def test_carousel_posts_use_the_first_photo_as_cover(fake_get):
    carousel = _v1_media(3, media_type=8)
    carousel["media"]["carousel_media"] = [
        {"media_type": 2},
        {
            "media_type": 1,
            "image_versions2": {"candidates": [
                {"url": "https://scontent.cdninstagram.com/cover3.jpg",
                 "width": 1100, "height": 1600},
            ]},
            "original_width": 1100,
            "original_height": 1600,
        },
    ]
    fake_get(_FakeResponse(_tag_payload([carousel])))
    images = InstagramScrapeClient().search("rotina", limit=1)
    assert images[0].image_url == "https://scontent.cdninstagram.com/cover3.jpg"


# ---------- piso de resolução e retrato ----------


def test_resolution_floor_prefers_photos_that_cover_the_slide(fake_get):
    fake_get(_FakeResponse(_tag_payload([
        _v1_media(0, width=474, height=711),
        _v1_media(1, width=1200, height=1500),
    ])))
    client = InstagramScrapeClient(min_resolution=(1080, 1350))
    images = client.search("rotina", limit=1)
    assert images[0].image_id == "ig-90001"


def test_without_high_res_stock_the_floor_stays_strict(fake_get):
    fake_get(_FakeResponse(_tag_payload([_v1_media(0, width=474, height=711)])))
    client = InstagramScrapeClient(min_resolution=(1080, 1350))
    images = client.search("rotina", limit=1)
    assert is_mock_image(images[0])


# ---------- fallbacks ----------


def test_http_error_falls_back_with_a_reason_without_talking_about_keys(fake_get):
    fake_get(_FakeResponse({}, status_code=401))
    client = InstagramScrapeClient()
    images = client.search("rotina", limit=4)
    assert all(is_mock_image(img) for img in images)
    assert "bloqueou o acesso anônimo" in client.last_fallback_reason
    assert "chave" not in client.last_fallback_reason.lower()


def test_html_instead_of_json_reads_as_the_login_wall(fake_get):
    fake_get(_FakeResponse(payload=None))
    client = InstagramScrapeClient()
    images = client.search("rotina", limit=4)
    assert all(is_mock_image(img) for img in images)
    assert "login" in client.last_fallback_reason


def test_a_redirect_is_the_login_wall_and_is_not_followed(fake_get):
    """A API 302-redireciona para /accounts/login/. Seguir o redirect só
    baixaria o HTML do login — o redirect já É a resposta."""
    calls = fake_get(_FakeResponse({}, status_code=302))
    client = InstagramScrapeClient()
    images = client.search("rotina", limit=4)
    assert all(is_mock_image(img) for img in images)
    assert calls[0]["allow_redirects"] is False
    assert "página de login" in client.last_fallback_reason


def test_the_wall_never_blames_the_exit_ip(fake_get):
    """O muro é gate do ENDPOINT, não do IP: medido em 2026-08-16, o 302 volta
    igual de datacenter, de residencial doméstico e dos exits do ScrapeOps.
    Este aviso já mandou "trocar o proxy por um residencial" — conselho que fez
    o usuário pagar proxy à toa, e é o que o teste trava. O remédio agora é
    APIFY_TOKEN (sessão própria) ou trocar de fonte."""
    fake_get(_FakeResponse({}, status_code=302))
    for client in (
        InstagramScrapeClient(),
        InstagramScrapeClient(scrapedo_token="tok"),
    ):
        reason = client._wall_reason()
        assert "não é do IP" in reason or "não do IP" in reason
        assert "APIFY_TOKEN" in reason
        assert "pinterest" in reason.lower()
        assert "troque o proxy" not in reason.lower()


def test_the_wall_is_not_retried(fake_get):
    """Outro exit não passa por um gate de endpoint, e sem proxy o IP é sempre
    o mesmo — repetir a MESMA chamada seria só latência dentro do POST
    /generate.

    Duas chamadas, não uma: um termo de uma palavra tem dois alvos (o perfil e
    a hashtag de mesmo nome, ver `_ig_targets`) e alvo diferente não é repetir
    — é o que salva o caso do `bellebres`, que existe como perfil e não como
    hashtag. Nenhum dos dois é tentado duas vezes.
    """
    calls = fake_get([_FakeResponse({}, status_code=302)] * 3)
    client = InstagramScrapeClient()
    images = client.search("rotina", limit=2)
    assert len(calls) == 2
    assert [call["params"] for call in calls] == [
        {"username": "rotina"},
        {"tag_name": "rotina"},
    ]
    assert all(is_mock_image(img) for img in images)
    assert "APIFY_TOKEN" in client.last_fallback_reason


def test_the_rate_limit_falls_back_with_its_own_reason(fake_get):
    calls = fake_get(_FakeResponse({}, status_code=429))
    client = InstagramScrapeClient()
    images = client.search("rotina", limit=2)
    # Um alvo por chamada (perfil e hashtag), nenhum repetido.
    assert len(calls) == 2
    assert all(is_mock_image(img) for img in images)
    assert "429" in client.last_fallback_reason


# ---------- transporte Apify ----------


def test_apify_runs_the_actor_and_maps_the_dataset(fake_post):
    """A Apify não é proxy: devolve o dataset DELA, com nomes de campo
    próprios. A conversão acontece na fronteira, então o piso de resolução, o
    casting por metadado e o `_to_image` seguem valendo sem saber da origem."""
    calls = fake_post(_FakeResponse([_apify_item(0), _apify_item(1)]))
    client = InstagramScrapeClient(apify_token="apify_tok", min_resolution=(1080, 1350))
    images = client.search("rotina matinal", limit=2)

    assert "apify~instagram-scraper/run-sync-get-dataset-items" in calls[0]["url"]
    assert calls[0]["params"]["token"] == "apify_tok"
    # A hashtag vai por URL direta: `search`+`searchType` fazia o actor buscar
    # a hashtag no GOOGLE e devolver a entidade do resultado (sem post nenhum
    # no dataset) — e casando a hashtag errada ("aesthetic" → #gaesthetic).
    # As hashtags vão por URL direta: `search`+`searchType` fazia o actor
    # buscar a hashtag no GOOGLE e devolver a entidade do resultado (sem post
    # nenhum no dataset) — e casando a hashtag errada ("aesthetic" →
    # #gaesthetic). Um tema de duas palavras rende a hashtag colada e as duas
    # soltas, todas no MESMO run: `maxItems` limita a cobrança do run inteiro,
    # então o segundo alvo só é raspado se o primeiro não fechar a cota.
    assert calls[0]["json"]["directUrls"] == [
        "https://www.instagram.com/explore/tags/rotinamatinal/",
        "https://www.instagram.com/explore/tags/rotina/",
        "https://www.instagram.com/explore/tags/matinal/",
    ]
    assert "search" not in calls[0]["json"]
    assert calls[0]["json"]["addParentData"] is True
    assert calls[0]["json"]["resultsType"] == "posts"
    assert [img.image_id for img in images] == ["ig-314150", "ig-314151"]
    assert images[0].image_url == "https://scontent.cdninstagram.com/apify0.jpg"
    assert images[0].source_url == "https://www.instagram.com/p/Cabc0/"
    assert images[0].attribution_text == "@fulana no Instagram"
    # O `alt` do actor é o mesmo sinal que alimenta o casting por metadado.
    assert "1 person" in images[0].title
    assert client.last_fallback_reason == ""


def test_apify_wins_over_scrapedo(fake_post, fake_get):
    """Com os dois configurados, a Apify vence: o Scrape.do só troca o IP, e
    contra um gate de endpoint isso não passa."""
    posts = fake_post(_FakeResponse([_apify_item(0)]))
    gets = fake_get(_FakeResponse({}, status_code=302))
    client = InstagramScrapeClient(apify_token="a", scrapedo_token="s")
    images = client.search("rotina", limit=1)
    assert len(posts) == 1 and gets == []
    assert not is_mock_image(images[0])


def test_apify_uses_the_profile_url_for_an_at_handle(fake_post):
    calls = fake_post(_FakeResponse([_apify_item(0)]))
    InstagramScrapeClient(apify_token="a").search("@fulana", limit=2)
    assert calls[0]["json"]["directUrls"] == ["https://www.instagram.com/fulana/"]
    assert "search" not in calls[0]["json"]


def test_apify_caps_the_billed_items_and_the_run(fake_post):
    """Cada item do actor é pago e o run roda dentro do POST /generate: sem
    `maxItems` uma fatura surpresa, sem `timeout` o gunicorn mata o worker
    antes do fallback."""
    calls = fake_post(_FakeResponse([_apify_item(0)]))
    client = InstagramScrapeClient(apify_token="a", timeout=20)
    client.search("rotina", limit=4)
    wanted = calls[0]["json"]["resultsLimit"]
    assert wanted == 12  # max(limit*3, 12) — a busca sem cota exata
    assert calls[0]["params"]["maxItems"] == wanted
    assert calls[0]["params"]["limit"] == wanted
    assert calls[0]["params"]["clean"] == "1"
    # O teto do run fica abaixo do timeout do cliente, que sobe para 90s por
    # causa do cold start do actor.
    assert client._timeout == 90
    assert calls[0]["params"]["timeout"] < client._timeout


def test_apify_exact_search_keeps_the_user_quota_plus_rotation_slack(fake_post):
    """A cota do usuário decide quantas fotos ENTRAM; a folga decide que haja o
    que sortear.

    O pedido exato voltou a ter folga de propósito. O actor devolve os posts
    mais recentes do alvo, sempre na mesma ordem: pedir exatamente as fotos que
    vão para os slides é pedir o carrossel anterior de volta, que é a metade
    Instagram do "sempre o mesmo material". A folga é bem menor que o pool
    antigo de 3× (piso de 12), que era o que a cota exata tinha vindo cortar.
    """
    calls = fake_post(_FakeResponse([_apify_item(0), _apify_item(1)]))
    client = InstagramScrapeClient(apify_token="a")
    images = client.search_exact("@fulana", limit=2)

    esperado = 2 + client._ROTATION_SLACK  # noqa: SLF001
    assert esperado < 12, "a folga não pode voltar ao pool antigo"
    assert calls[0]["json"]["resultsLimit"] == esperado
    assert calls[0]["params"]["maxItems"] == esperado
    assert calls[0]["params"]["limit"] == esperado
    # O dataset devolveu duas: a cota é o teto do que entra, não um piso.
    assert len(images) == 2


def test_apify_reuses_the_same_profile_dataset_between_casting_pools(fake_post):
    calls = fake_post(_FakeResponse([_apify_item(i) for i in range(6)]))
    client = InstagramScrapeClient(apify_token="a")

    client.search("@fulana woman portrait", limit=2)
    client.search("@fulana aesthetic lifestyle", limit=4)

    assert len(calls) == 1


def test_apify_skips_videos_and_takes_the_carousel_cover(fake_post):
    fake_post(_FakeResponse([
        _apify_item(0, type="Video", videoUrl="https://v/0.mp4"),
        _apify_item(1, type="Sidecar", displayUrl="",
                    images=["https://scontent.cdninstagram.com/capa.jpg",
                            "https://scontent.cdninstagram.com/segunda.jpg"]),
    ]))
    images = InstagramScrapeClient(apify_token="a").search("rotina", limit=4)
    assert [img.image_id for img in images] == ["ig-314151"]
    assert images[0].image_url == "https://scontent.cdninstagram.com/capa.jpg"


def test_apify_sidecar_accepts_child_posts_and_original_dimensions(fake_post):
    fake_post(_FakeResponse([
        _apify_item(
            1,
            type="Sidecar",
            displayUrl="",
            images=[],
            dimensionsWidth=None,
            dimensionsHeight=None,
            originalWidth=1080,
            originalHeight=1350,
            childPosts=[
                {"type": "Video", "displayUrl": "https://cdn/video-cover.jpg"},
                {
                    "type": "Image",
                    "displayUrl": "https://scontent.cdninstagram.com/child.jpg",
                },
            ],
        )
    ]))

    images = InstagramScrapeClient(
        apify_token="a", min_resolution=(1080, 1350)
    ).search_exact("@fulana", limit=1)

    assert images[0].image_url.endswith("/child.jpg")


def test_apify_applies_the_slide_resolution_floor(fake_post):
    """O piso é o mesmo dos outros caminhos: foto menor que o slide seria
    ampliada no render e chegaria borrada ao feed."""
    fake_post(_FakeResponse([
        _apify_item(0, width=640, height=800),
        _apify_item(1, width=1080, height=1350),
    ]))
    images = InstagramScrapeClient(
        apify_token="a", min_resolution=(1080, 1350)
    ).search("rotina", limit=1)
    assert [img.image_id for img in images] == ["ig-314151"]


def test_apify_gateway_errors_do_not_read_as_instagram_blocks(fake_post):
    """401/402/404/408 são da Apify — "Instagram bloqueou" mandaria investigar
    o lugar errado (o Instagram nem foi chamado por nós)."""
    for status, needle in (
        (401, "token"), (402, "crédito"), (404, "APIFY_ACTOR"), (408, "cold start")
    ):
        fake_post(_FakeResponse({}, status_code=status))
        client = InstagramScrapeClient(apify_token="a")
        images = client.search("rotina", limit=2)
        assert all(is_mock_image(img) for img in images)
        assert needle in client.last_fallback_reason
        assert "Instagram" not in client.last_fallback_reason


def test_apify_unusable_dataset_names_the_field_mismatch(fake_post):
    """Dataset cheio e nada aproveitável = ou só vídeo, ou o actor usa outros
    nomes de campo. A segunda é cara de descobrir sem esta pista."""
    fake_post(_FakeResponse([{"foo": "bar"}, {"baz": 1}]))
    client = InstagramScrapeClient(apify_token="a")
    images = client.search("rotina", limit=2)
    assert all(is_mock_image(img) for img in images)
    assert "displayUrl" in client.last_fallback_reason


def test_apify_non_list_payload_is_not_read_as_the_login_wall(fake_post):
    fake_post(_FakeResponse({"error": {"type": "actor-not-found"}}))
    client = InstagramScrapeClient(apify_token="a", apify_actor="eu~errado")
    images = client.search("rotina", limit=2)
    assert all(is_mock_image(img) for img in images)
    assert "eu~errado" in client.last_fallback_reason
    assert "login" not in client.last_fallback_reason


def test_apify_timeout_names_apify_not_instagram(fake_post):
    fake_post(requests.Timeout())
    client = InstagramScrapeClient(apify_token="a")
    images = client.search("rotina", limit=2)
    assert all(is_mock_image(img) for img in images)
    assert client.last_fallback_reason.startswith("A Apify não respondeu")


def test_a_custom_actor_id_reaches_the_url(fake_post):
    calls = fake_post(_FakeResponse([_apify_item(0)]))
    InstagramScrapeClient(
        apify_token="a", apify_actor="outro~scraper"
    ).search("rotina", limit=1)
    assert "/acts/outro~scraper/run-sync-get-dataset-items" in calls[0]["url"]


# ---------- transporte Scrape.do ----------


def test_scrapedo_routes_the_same_call_through_the_gateway(fake_get):
    calls = fake_get(_FakeResponse(_tag_payload([_v1_media(0)])))
    client = InstagramScrapeClient(scrapedo_token="sd_tok")

    images = client.search("rotina matinal", limit=1)

    call = calls[0]
    assert call["url"] == "https://api.scrape.do/"
    assert call["params"]["token"] == "sd_tok"
    # O alvo é o MESMO endpoint da chamada direta, com a query embutida.
    assert call["params"]["url"] == (
        "https://www.instagram.com/api/v1/tags/web_info/?tag_name=rotinamatinal"
    )
    # Residencial: proxy de datacenter cai no mesmo balde do muro.
    assert call["params"]["super"] == "true"
    assert call["params"]["disableRedirection"] == "true"
    # extraHeaders põe o x-ig-app-id POR CIMA do fingerprint deles (o prefixo
    # sd- é o contrato); mandar o header cru não chegaria ao alvo.
    assert call["params"]["extraHeaders"] == "true"
    assert call["headers"]["sd-x-ig-app-id"]
    assert "x-ig-app-id" not in call["headers"]
    assert images and not is_mock_image(images[0])


def test_scrapedo_carries_the_profile_endpoint_too(fake_get):
    calls = fake_get(_FakeResponse(_profile_payload([_profile_node(0)])))
    InstagramScrapeClient(scrapedo_token="t").search("@fulana", limit=1)
    assert calls[0]["params"]["url"] == (
        "https://www.instagram.com/api/v1/users/web_profile_info/?username=fulana"
    )


def test_scrapedo_bumps_the_timeout_to_survive_the_gateway_retries(fake_get):
    """O gateway tenta vários IPs por dentro — os 20s da chamada direta
    cancelariam a chamada no meio (a mesma lição do VISION_TIMEOUT)."""
    calls = fake_get(_FakeResponse(_tag_payload([_v1_media(0)])))
    InstagramScrapeClient(timeout=20, scrapedo_token="t").search("rotina", limit=1)
    assert calls[0]["timeout"] == 60
    # Um REQUEST_TIMEOUT_SECONDS acima do piso continua mandando.
    calls = fake_get(_FakeResponse(_tag_payload([_v1_media(0)])))
    InstagramScrapeClient(timeout=90, scrapedo_token="t").search("rotina", limit=1)
    assert calls[0]["timeout"] == 90


def test_scrapedo_replaces_the_direct_call(fake_get):
    """O Scrape.do é transporte: a chamada sai para o gateway deles em vez de
    para o instagram.com, mas o payload e o parse são os mesmos."""
    calls = fake_get(_FakeResponse(_tag_payload([_v1_media(0)])))
    client = InstagramScrapeClient(scrapedo_token="t")
    images = client.search("rotina", limit=1)
    assert calls[0]["url"] == "https://api.scrape.do/"
    assert calls[0]["params"]["token"] == "t"
    assert not is_mock_image(images[0])


def test_the_redirect_header_from_scrapedo_reads_as_the_login_wall(fake_get):
    """Com disableRedirection, o muro volta como 200 + header apontando o
    /accounts/login/. O remédio antigo — "gera de novo, o IP do gateway
    rotaciona" — só queimava crédito (10x por chamada, com `super=true`): o
    gate é do endpoint, então os exits residenciais deles caem no mesmo 302."""
    fake_get(_FakeResponse(_tag_payload([_v1_media(0)]), headers={
        "Scrape.do-Target-Redirected-Location":
            "https://www.instagram.com/accounts/login/",
    }))
    client = InstagramScrapeClient(scrapedo_token="t")
    images = client.search("rotina", limit=2)
    assert all(is_mock_image(img) for img in images)
    assert "página de login" in client.last_fallback_reason
    assert "SCRAPEDO_TOKEN" in client.last_fallback_reason
    assert "gerar de novo" not in client.last_fallback_reason


def test_scrapedo_gateway_errors_do_not_read_as_instagram_blocks(fake_get):
    """401/429/502 vindos do gateway são token, concorrência e retries
    esgotados — não "Instagram bloqueou", que mandaria investigar o lugar
    errado."""
    for status, needle in ((401, "token"), (429, "concorrência"), (502, "crédito")):
        fake_get(_FakeResponse({}, status_code=status))
        client = InstagramScrapeClient(scrapedo_token="t")
        images = client.search("rotina", limit=2)
        assert all(is_mock_image(img) for img in images)
        assert needle in client.last_fallback_reason.lower()
        assert "acesso anônimo" not in client.last_fallback_reason


def test_timeout_falls_back_with_a_reason(fake_get):
    fake_get(requests.Timeout())
    client = InstagramScrapeClient(timeout=7)
    images = client.search("rotina", limit=4)
    assert all(is_mock_image(img) for img in images)
    assert "7s" in client.last_fallback_reason


def test_empty_result_falls_back_with_a_reason(fake_get):
    fake_get(_FakeResponse({"data": {}}))
    client = InstagramScrapeClient()
    images = client.search("rotina", limit=4)
    assert all(is_mock_image(img) for img in images)
    assert "#rotina" in client.last_fallback_reason


def test_a_query_with_nothing_usable_does_not_even_call(fake_get):
    calls = fake_get(_FakeResponse(_tag_payload([])))
    client = InstagramScrapeClient(hint_words=["aesthetic"])
    images = client.search("aesthetic", limit=4)
    assert all(is_mock_image(img) for img in images)
    assert not calls


# ---------- busca combinada ----------


class _StubClient:
    def __init__(self, name, images=None, reason="", error=None):
        self.name = name
        self._images = images or []
        self.last_fallback_reason = reason
        self._error = error
        self.queries = []

    def search(self, query, limit=8):
        self.queries.append((query, limit))
        if self._error:
            raise self._error
        return list(self._images)[:limit]


class _ExactStubClient(_StubClient):
    def __init__(self, name, images=None, reason="", error=None):
        super().__init__(name, images, reason, error)
        self.exact_limits = []

    def search_exact(self, query, limit=8):
        self.queries.append((query, limit))
        self.exact_limits.append(limit)
        if self._error:
            raise self._error
        return list(self._images)[:limit]


def _img(image_id):
    return PinterestImage(
        image_id=image_id,
        image_url=f"https://cdn/{image_id}.jpg",
        source_url=f"https://site/{image_id}/",
        title=image_id,
    )


def test_combined_interleaves_the_two_sources():
    combined = CombinedImageClient([
        _StubClient("instagram_scrape", [_img("ig-1"), _img("ig-2"), _img("ig-3")]),
        _StubClient("pinterest_scrape", [_img("p-1"), _img("p-2"), _img("p-3")]),
    ], name="instagram_pinterest")
    images = combined.search("rotina", limit=4)
    assert [img.image_id for img in images] == ["ig-1", "p-1", "ig-2", "p-2"]


def test_combined_quota_reserves_one_instagram_photo_for_the_hook():
    instagram = _ExactStubClient(
        "instagram_scrape", [_img("ig-1"), _img("ig-2"), _img("ig-3")]
    )
    pinterest = _StubClient(
        "pinterest_scrape", [_img("p-1"), _img("p-2"), _img("p-3")]
    )
    combined = CombinedImageClient(
        [instagram, pinterest],
        name="instagram_pinterest",
        source_limits={"instagram_scrape": 3},
    )

    hook = combined.search_pool(
        "rotina @fulana #cafe woman portrait", limit=4, pool="hook"
    )
    scene = combined.search_pool(
        "rotina @fulana #cafe lifestyle", limit=5, pool="scene"
    )

    assert instagram.exact_limits == [3]
    assert [img.image_id for img in hook if img.image_id.startswith("ig-")] == ["ig-1"]
    assert [img.image_id for img in scene if img.image_id.startswith("ig-")] == [
        "ig-2", "ig-3"
    ]
    assert sum(img.image_id.startswith("ig-") for img in hook + scene) == 3
    assert "@fulana" in instagram.queries[0][0]
    assert all("@fulana" not in query for query, _ in pinterest.queries)
    assert all("cafe" in query and "#cafe" not in query for query, _ in pinterest.queries)


def test_combined_uses_a_generic_pinterest_query_when_only_a_profile_was_given():
    instagram = _StubClient("instagram_scrape", [_img("ig-1")])
    pinterest = _StubClient("pinterest_scrape", [_img("p-1")])
    combined = CombinedImageClient(
        [instagram, pinterest], name="instagram_pinterest"
    )

    combined.search("@fulana", limit=2)

    assert pinterest.queries == [("lifestyle aesthetic", 2)]


def test_combined_fills_from_the_other_source_when_one_returns_little():
    combined = CombinedImageClient([
        _StubClient("instagram_scrape", [_img("ig-1")]),
        _StubClient("pinterest_scrape", [_img("p-1"), _img("p-2"), _img("p-3")]),
    ])
    images = combined.search("rotina", limit=4)
    assert [img.image_id for img in images] == ["ig-1", "p-1", "p-2", "p-3"]


def test_combined_drops_mock_results_from_a_failed_source():
    mocks = MockPinterestClient().search("rotina", limit=2)
    combined = CombinedImageClient([
        _StubClient("instagram_scrape", mocks, reason="Instagram bloqueou."),
        _StubClient("pinterest_scrape", [_img("p-1")]),
    ])
    images = combined.search("rotina", limit=4)
    assert [img.image_id for img in images] == ["p-1"]


def test_combined_deduplicates_by_image_id():
    combined = CombinedImageClient([
        _StubClient("a", [_img("x"), _img("y")]),
        _StubClient("b", [_img("x"), _img("z")]),
    ])
    images = combined.search("rotina", limit=8)
    assert [img.image_id for img in images] == ["x", "y", "z"]


def test_combined_falls_back_to_mock_with_the_joined_reasons():
    combined = CombinedImageClient([
        _StubClient("instagram_scrape", [], reason="Instagram bloqueou."),
        _StubClient("pinterest_scrape", [], reason="Pinterest sem pins."),
    ])
    images = combined.search("rotina", limit=4)
    assert all(is_mock_image(img) for img in images)
    assert "Instagram bloqueou." in combined.last_fallback_reason
    assert "Pinterest sem pins." in combined.last_fallback_reason


def test_combined_survives_a_client_that_raises():
    combined = CombinedImageClient([
        _StubClient("a", error=RuntimeError("boom")),
        _StubClient("b", [_img("p-1")]),
    ])
    assert [img.image_id for img in combined.search("q", limit=2)] == ["p-1"]


def test_combined_forwards_related_to_the_client_that_has_it():
    class _WithRelated(_StubClient):
        def related(self, pin_url, limit=8):
            return [_img("rel-1")]

    combined = CombinedImageClient([
        _StubClient("instagram_scrape"),
        _WithRelated("pinterest_scrape"),
    ])
    assert [i.image_id for i in combined.related("https://pin", limit=2)] == ["rel-1"]


def test_unsplash_pinterest_without_a_key_still_fills_from_pinterest():
    """A metade sem chave cai no mock (sem ir à rede) e o Pinterest preenche —
    o mesmo contrato do instagram_pinterest sem APIFY_TOKEN."""
    combined = CombinedImageClient([
        UnsplashClient(access_key=""),
        _StubClient("pinterest_scrape", [_img("p-1"), _img("p-2")]),
    ], name="unsplash_pinterest")
    images = combined.search("rotina", limit=2)
    assert [img.image_id for img in images] == ["p-1", "p-2"]


def test_unsplash_pinterest_with_both_down_names_the_missing_key():
    """Quando as DUAS fontes caem, o motivo somado precisa apontar a chave que
    falta — e não um "Unsplash recusou a chave" de uma chave que não existe."""
    combined = CombinedImageClient([
        UnsplashClient(access_key=""),
        _StubClient("pinterest_scrape", [], reason="Pinterest sem pins."),
    ], name="unsplash_pinterest")
    images = combined.search("rotina", limit=2)
    assert all(is_mock_image(img) for img in images)
    assert "UNSPLASH_ACCESS_KEY" in combined.last_fallback_reason
    assert "Pinterest sem pins." in combined.last_fallback_reason


# ---------- fábrica e settings ----------


def test_factory_builds_the_instagram_client():
    settings = Settings.from_env({"IMAGE_PROVIDER": "instagram_scrape"})
    client = build_pinterest_client(settings)
    assert isinstance(client, InstagramScrapeClient)


def test_factory_builds_the_combined_client_with_both_sources():
    settings = Settings.from_env({"IMAGE_PROVIDER": "instagram_pinterest"})
    client = build_pinterest_client(settings)
    assert isinstance(client, CombinedImageClient)
    assert client.name == "instagram_pinterest"
    assert any(isinstance(c, InstagramScrapeClient) for c in client._clients)
    assert any(isinstance(c, PinterestScrapeClient) for c in client._clients)


def test_factory_builds_the_unsplash_pinterest_pair(monkeypatch):
    monkeypatch.setenv("UNSPLASH_ACCESS_KEY", "chave")
    settings = Settings.from_env({"IMAGE_PROVIDER": "unsplash_pinterest"})
    client = build_pinterest_client(settings)
    assert isinstance(client, CombinedImageClient)
    assert client.name == "unsplash_pinterest"
    assert any(isinstance(c, UnsplashClient) for c in client._clients)
    assert any(isinstance(c, PinterestScrapeClient) for c in client._clients)


def test_the_unsplash_pinterest_pair_survives_a_missing_key(monkeypatch):
    """Sem a chave o par entra INTEIRO mesmo assim — como o Instagram sem
    APIFY_TOKEN no outro combinado: a metade fadada a cair devolve mock com o
    motivo, o combinado descarta o mock e o Pinterest preenche. Um cliente
    solo aqui esconderia por que metade das fotos não veio."""
    monkeypatch.setenv("UNSPLASH_ACCESS_KEY", "")
    settings = Settings.from_env({"IMAGE_PROVIDER": "unsplash_pinterest"})
    client = build_pinterest_client(settings)
    assert isinstance(client, CombinedImageClient)
    assert client.name == "unsplash_pinterest"
    assert any(isinstance(c, UnsplashClient) for c in client._clients)


def test_ui_override_beats_the_environment_provider():
    settings = Settings.from_env({"IMAGE_PROVIDER": "mock"})
    client = build_pinterest_client(settings, override="instagram_scrape")
    assert isinstance(client, InstagramScrapeClient)


def test_an_unknown_override_falls_back_to_the_environment():
    settings = Settings.from_env({"IMAGE_PROVIDER": "mock"})
    client = build_pinterest_client(settings, override="tiktok")
    assert isinstance(client, MockPinterestClient)


def test_instagram_providers_are_valid_settings_values():
    assert Settings.from_env(
        {"IMAGE_PROVIDER": "instagram_scrape"}
    ).image_provider == "instagram_scrape"
    assert Settings.from_env(
        {"IMAGE_PROVIDER": "instagram_pinterest"}
    ).image_provider == "instagram_pinterest"


def test_unsplash_pinterest_is_a_valid_settings_value():
    assert Settings.from_env(
        {"IMAGE_PROVIDER": "unsplash_pinterest"}
    ).image_provider == "unsplash_pinterest"


def test_instagram_client_inherits_the_slide_floor_and_the_hints():
    settings = Settings.from_env({"IMAGE_PROVIDER": "instagram_scrape"})
    client = build_pinterest_client(settings)
    assert client._min_resolution == (1080, 1350)
    # As dicas de casting não podem virar hashtag.
    assert "portrait" in client._hint_words
    assert "aesthetic" in client._hint_words


def test_apify_settings_reach_the_client_and_win_over_scrapedo():
    settings = Settings.from_env({
        "IMAGE_PROVIDER": "instagram_scrape",
        "APIFY_TOKEN": "apify_tok",
        "APIFY_ACTOR": "outro~scraper",
        "SCRAPEDO_TOKEN": "sd_tok",
    })
    client = build_pinterest_client(settings)
    assert client._apify_token == "apify_tok"
    assert client._apify_actor == "outro~scraper"
    # O Scrape.do continua chegando ao cliente; quem decide a precedência é o
    # `search`, e é a Apify que vence (ver test_apify_wins_over_scrapedo).
    assert client._scrapedo_token == "sd_tok"

    bare = build_pinterest_client(
        Settings.from_env({"IMAGE_PROVIDER": "instagram_scrape"})
    )
    assert bare._apify_token == ""
    # Sem APIFY_ACTOR o default é o actor de Instagram da própria Apify.
    assert bare._apify_actor == "apify~instagram-scraper"


def test_scrapedo_token_reaches_the_client_from_the_settings():
    settings = Settings.from_env({
        "IMAGE_PROVIDER": "instagram_scrape",
        "SCRAPEDO_TOKEN": "sd_tok",
    })
    client = build_pinterest_client(settings)
    assert client._scrapedo_token == "sd_tok"
    assert build_pinterest_client(
        Settings.from_env({"IMAGE_PROVIDER": "instagram_scrape"})
    )._scrapedo_token == ""


# ---------- alvos: o termo pode ser perfil, hashtag, ou os dois ----------


def test_a_one_word_term_is_tried_as_a_profile_and_as_a_hashtag():
    """O caso `bellebres`: o termo é um USUÁRIO do Instagram.

    Buscar essa palavra no site devolve o perfil de mesmo nome e os posts dele;
    `#bellebres` não existe. O app pedia só a hashtag, recebia nada e caía no
    gradiente — embora o termo tivesse resultado na plataforma. Perfil primeiro
    porque é a leitura que casa com uma palavra sem espaço.
    """
    from app.adapters.pinterest_client import _ig_targets

    alvos = _ig_targets("bellebres")

    assert [(a.kind, a.value) for a in alvos] == [
        ("profile", "bellebres"),
        ("tag", "bellebres"),
    ]


def test_a_theme_with_spaces_is_not_a_handle():
    """Tema de várias palavras vira a hashtag colada e as palavras soltas —
    perfil não entra, porque handle não tem espaço."""
    from app.adapters.pinterest_client import _ig_targets

    alvos = _ig_targets("rotina matinal")

    assert all(a.kind == "tag" for a in alvos)
    assert [a.value for a in alvos] == ["rotinamatinal", "rotina", "matinal"]


def test_an_explicit_choice_is_the_only_target():
    """Quem escreveu `@perfil` ou `#hashtag` disse qual alvo quer: adivinhar
    outro só gastaria item pago da Apify."""
    from app.adapters.pinterest_client import _ig_targets

    assert [(a.kind, a.value) for a in _ig_targets("fotos de @fulana")] == [
        ("profile", "fulana")
    ]
    assert [(a.kind, a.value) for a in _ig_targets("rotina #morningroutine")] == [
        ("tag", "morningroutine")
    ]


def test_the_casting_hints_do_not_become_targets():
    from app.adapters.pinterest_client import _ig_targets

    alvos = _ig_targets(
        "rotina woman portrait", hint_words=["woman", "portrait"]
    )

    assert [(a.kind, a.value) for a in alvos] == [
        ("profile", "rotina"),
        ("tag", "rotina"),
    ]


def test_the_number_of_targets_is_capped():
    """Cada alvo é uma URL a mais no run da Apify, e item de actor é pago."""
    from app.adapters.pinterest_client import _IG_MAX_TARGETS, _ig_targets

    alvos = _ig_targets("cinco palavras diferentes no tema aqui")

    assert len(alvos) <= _IG_MAX_TARGETS


def test_a_term_that_is_only_a_profile_still_fills_the_carousel(fake_get):
    """A ponta a ponta do `bellebres` sem token: a hashtag não existe, o perfil
    existe, e o carrossel sai com fotos reais em vez de gradiente."""
    perfil = {
        "data": {
            "user": {
                "edge_owner_to_timeline_media": {
                    "edges": [
                        {
                            "node": {
                                "id": f"90{i}",
                                "shortcode": f"Cx{i}",
                                "display_url": f"https://scontent.cdninstagram.com/b{i}.jpg",
                                "dimensions": {"width": 1080, "height": 1350},
                                "accessibility_caption": "May be an image of 1 person",
                                "owner": {"username": "bellebres"},
                            }
                        }
                        for i in range(6)
                    ]
                }
            }
        }
    }
    fake_get(_FakeResponse(perfil))
    client = InstagramScrapeClient(min_resolution=(1080, 1350))

    images = client.search("bellebres", limit=3)

    assert len(images) == 3
    assert not any(is_mock_image(img) for img in images)
    assert all("bellebres" in img.attribution_text for img in images)
    assert client.last_fallback_reason == ""


def test_a_dead_first_target_does_not_end_the_search(fake_get):
    """404 no perfil é "esse alvo não existe", não "a busca falhou": a hashtag
    de mesmo nome ainda pode responder."""
    fake_get([
        _FakeResponse({}, status_code=404),
        _FakeResponse(_tag_payload([_v1_media(i) for i in range(4)])),
    ])
    client = InstagramScrapeClient(min_resolution=(1080, 1350))

    images = client.search("skincare", limit=2)

    assert len(images) == 2
    assert not any(is_mock_image(img) for img in images)


def test_the_reason_says_both_readings_were_tried(fake_get):
    fake_get(_FakeResponse({}, status_code=404))
    client = InstagramScrapeClient()

    client.search("termoinexistente", limit=2)

    assert "perfil" in client.last_fallback_reason
    assert "hashtag" in client.last_fallback_reason
    assert "404" in client.last_fallback_reason


# ---------- rotação: a mesma hashtag não devolve o mesmo carrossel ----------


def test_photos_from_recent_carousels_go_to_the_end_of_the_draw(fake_post):
    """O Instagram não tinha a memória do que já saiu, e era metade do "sempre
    as mesmas fotos": o dataset da Apify vem sempre na mesma ordem, então sem
    memória nem sorteio a mesma hashtag rendia o mesmo carrossel."""
    from app.adapters.pinterest_client import media_identity

    itens = [_apify_item(i) for i in range(10)]
    fake_post(_FakeResponse(itens))
    ja_usadas = [
        media_identity(f"https://scontent.cdninstagram.com/apify{i}.jpg")
        for i in range(8)
    ]

    client = InstagramScrapeClient(apify_token="a", avoid_media=ja_usadas)
    images = client.search("rotina matinal", limit=2)

    assert {img.image_url for img in images} == {
        "https://scontent.cdninstagram.com/apify8.jpg",
        "https://scontent.cdninstagram.com/apify9.jpg",
    }


def test_an_exhausted_memory_still_returns_a_carousel(fake_post):
    """Acervo inteiro já usado não pode devolver carrossel vazio — a memória é
    preferência, não veto."""
    from app.adapters.pinterest_client import media_identity

    itens = [_apify_item(i) for i in range(6)]
    fake_post(_FakeResponse(itens))
    todas = [
        media_identity(f"https://scontent.cdninstagram.com/apify{i}.jpg")
        for i in range(6)
    ]

    client = InstagramScrapeClient(apify_token="a", avoid_media=todas)

    assert len(client.search("rotina matinal", limit=3)) == 3
