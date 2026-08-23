"""Testes da memória de fotos — o que já saiu não volta no próximo carrossel.

O defeito que originou este arquivo: gerar duas vezes com a mesma hashtag
devolvia quase as mesmas fotos. O pool raso da busca era a causa maior (ver
`test_pinterest_scrape.py`), mas o sorteio não tem memória — nada impedia o
acaso de repetir a foto do carrossel anterior.

Nenhum teste toca o disco real: o `conftest.py` manda o JSON para o tmp_path.
"""

from __future__ import annotations

import json

import pytest

from app.adapters.pinterest_client import PinterestImage
from app.config import Settings
from app.services import recent_media
from app.services.generation import GenerationService
from app.services.recent_media import (
    MAX_REMEMBERED,
    clear_recent,
    load_recent,
    remember,
)
from app.services.session_store import reset_store

RAW = "5 dicas matinais. Beba água, alongue, escreva as prioridades, tome café."


@pytest.fixture(autouse=True)
def _clean_store():
    reset_store()
    yield
    reset_store()


@pytest.fixture(autouse=True)
def _no_promo_assets(monkeypatch):
    monkeypatch.setattr("app.services.goviral_assets.list_asset_files", lambda: [])


# ---------- o arquivo ----------


def test_memory_starts_empty_and_survives_a_round_trip():
    assert load_recent() == frozenset()

    remember(["i.pinimg.com/aa/bb/um", "i.pinimg.com/aa/bb/dois"])

    assert load_recent() == {"i.pinimg.com/aa/bb/um", "i.pinimg.com/aa/bb/dois"}


def test_a_photo_used_twice_in_the_same_carousel_takes_one_slot():
    remember(["mesma", "mesma", "outra"])

    assert json.loads(open(recent_media.RECENT_MEDIA_PATH, encoding="utf-8").read())[
        "identities"
    ] == ["mesma", "outra"]


def test_the_oldest_photos_are_the_ones_dropped():
    """A fila é antiga → recente: o corte tem que descartar o que já pode voltar
    a aparecer sem incomodar, não o carrossel que acabou de sair."""
    remember([f"antiga-{i}" for i in range(MAX_REMEMBERED)])
    remember(["recem-usada"])

    memoria = load_recent()

    assert "recem-usada" in memoria
    assert "antiga-0" not in memoria
    assert len(memoria) == MAX_REMEMBERED


def test_using_a_remembered_photo_again_moves_it_back_to_the_end():
    remember(["a", "b", "c"])
    remember(["a"])

    fila = json.loads(open(recent_media.RECENT_MEDIA_PATH, encoding="utf-8").read())

    assert fila["identities"] == ["b", "c", "a"]


def test_an_unreadable_file_reads_as_an_empty_memory():
    with open(recent_media.RECENT_MEDIA_PATH, "w", encoding="utf-8") as fh:
        fh.write("{nao é json")

    assert load_recent() == frozenset()


def test_remembering_nothing_does_not_create_the_file():
    remember([])

    assert load_recent() == frozenset()


def test_clear_removes_the_memory():
    remember(["alguma"])
    clear_recent()

    assert load_recent() == frozenset()


# ---------- a integração com a geração ----------


class _FakeClient:
    name = "fake"
    last_fallback_reason = ""

    def __init__(self):
        self.queries: list[tuple[str, int]] = []

    def search(self, query: str, limit: int = 10) -> list[PinterestImage]:
        self.queries.append((query, limit))
        tag = f"q{len(self.queries)}"
        return [
            PinterestImage(
                image_id=f"{tag}-{i}",
                image_url=f"https://i.pinimg.com/originals/ab/cd/{tag}-{i}.jpg",
                source_url="https://src",
                title="",
            )
            for i in range(limit)
        ]


def _run(client: _FakeClient) -> GenerationService:
    service = GenerationService(Settings.from_env({"LLM_PROVIDER": "mock"}))
    service._pinterest = client  # noqa: SLF001
    return service


def test_only_the_photos_that_reached_a_slide_are_remembered():
    """A galeria são as alternativas. Marcar as ~30 candidatas de cada geração
    esgotaria a memória em duas rodadas e ela não serviria para nada."""
    client = _FakeClient()
    outcome = _run(client).run(
        raw_text=RAW, theme="rotina matinal", style="list", slides_count=3
    )

    memoria = load_recent()
    nos_slides = {
        str(slide.get("image_id"))
        for slide in outcome.project.carousel["slides"]
        if slide.get("image_id")
    }
    buscadas = {img["image_id"] for img in outcome.project.images}

    assert len(memoria) == len(nos_slides)
    assert len(buscadas) > len(memoria)


def test_the_next_generation_asks_the_search_to_avoid_what_already_ran():
    """O elo que faltava: a memória tem que CHEGAR ao cliente de busca.

    O `avoid` só existe no cliente do Pinterest — no Instagram o dataset é pago
    por resultado e descartar foto já vista seria jogar dinheiro fora.
    """
    remember(["i.pinimg.com/ab/cd/ja-saiu"])

    service = GenerationService(
        Settings.from_env(
            {"LLM_PROVIDER": "mock", "IMAGE_PROVIDER": "pinterest_scrape"}
        )
    )

    assert service._pinterest.name == "pinterest_scrape"  # noqa: SLF001
    assert "i.pinimg.com/ab/cd/ja-saiu" in service._pinterest._avoid_media  # noqa: SLF001


def test_mock_gradients_are_never_remembered():
    """Gradiente sintético não é foto de acervo — lembrar dele só gastaria a
    memória e não impediria repetição nenhuma."""

    class _MockOnly(_FakeClient):
        def search(self, query: str, limit: int = 10) -> list[PinterestImage]:
            self.queries.append((query, limit))
            return [
                PinterestImage(
                    image_id=f"mock-{i}",
                    image_url=f"data:image/svg+xml;utf8,<svg/>{i}",
                    source_url="https://src",
                    title="",
                )
                for i in range(limit)
            ]

    _run(_MockOnly()).run(
        raw_text=RAW, theme="rotina matinal", style="list", slides_count=3
    )

    assert load_recent() == frozenset()
