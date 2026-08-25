"""Testes da busca on-spot — mais fotos do mesmo @, pedidas pela prévia.

Duas fontes em ordem: o Instagram (Apify, os posts do próprio perfil, pago por
item) e o Pinterest como reserva de graça, onde o handle **sem arroba** é um
termo de busca legítimo. Nenhum teste toca a rede: as duas fábricas de cliente
são substituídas por fakes.
"""

from __future__ import annotations

import pytest

from app.adapters.pinterest_client import PinterestImage
from app.config import Settings
from app.services import hook_search
from app.services.hook_search import normalize_handle, search_by_handle, search_by_query


def _settings(**over) -> Settings:
    env = {
        "FLASK_ENV": "testing",
        "SECRET_KEY": "x",
        "APIFY_TOKEN": "apify-token",
    }
    env.update(over)
    return Settings.from_env(env)


def _img(image_id: str) -> PinterestImage:
    return PinterestImage(
        image_id=image_id,
        image_url=f"https://img/{image_id}.jpg",
        source_url="https://source",
        title=image_id,
    )


class _FakeClient:
    name = "fake"

    def __init__(self, images, reason=""):
        self._images = list(images)
        self.last_fallback_reason = reason
        self.queries: list[tuple[str, int]] = []

    def search(self, query, limit=8):
        self.queries.append((query, limit))
        return list(self._images)

    def search_exact(self, query, limit=8):
        self.queries.append((query, limit))
        return list(self._images)


@pytest.fixture
def sources(monkeypatch):
    """Instala os dois clientes e devolve o par para inspeção."""

    def _install(instagram, pinterest):
        monkeypatch.setattr(
            hook_search, "_instagram_scrape_client", lambda s, **k: instagram
        )
        monkeypatch.setattr(
            hook_search, "_pinterest_scrape_client", lambda s, **k: pinterest
        )
        return instagram, pinterest

    return _install


# ---------- normalização do @ ----------


@pytest.mark.parametrize("raw,expected", [
    ("@bellebres", "bellebres"),
    ("bellebres", "bellebres"),
    ("  @Belle.Bres  ", "belle.bres"),
    ("https://www.instagram.com/bellebres/", "bellebres"),
    ("instagram.com/bellebres?hl=pt", "bellebres"),
    ("@", ""),
    ("   ", ""),
])
def test_the_handle_is_normalized_however_it_was_typed(raw, expected):
    """O usuário digita com arroba, sem arroba, com espaço sobrando ou colando
    a URL do perfil — as quatro formas viram a mesma chave de busca."""
    assert normalize_handle(raw) == expected


# ---------- a ordem das fontes ----------


def test_the_instagram_answers_first_and_the_pinterest_is_not_charged(sources):
    """O Instagram devolve os posts do próprio perfil, que é a resposta certa
    para "mais fotos desta modelo". Achando lá, o Pinterest nem é consultado."""
    instagram, pinterest = sources(
        _FakeClient([_img("ig-1"), _img("ig-2")]), _FakeClient([_img("pin-1")])
    )

    found, source, reason = search_by_handle(
        _settings(), "bellebres", avoid_ids=set()
    )

    assert [img.image_id for img in found] == ["ig-1", "ig-2"]
    assert source == "instagram"
    assert not reason
    assert instagram.queries == [("@bellebres", 5)]
    assert pinterest.queries == []


def test_the_pinterest_covers_for_an_instagram_that_found_nothing(sources):
    instagram, pinterest = sources(
        _FakeClient([], reason="Perfil não encontrado."), _FakeClient([_img("pin-1")])
    )

    found, source, reason = search_by_handle(
        _settings(), "bellebres", avoid_ids=set()
    )

    assert [img.image_id for img in found] == ["pin-1"]
    assert source == "pinterest"
    assert not reason


def test_the_pinterest_is_asked_without_the_at(sources):
    """`bellebres` devolve 50 pins no site e `@bellebres` devolve zero —
    medido em 2026-08-25. Mandar o sigilo junto seria pedir nada."""
    _, pinterest = sources(_FakeClient([]), _FakeClient([_img("pin-1")]))

    search_by_handle(_settings(), "bellebres", avoid_ids=set())

    assert pinterest.queries == [("bellebres", 5)]


def test_without_an_apify_token_the_instagram_is_not_even_tried(sources):
    """Sem token o endpoint de perfil está atrás do muro de login — dizer isso
    é mais útil que gastar uma chamada que já se sabe que falha."""
    instagram, pinterest = sources(_FakeClient([_img("ig-1")]), _FakeClient([]))

    found, _, reason = search_by_handle(
        _settings(APIFY_TOKEN=""), "bellebres", avoid_ids=set()
    )

    assert instagram.queries == []
    assert not found
    assert "APIFY_TOKEN" in reason


# ---------- o que já está na galeria não é alternativa ----------


def test_a_photo_the_project_already_has_is_not_offered_again(sources):
    sources(_FakeClient([_img("ig-1"), _img("ig-2")]), _FakeClient([]))

    found, _, _ = search_by_handle(
        _settings(), "bellebres", avoid_ids={"ig-1"}
    )

    assert [img.image_id for img in found] == ["ig-2"]


def test_the_pinterest_answers_when_the_instagram_only_repeats(sources):
    """Fonte que só devolve o que o projeto já tem conta como vazia — senão a
    busca "funcionaria" sem acrescentar alternativa nenhuma."""
    sources(_FakeClient([_img("ig-1")]), _FakeClient([_img("pin-1")]))

    found, source, _ = search_by_handle(
        _settings(), "bellebres", avoid_ids={"ig-1"}
    )

    assert [img.image_id for img in found] == ["pin-1"]
    assert source == "pinterest"


def test_nothing_anywhere_comes_back_with_the_reasons(sources):
    sources(
        _FakeClient([], reason="Perfil não encontrado."),
        _FakeClient([], reason="O Pinterest não retornou pins."),
    )

    found, source, reason = search_by_handle(
        _settings(), "bellebres", avoid_ids=set()
    )

    assert not found
    assert not source
    assert "Perfil não encontrado." in reason
    assert "O Pinterest não retornou pins." in reason


def test_a_source_that_raises_does_not_take_the_other_down(sources):
    class _Boom:
        last_fallback_reason = ""

        def search_exact(self, query, limit=8):
            raise RuntimeError("timeout")

    sources(_Boom(), _FakeClient([_img("pin-1")]))

    found, source, _ = search_by_handle(
        _settings(), "bellebres", avoid_ids=set()
    )

    assert [img.image_id for img in found] == ["pin-1"]
    assert source == "pinterest"


def test_query_search_uses_the_configured_source_and_filters_existing_media(monkeypatch):
    client = _FakeClient([_img("old"), _img("new")])
    monkeypatch.setattr(hook_search, "build_pinterest_client", lambda *a, **k: client)

    found, source, reason = search_by_query(
        _settings(),
        "  mulher lendo  ",
        image_source="unsplash",
        avoid_ids={"old"},
    )

    assert [img.image_id for img in found] == ["new"]
    assert source == "fake"
    assert not reason
    assert client.queries == [("mulher lendo", 5)]


def test_query_search_explains_empty_query():
    found, source, reason = search_by_query(
        _settings(), " ", avoid_ids=set()
    )

    assert not found
    assert not source
    assert "Escreva" in reason
