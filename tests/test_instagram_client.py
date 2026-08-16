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
        # Uma lista de respostas serve para simular o proxy rotativo: uma
        # resposta por chamada, na ordem.
        queue = list(response) if isinstance(response, list) else None

        def _get(url, params=None, headers=None, timeout=None, proxies=None,
                 allow_redirects=True, verify=True):
            calls.append({
                "url": url,
                "params": params or {},
                "headers": headers or {},
                "timeout": timeout,
                "proxies": proxies,
                "allow_redirects": allow_redirects,
                "verify": verify,
            })
            current = queue.pop(0) if queue is not None else response
            if isinstance(current, Exception):
                raise current
            return current

        monkeypatch.setattr("app.adapters.pinterest_client.requests.get", _get)
        return calls

    return _install


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


def test_without_high_res_stock_the_floor_gives_way(fake_get):
    fake_get(_FakeResponse(_tag_payload([_v1_media(0, width=474, height=711)])))
    client = InstagramScrapeClient(min_resolution=(1080, 1350))
    images = client.search("rotina", limit=1)
    assert not is_mock_image(images[0])


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
    """De um IP no balde do muro, a API 302-redireciona para /accounts/login/.
    Seguir o redirect só baixaria o HTML do login — o redirect já É a resposta,
    e o motivo aponta o remédio (o IP de saída, não o código)."""
    calls = fake_get(_FakeResponse({}, status_code=302))
    client = InstagramScrapeClient()
    images = client.search("rotina", limit=4)
    assert all(is_mock_image(img) for img in images)
    assert calls[0]["allow_redirects"] is False
    assert "página de login" in client.last_fallback_reason
    assert "INSTAGRAM_PROXY" in client.last_fallback_reason


def test_the_proxy_reaches_only_the_instagram_request(fake_get):
    calls = fake_get(_FakeResponse(_tag_payload([_v1_media(0)])))
    proxy = "http://user:pass@10.0.0.1:8080"
    InstagramScrapeClient(proxy=proxy).search("rotina", limit=1)
    assert calls[0]["proxies"] == {"http": proxy, "https": proxy}


def test_without_proxy_the_request_keeps_the_environment_defaults(fake_get):
    """proxies=None deixa o requests honrar um HTTPS_PROXY global do ambiente."""
    calls = fake_get(_FakeResponse(_tag_payload([_v1_media(0)])))
    InstagramScrapeClient().search("rotina", limit=1)
    assert calls[0]["proxies"] is None


def test_walled_with_a_proxy_blames_the_proxy_ip(fake_get):
    """Com proxy configurado, "configure INSTAGRAM_PROXY" seria conselho já
    seguido — o aviso tem que dizer que o IP DO PROXY caiu no muro."""
    fake_get(_FakeResponse({}, status_code=302))
    client = InstagramScrapeClient(proxy="http://10.0.0.1:8080")
    client.search("rotina", limit=2)
    assert "proxy" in client.last_fallback_reason.lower()
    assert "também caiu" in client.last_fallback_reason


def test_a_rotating_proxy_gets_three_tries_at_the_wall(fake_get):
    """Pools rotativos (ScrapeOps etc.) sorteiam outro IP a cada conexão — um
    exit no muro não condena os próximos, então vale repetir."""
    calls = fake_get([
        _FakeResponse({}, status_code=302),
        _FakeResponse({}, status_code=302),
        _FakeResponse(_tag_payload([_v1_media(0)])),
    ])
    client = InstagramScrapeClient(proxy="http://10.0.0.1:8080")
    images = client.search("rotina", limit=1)
    assert len(calls) == 3
    assert not is_mock_image(images[0])
    assert client.last_fallback_reason == ""


def test_still_walled_after_the_retries_falls_back_with_the_reason(fake_get):
    calls = fake_get([_FakeResponse({}, status_code=302)] * 3)
    client = InstagramScrapeClient(proxy="http://10.0.0.1:8080")
    images = client.search("rotina", limit=2)
    assert len(calls) == 3
    assert all(is_mock_image(img) for img in images)
    assert "também caiu" in client.last_fallback_reason


def test_without_a_proxy_the_wall_is_not_retried(fake_get):
    """Sem proxy o IP de saída é sempre o mesmo — repetir seria só latência."""
    calls = fake_get(_FakeResponse({}, status_code=302))
    InstagramScrapeClient().search("rotina", limit=2)
    assert len(calls) == 1


def test_an_insecure_proxy_disables_tls_verification_only_when_asked(fake_get):
    """Portas-proxy de agregadores (ScrapeOps) interceptam o TLS e as docs
    deles mandam desligar a validação — opt-in, nunca o default."""
    calls = fake_get(_FakeResponse(_tag_payload([_v1_media(0)])))
    InstagramScrapeClient(
        proxy="http://scrapeops.mobile=true:key@residential-proxy.scrapeops.io:8181",
        proxy_insecure=True,
    ).search("rotina", limit=1)
    assert calls[0]["verify"] is False
    calls = fake_get(_FakeResponse(_tag_payload([_v1_media(0)])))
    InstagramScrapeClient().search("rotina", limit=1)
    assert calls[0]["verify"] is True


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


def test_scrapedo_wins_over_a_configured_proxy(fake_get):
    calls = fake_get(_FakeResponse(_tag_payload([_v1_media(0)])))
    client = InstagramScrapeClient(
        proxy="http://10.0.0.1:8080", scrapedo_token="t"
    )
    client.search("rotina", limit=1)
    assert calls[0]["url"] == "https://api.scrape.do/"
    assert calls[0]["proxies"] is None


def test_the_redirect_header_from_scrapedo_reads_as_the_login_wall(fake_get):
    """Com disableRedirection, o muro volta como 200 + header apontando o
    /accounts/login/ — e o remédio não é INSTAGRAM_PROXY (a chamada já saiu
    por proxy): é gerar de novo, porque o IP do gateway rotaciona."""
    fake_get(_FakeResponse(_tag_payload([_v1_media(0)]), headers={
        "Scrape.do-Target-Redirected-Location":
            "https://www.instagram.com/accounts/login/",
    }))
    client = InstagramScrapeClient(scrapedo_token="t")
    images = client.search("rotina", limit=2)
    assert all(is_mock_image(img) for img in images)
    assert "página de login" in client.last_fallback_reason
    assert "Scrape.do" in client.last_fallback_reason
    assert "INSTAGRAM_PROXY" not in client.last_fallback_reason


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

    def search(self, query, limit=8):
        if self._error:
            raise self._error
        return list(self._images)


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


def test_instagram_client_inherits_the_slide_floor_and_the_hints():
    settings = Settings.from_env({"IMAGE_PROVIDER": "instagram_scrape"})
    client = build_pinterest_client(settings)
    assert client._min_resolution == (1080, 1350)
    # As dicas de casting não podem virar hashtag.
    assert "portrait" in client._hint_words
    assert "aesthetic" in client._hint_words


def test_instagram_proxy_reaches_the_client_from_the_settings():
    proxy = "http://user:pass@10.0.0.1:8080"
    settings = Settings.from_env({
        "IMAGE_PROVIDER": "instagram_scrape",
        "INSTAGRAM_PROXY": proxy,
    })
    client = build_pinterest_client(settings)
    assert client._proxies == {"http": proxy, "https": proxy}
    # Sem a variável, o cliente sai sem proxy fixo (ambiente decide).
    bare = build_pinterest_client(
        Settings.from_env({"IMAGE_PROVIDER": "instagram_scrape"})
    )
    assert bare._proxies is None


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


def test_proxy_insecure_reaches_the_client_from_the_settings():
    settings = Settings.from_env({
        "IMAGE_PROVIDER": "instagram_scrape",
        "INSTAGRAM_PROXY": "http://scrapeops:key@residential-proxy.scrapeops.io:8181",
        "INSTAGRAM_PROXY_INSECURE": "true",
    })
    assert build_pinterest_client(settings)._verify is False
    assert build_pinterest_client(
        Settings.from_env({"IMAGE_PROVIDER": "instagram_scrape"})
    )._verify is True
