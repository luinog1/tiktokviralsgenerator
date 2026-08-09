"""Testes do GenerationService — busca em dois pools e integração do casting."""

from __future__ import annotations

import pytest

from app.adapters.pinterest_client import PinterestImage
from app.config import Settings
from app.services.casting import POOL_HOOK, POOL_SCENE
from app.services.generation import GenerationService
from app.services.session_store import reset_store

RAW = (
    "5 dicas matinais para acordar com energia. Beba água, alongue, "
    "escreva as prioridades do dia, evite o celular, tome café."
)


@pytest.fixture(autouse=True)
def _clean_store():
    reset_store()
    yield
    reset_store()


class _FakeClient:
    """Registra as queries e devolve fotos distintas por busca."""

    name = "fake"
    last_fallback_reason = ""

    def __init__(self, overlap: bool = False):
        self.queries: list[tuple[str, int]] = []
        self._overlap = overlap

    def search(self, query: str, limit: int = 10) -> list[PinterestImage]:
        self.queries.append((query, limit))
        tag = "dup" if self._overlap else f"q{len(self.queries)}"
        return [
            PinterestImage(
                image_id=f"{tag}-{i}",
                image_url=f"https://img/{tag}-{i}",
                source_url="https://src",
                title="",
            )
            for i in range(limit)
        ]


def _service(client: _FakeClient, **env) -> GenerationService:
    service = GenerationService(Settings.from_env({"LLM_PROVIDER": "mock", **env}))
    # O serviço monta os adapters a partir das settings; trocar o cliente aqui
    # é o que mantém o teste offline sem mexer na fábrica.
    service._pinterest = client  # noqa: SLF001
    return service


def _run(client: _FakeClient, service: GenerationService, **over):
    kwargs = {
        "raw_text": RAW,
        "theme": "rotina matinal",
        "style": "list",
        "slides_count": 3,
        "language": "pt-BR",
    }
    kwargs.update(over)
    return service.run(**kwargs)


# ------------------------------------------------------ busca em dois pools
def test_searches_twice_one_query_per_role():
    client = _FakeClient()
    _run(client, _service(client))

    assert len(client.queries) == 2
    hook_query, scene_query = client.queries[0][0], client.queries[1][0]
    assert hook_query != scene_query
    assert "rotina matinal" in hook_query and "rotina matinal" in scene_query


def test_hook_query_asks_for_a_person():
    """Sem isso, "rotina matinal" na primeira página do Unsplash é xícara e
    caderno — nunca o retrato que o hook precisa."""
    client = _FakeClient()
    _run(client, _service(client))

    assert "woman" in client.queries[0][0].lower()


def test_each_photo_remembers_which_pool_it_came_from():
    client = _FakeClient()
    outcome = _run(client, _service(client))

    pools = {img["pool"] for img in outcome.project.images}
    assert pools == {POOL_HOOK, POOL_SCENE}


def test_query_hints_are_configurable():
    client = _FakeClient()
    _run(client, _service(
        client, HOOK_QUERY_HINTS="femme portrait", SCENE_QUERY_HINTS="voyage"
    ))

    assert "femme portrait" in client.queries[0][0]
    assert "voyage" in client.queries[1][0]


def test_casting_off_falls_back_to_a_single_search():
    client = _FakeClient()
    outcome = _run(client, _service(client, HOOK_SUBJECT="off"))

    assert len(client.queries) == 1
    assert all(img["pool"] == "" for img in outcome.project.images)


def test_overlapping_pools_are_deduped():
    """A mesma foto nos dois pools duplicaria a galeria e tornaria o mapa por
    image_id ambíguo."""
    client = _FakeClient(overlap=True)
    outcome = _run(client, _service(client))

    ids = [img["image_id"] for img in outcome.project.images]
    assert len(ids) == len(set(ids))


def test_a_failing_pool_does_not_sink_the_generation():
    class _Broken(_FakeClient):
        def search(self, query, limit=10):
            raise RuntimeError("502")

    client = _Broken()
    outcome = _run(client, _service(client))

    assert outcome.project.carousel["slides"]
    assert any("busca de imagens falhou" in w.lower() for w in outcome.warnings)


# --------------------------------------------------- casting nos slides salvos
def test_every_slide_gets_an_explicit_image_id():
    """A prévia e o export leem slide["image_id"] — deixá-lo vazio devolveria a
    rotação antiga e o hook perderia a foto de pessoa."""
    client = _FakeClient()
    outcome = _run(client, _service(client))

    slides = outcome.project.carousel["slides"]
    assert all(s["image_id"] for s in slides)


def test_hook_slide_takes_a_photo_from_the_hook_pool():
    client = _FakeClient()
    outcome = _run(client, _service(client))

    slides = outcome.project.carousel["slides"]
    pool_by_id = {img["image_id"]: img["pool"] for img in outcome.project.images}
    assert pool_by_id[slides[0]["image_id"]] == POOL_HOOK
    assert slides[0]["role"] == "hook"


def test_secondary_slides_take_scene_photos():
    client = _FakeClient()
    outcome = _run(client, _service(client), slides_count=6)

    slides = outcome.project.carousel["slides"]
    pool_by_id = {img["image_id"]: img["pool"] for img in outcome.project.images}
    assert all(pool_by_id[s["image_id"]] == POOL_SCENE for s in slides[1:])


# ------------------------------------------- modo roteiro dentro do serviço
def test_script_blocks_skip_the_composer_entirely():
    client = _FakeClient()
    outcome = _run(
        client,
        _service(client),
        script_blocks=["ninguém acorda às 5h", "dormiu às 21h", "salva esse post"],
    )

    slides = outcome.project.carousel["slides"]
    assert [s["headline"] for s in slides] == [
        "ninguém acorda às 5h",
        "dormiu às 21h",
        "salva esse post",
    ]
    assert outcome.project.carousel["provider"] == "manual"


def test_script_blocks_still_get_casting_and_images():
    client = _FakeClient()
    outcome = _run(client, _service(client), script_blocks=["o hook", "o meio", "o fim"])

    slides = outcome.project.carousel["slides"]
    pool_by_id = {img["image_id"]: img["pool"] for img in outcome.project.images}
    assert pool_by_id[slides[0]["image_id"]] == POOL_HOOK


def test_blank_blocks_shrink_the_carousel_not_the_search():
    client = _FakeClient()
    outcome = _run(
        client, _service(client), slides_count=6, script_blocks=["um", "", "  ", "dois"]
    )

    assert len(outcome.project.carousel["slides"]) == 2
    assert outcome.project.slides_count == 2


def test_no_mock_llm_warning_in_script_mode():
    """O aviso de mock existe para dizer "o texto não veio de um LLM real".
    No modo roteiro isso é o esperado, não uma degradação."""
    client = _FakeClient()
    outcome = _run(client, _service(client), script_blocks=["um", "dois"])

    assert not any("mock" in w.lower() and "LLM" in w for w in outcome.warnings)
