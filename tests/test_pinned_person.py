"""Testes da pessoa fixada — persistência, rotas e o pool de hook por pins
relacionados.

A pessoa fixada é o pin da foto do hook guardado em disco; com o checkbox
ligado, a busca de retrato do hook vira "pins relacionados a esse pin". Nenhum
teste toca a rede nem o disco real: o caminho do JSON vai para o tmp_path e o
cliente de imagens é um fake.
"""

from __future__ import annotations

import json

import pytest

from app.adapters.pinterest_client import PinterestImage
from app.config import Settings
from app.main import create_app
from app.services import pinned_person
from app.services.casting import POOL_HOOK
from app.services.generation import GenerationService
from app.services.pinned_person import (
    clear_pinned,
    load_pinned,
    pin_url_from_image,
    save_pinned,
)
from app.services.session_store import get_store, reset_store

PIN_IMAGE = {
    "image_id": "55169164192029389",
    "image_url": "https://i.pinimg.com/originals/c3/b1/76/hash.jpg",
    "thumb_url": "https://i.pinimg.com/474x/c3/b1/76/hash.jpg",
    "source_url": "https://www.pinterest.com/pin/55169164192029389/",
    "title": "a woman holding a cup of coffee",
}


@pytest.fixture(autouse=True)
def _tmp_pin_file(tmp_path, monkeypatch):
    """O arquivo da pessoa fixada vai para o tmp_path — nunca o instance/ real."""
    monkeypatch.setattr(pinned_person, "INSTANCE_DIR", str(tmp_path))
    monkeypatch.setattr(
        pinned_person, "PINNED_PERSON_PATH", str(tmp_path / "pinned_person.json")
    )


# ---------- persistência ----------


def test_save_and_load_round_trip():
    saved = save_pinned(PIN_IMAGE)

    assert saved is not None
    loaded = load_pinned()
    assert loaded["pin_url"] == "https://www.pinterest.com/pin/55169164192029389/"
    assert loaded["title"] == PIN_IMAGE["title"]
    assert loaded["thumb_url"] == PIN_IMAGE["thumb_url"]


def test_clear_forgets_the_person():
    save_pinned(PIN_IMAGE)

    clear_pinned()

    assert load_pinned() is None


def test_clear_without_a_pinned_person_is_a_no_op():
    clear_pinned()  # não pode levantar exceção

    assert load_pinned() is None


def test_nothing_pinned_loads_none():
    assert load_pinned() is None


def test_a_corrupted_file_counts_as_nobody_pinned():
    path = pinned_person.PINNED_PERSON_PATH
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("{nem json")

    assert load_pinned() is None


def test_a_photo_that_is_not_a_pin_cannot_be_pinned():
    """Unsplash, mock e goviral_assets não têm pins relacionados — fixar não
    teria como buscar mais fotos depois."""
    unsplash = dict(PIN_IMAGE, source_url="https://unsplash.com/photos/abc123")

    assert save_pinned(unsplash) is None
    assert load_pinned() is None


@pytest.mark.parametrize("source,expected", [
    (
        "https://www.pinterest.com/pin/123456/",
        "https://www.pinterest.com/pin/123456/",
    ),
    # Domínio regional e sufixos: o id numérico é o que importa.
    (
        "https://br.pinterest.com/pin/123456/sent/?invite_code=x",
        "https://www.pinterest.com/pin/123456/",
    ),
    ("https://unsplash.com/photos/abc", ""),
    ("/goviral-assets/print.png", ""),
    ("", ""),
])
def test_pin_url_is_canonical(source, expected):
    assert pin_url_from_image({"source_url": source}) == expected


# ---------- rotas ----------


@pytest.fixture
def app():
    reset_store()
    settings = Settings.from_env({
        "FLASK_ENV": "testing",
        "SECRET_KEY": "test-secret",
        "DEBUG": "false",
        "LLM_PROVIDER": "mock",
    })
    app = create_app(settings)
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    yield app
    reset_store()


@pytest.fixture
def client(app):
    return app.test_client()


def _seed_project(images: list[dict]) -> str:
    project = get_store().create(
        briefing={"theme": "café"},
        carousel={"slides": [{"headline": "hook", "role": "hook"}]},
        images=images,
        ranking=[],
        style="sticker",
        slides_count=1,
        raw_text="texto",
    )
    return project.project_id


def test_pin_person_saves_the_hook_pin(client):
    project_id = _seed_project([dict(PIN_IMAGE)])

    response = client.post("/pin-person", json={
        "project_id": project_id,
        "image_id": PIN_IMAGE["image_id"],
    })

    assert response.status_code == 200
    assert response.get_json()["pinned"] is True
    assert load_pinned()["pin_url"] == "https://www.pinterest.com/pin/55169164192029389/"


def test_pinning_a_non_pinterest_photo_explains_why(client):
    unsplash = dict(PIN_IMAGE, source_url="https://unsplash.com/photos/abc123")
    project_id = _seed_project([unsplash])

    response = client.post("/pin-person", json={
        "project_id": project_id,
        "image_id": PIN_IMAGE["image_id"],
    })

    assert response.status_code == 422
    assert "Pinterest" in response.get_json()["reason"]
    assert load_pinned() is None


def test_pinning_an_unknown_image_is_404(client):
    project_id = _seed_project([dict(PIN_IMAGE)])

    response = client.post("/pin-person", json={
        "project_id": project_id,
        "image_id": "nao-existe",
    })

    assert response.status_code == 404


def test_pinning_needs_project_and_image(client):
    assert client.post("/pin-person", json={}).status_code == 400


def test_clear_route_forgets_the_person(client):
    save_pinned(PIN_IMAGE)

    response = client.post("/pin-person/clear")

    assert response.status_code == 200
    assert load_pinned() is None


# ---------- geração: o pool de hook vem dos pins relacionados ----------


class _FakeRelatedClient:
    """Cliente com search e related — o contrato do pinterest_scrape."""

    name = "pinterest_scrape"
    last_fallback_reason = ""

    def __init__(self, related_images=None, related_error=None):
        self.queries: list[tuple[str, int]] = []
        self.related_calls: list[tuple[str, int]] = []
        self._related_images = related_images or []
        self._related_error = related_error

    def search(self, query: str, limit: int = 8) -> list[PinterestImage]:
        self.queries.append((query, limit))
        return [
            PinterestImage(
                image_id=f"q{len(self.queries)}-{i}",
                image_url=f"https://img/q{i}",
                source_url="https://www.pinterest.com/pin/1/",
                title="",
            )
            for i in range(limit)
        ]

    def related(self, pin_url: str, limit: int = 8) -> list[PinterestImage]:
        self.related_calls.append((pin_url, limit))
        if self._related_error:
            raise self._related_error
        return list(self._related_images)


def _related_batch(n=4):
    return [
        PinterestImage(
            image_id=f"rel-{i}",
            image_url=f"https://i.pinimg.com/originals/a/b/c/rel{i}.jpg",
            source_url=f"https://www.pinterest.com/pin/{9000 + i}/",
            title="a woman drinking coffee",
        )
        for i in range(n)
    ]


@pytest.fixture(autouse=True)
def _no_promo_assets(monkeypatch):
    monkeypatch.setattr("app.services.goviral_assets.list_asset_files", lambda: [])


def _run(client, **env):
    reset_store()
    service = GenerationService(Settings.from_env({"LLM_PROVIDER": "mock", **env}))
    service._pinterest = client  # noqa: SLF001
    return service.run(
        raw_text="Cinco dicas para acordar cedo com energia todos os dias.",
        theme="rotina matinal",
        style="sticker",
        slides_count=3,
        language="pt-BR",
        use_pinned_person=True,
    )


def test_the_hook_pool_comes_from_related_pins():
    save_pinned(PIN_IMAGE)
    client = _FakeRelatedClient(related_images=_related_batch())

    outcome = _run(client)

    assert client.related_calls == [
        ("https://www.pinterest.com/pin/55169164192029389/",
         GenerationService.HOOK_POOL_SIZE)
    ]
    # Só a busca de cenário rodou por query — a de retrato veio dos relacionados.
    assert len(client.queries) == 1
    hook_pool = [img for img in outcome.project.images if img["pool"] == POOL_HOOK]
    assert {img["image_id"] for img in hook_pool} == {f"rel-{i}" for i in range(4)}
    assert any("pessoa fixada" in w for w in outcome.warnings)


def test_the_hook_slide_gets_a_related_photo():
    save_pinned(PIN_IMAGE)
    client = _FakeRelatedClient(related_images=_related_batch())

    outcome = _run(client)

    hook_slide = outcome.project.carousel["slides"][0]
    assert hook_slide["image_id"].startswith("rel-")


def test_nobody_pinned_falls_back_to_the_usual_search():
    client = _FakeRelatedClient(related_images=_related_batch())

    outcome = _run(client)

    assert client.related_calls == []
    assert len(client.queries) == 2  # retrato + cenário, como sempre
    assert any("Nenhuma pessoa fixada" in w for w in outcome.warnings)


def test_a_client_without_related_falls_back_with_a_reason():
    """Unsplash e a API oficial não têm pins relacionados — a opção explica em
    vez de sumir com o hook."""
    save_pinned(PIN_IMAGE)

    class _NoRelated:
        name = "unsplash"
        last_fallback_reason = ""

        def __init__(self):
            self.queries = []

        def search(self, query, limit=8):
            self.queries.append((query, limit))
            return [
                PinterestImage(
                    image_id=f"u-{len(self.queries)}-{i}",
                    image_url="https://img/u",
                    source_url="https://unsplash.com/photos/x",
                    title="",
                )
                for i in range(limit)
            ]

    client = _NoRelated()
    outcome = _run(client)

    assert len(client.queries) == 2
    assert any("pinterest_scrape" in w for w in outcome.warnings)


def test_empty_related_results_fall_back_to_the_usual_search():
    save_pinned(PIN_IMAGE)
    client = _FakeRelatedClient(related_images=[])

    outcome = _run(client)

    assert len(client.related_calls) == 1
    assert len(client.queries) == 2
    assert any("não retornaram fotos" in w for w in outcome.warnings)


def test_related_errors_fall_back_to_the_usual_search():
    save_pinned(PIN_IMAGE)
    client = _FakeRelatedClient(related_error=RuntimeError("payload mudou"))

    outcome = _run(client)

    assert len(client.queries) == 2
    assert any("não retornaram fotos" in w for w in outcome.warnings)


def test_casting_off_ignores_the_option_with_a_warning():
    save_pinned(PIN_IMAGE)
    client = _FakeRelatedClient(related_images=_related_batch())

    outcome = _run(client, HOOK_SUBJECT="off")

    assert client.related_calls == []
    assert any("casting" in w for w in outcome.warnings)


def test_the_option_off_keeps_everything_as_before():
    save_pinned(PIN_IMAGE)
    client = _FakeRelatedClient(related_images=_related_batch())
    reset_store()
    service = GenerationService(Settings.from_env({"LLM_PROVIDER": "mock"}))
    service._pinterest = client  # noqa: SLF001

    service.run(
        raw_text="Cinco dicas para acordar cedo com energia todos os dias.",
        theme="rotina matinal",
        style="sticker",
        slides_count=3,
        language="pt-BR",
    )

    assert client.related_calls == []
    assert len(client.queries) == 2


# ---------- formulários levam o checkbox até o serviço ----------


def test_briefing_form_carries_the_checkbox(app):
    data = {
        "raw_text": "Texto colado com mais de vinte caracteres para validar.",
        "theme": "café",
        "language": "pt-BR",
        "style": "quote",
        "slides_count": "3",
        "script_mode": "auto",
        "use_pinned_person": "y",
    }
    with app.test_request_context("/", method="POST", data=data):
        from app.forms import BriefingForm

        form = BriefingForm()
        assert form.validate_on_submit(), form.errors
        assert form.to_briefing()["use_pinned_person"] is True

    del data["use_pinned_person"]
    with app.test_request_context("/", method="POST", data=data):
        from app.forms import BriefingForm

        form = BriefingForm()
        assert form.validate_on_submit(), form.errors
        assert form.to_briefing()["use_pinned_person"] is False
