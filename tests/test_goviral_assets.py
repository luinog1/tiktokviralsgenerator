"""Testes do slide de fecho com o GoViral app (goviral_assets/)."""

from __future__ import annotations

import pytest

from app.adapters.pinterest_client import PinterestImage
from app.config import Settings
from app.services import goviral_assets
from app.services.goviral_assets import (
    GALLERY_SIZE,
    GOVIRAL_IMAGE_ID_PREFIX,
    GOVIRAL_URL_PREFIX,
    assign_promo_slide,
    pick_gallery,
    resolve_asset,
)
from app.services.generation import GenerationService
from app.services.session_store import reset_store

_FAKE_FILES = [f"print-{i}.webp" for i in range(8)]


@pytest.fixture
def fake_assets(monkeypatch):
    monkeypatch.setattr(goviral_assets, "list_asset_files", lambda: list(_FAKE_FILES))


def _slides(n: int) -> list[dict]:
    roles = ["hook"] + ["value"] * max(0, n - 2) + (["cta"] if n > 1 else [])
    return [
        {"headline": f"s{i}", "role": roles[i], "image_id": f"foto-{i}"}
        for i in range(n)
    ]


# ------------------------------------------------------------- pick_gallery
def test_gallery_has_five_alternatives_in_app_image_format(fake_assets):
    gallery = pick_gallery()
    assert len(gallery) == GALLERY_SIZE
    for img in gallery:
        assert isinstance(img, PinterestImage)
        assert img.image_id.startswith(GOVIRAL_IMAGE_ID_PREFIX)
        assert img.image_url.startswith(GOVIRAL_URL_PREFIX)
        assert img.pool == "goviral"
    # Sem repetição: cada alternativa da galeria é um print diferente.
    assert len({img.image_id for img in gallery}) == GALLERY_SIZE


def test_gallery_with_few_files_returns_what_exists(monkeypatch):
    monkeypatch.setattr(goviral_assets, "list_asset_files", lambda: ["a.webp", "b.webp"])
    assert len(pick_gallery()) == 2


def test_gallery_without_folder_is_empty(monkeypatch):
    monkeypatch.setattr(goviral_assets, "list_asset_files", lambda: [])
    assert pick_gallery() == []


# ------------------------------------------------------- assign_promo_slide
def test_last_slide_gets_the_app_print_and_gallery_grows(fake_assets):
    slides = _slides(3)
    images: list[PinterestImage] = []
    warnings: list[str] = []

    assign_promo_slide(slides, images, warnings)

    assert slides[-1]["image_id"].startswith(GOVIRAL_IMAGE_ID_PREFIX)
    # O print escolhido está na galeria, junto com as alternativas.
    assert len(images) == GALLERY_SIZE
    assert slides[-1]["image_id"] in {img.image_id for img in images}
    assert warnings and "GoViral" in warnings[0]


def test_hook_and_middle_slides_keep_their_photos(fake_assets):
    slides = _slides(3)
    assign_promo_slide(slides, [], [])
    assert slides[0]["image_id"] == "foto-0"
    assert slides[1]["image_id"] == "foto-1"


def test_single_slide_carousel_is_untouched(fake_assets):
    """Com um slide só, o "último" seria o hook — e o hook é da foto com
    pessoa, não do print do app."""
    slides = _slides(1)
    images: list[PinterestImage] = []
    assign_promo_slide(slides, images, [])
    assert slides[0]["image_id"] == "foto-0"
    assert images == []


def test_empty_folder_is_a_no_op(monkeypatch):
    monkeypatch.setattr(goviral_assets, "list_asset_files", lambda: [])
    slides = _slides(3)
    warnings: list[str] = []
    assign_promo_slide(slides, [], warnings)
    assert slides[-1]["image_id"] == "foto-2"
    assert warnings == []


# ----------------------------------------------------------- resolve_asset
def test_resolve_asset_blocks_path_traversal(tmp_path, monkeypatch):
    monkeypatch.setattr(goviral_assets, "GOVIRAL_ASSETS_DIR", str(tmp_path))
    (tmp_path / "ok.webp").write_bytes(b"x")
    assert resolve_asset("ok.webp") == str(tmp_path / "ok.webp")
    assert resolve_asset("../conftest.py") is None
    assert resolve_asset("") is None


# ------------------------------------------- a rota que serve os prints
def test_asset_route_serves_a_real_print():
    """A galeria da prévia carrega os prints por /goviral-assets/<nome>."""
    from app.main import create_app

    files = goviral_assets.list_asset_files()
    if not files:  # pragma: no cover - repo sem a pasta
        pytest.skip("goviral_assets/ vazia")
    app = create_app(Settings.from_env({"SECRET_KEY": "t", "DEBUG": "false"}))
    app.config["TESTING"] = True
    with app.test_client() as client:
        assert client.get(f"/goviral-assets/{files[0]}").status_code == 200
        assert client.get("/goviral-assets/nao-existe.webp").status_code == 404


def test_renderer_opens_the_print_from_disk():
    """A image_url do print é relativa — o renderer abre do disco, não por HTTP."""
    from app.services.slide_renderer import SlideRenderer

    files = goviral_assets.list_asset_files()
    if not files:  # pragma: no cover - repo sem a pasta
        pytest.skip("goviral_assets/ vazia")
    renderer = SlideRenderer(Settings.from_env({}))
    image = renderer._fetch_image(f"/goviral-assets/{files[0]}")  # noqa: SLF001
    assert image is not None
    assert renderer._fetch_image("/goviral-assets/nao-existe.webp") is None  # noqa: SLF001


# ------------------------------------------------- integração com a geração
class _FakeClient:
    name = "fake"
    last_fallback_reason = ""

    def search(self, query: str, limit: int = 10) -> list[PinterestImage]:
        return [
            PinterestImage(
                image_id=f"q-{i}",
                image_url=f"https://img/{i}",
                source_url="https://src",
                title="",
            )
            for i in range(limit)
        ]


def test_generation_puts_the_app_print_on_the_last_slide(fake_assets):
    reset_store()
    service = GenerationService(Settings.from_env({"LLM_PROVIDER": "mock"}))
    service._pinterest = _FakeClient()  # noqa: SLF001

    outcome = service.run(
        raw_text="dica um.\n\ndica dois.\n\ndica três.",
        theme="rotina",
        style="sticker",
        slides_count=3,
    )

    slides = outcome.project.carousel["slides"]
    assert slides[-1]["image_id"].startswith(GOVIRAL_IMAGE_ID_PREFIX)
    # O hook não vira print do app — continua com a foto do casting.
    assert not slides[0]["image_id"].startswith(GOVIRAL_IMAGE_ID_PREFIX)
    # As alternativas estão na galeria persistida, prontas para a prévia.
    promo = [
        img for img in outcome.project.images
        if str(img["image_id"]).startswith(GOVIRAL_IMAGE_ID_PREFIX)
    ]
    assert len(promo) == GALLERY_SIZE
    assert any("GoViral" in w for w in outcome.warnings)
    reset_store()
