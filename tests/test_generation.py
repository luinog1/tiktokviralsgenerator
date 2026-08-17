"""Testes do GenerationService — busca em dois pools e integração do casting."""

from __future__ import annotations

import pytest

from app.adapters.pinterest_client import PinterestImage
from app.config import Settings
from app.services.casting import POOL_FOOD, POOL_HOOK, POOL_SCENE
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


@pytest.fixture(autouse=True)
def _no_promo_assets(monkeypatch):
    """A pasta goviral_assets/ do repo colocaria um print do app no último
    slide de TODO teste daqui. O comportamento tem testes próprios em
    test_goviral_assets.py; nestes, a pasta se comporta como vazia."""
    monkeypatch.setattr(
        "app.services.goviral_assets.list_asset_files", lambda: []
    )


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


def test_default_scene_query_does_not_request_food():
    client = _FakeClient()
    _run(client, _service(client))

    assert "food" not in client.queries[1][0].lower().split()


def test_each_photo_remembers_which_pool_it_came_from():
    client = _FakeClient()
    outcome = _run(client, _service(client))

    pools = {img["pool"] for img in outcome.project.images}
    assert pools == {POOL_HOOK, POOL_SCENE}


def test_pool_aware_client_receives_hook_and_scene_explicitly():
    class _PoolAwareClient(_FakeClient):
        def __init__(self):
            super().__init__()
            self.pools = []

        def search_pool(self, query, limit=10, *, pool=""):
            self.pools.append(pool)
            return self.search(query, limit=limit)

    client = _PoolAwareClient()
    _run(client, _service(client))

    assert client.pools == [POOL_HOOK, POOL_SCENE]


def test_food_quota_adds_a_distinct_food_search_pool():
    class _PoolAwareClient(_FakeClient):
        def __init__(self):
            super().__init__()
            self.pools = []

        def search_pool(self, query, limit=10, *, pool=""):
            self.pools.append(pool)
            return self.search(query, limit=limit)

    client = _PoolAwareClient()
    outcome = _run(
        client,
        _service(client),
        slides_count=6,
        person_images_count=2,
        food_images_count=2,
    )

    assert client.pools == [POOL_HOOK, POOL_FOOD, POOL_SCENE]
    assert "smoothie" in client.queries[1][0].lower()
    pools = {image["pool"] for image in outcome.project.images}
    assert pools == {POOL_HOOK, POOL_FOOD, POOL_SCENE}


def test_visual_quotas_reach_the_saved_slides():
    client = _FakeClient()
    outcome = _run(
        client,
        _service(client),
        slides_count=6,
        person_images_count=2,
        food_images_count=2,
    )

    pool_by_id = {image["image_id"]: image["pool"] for image in outcome.project.images}
    chosen = [pool_by_id[slide["image_id"]] for slide in outcome.project.carousel["slides"]]
    assert chosen.count(POOL_HOOK) == 2
    assert chosen.count(POOL_FOOD) == 2
    assert chosen.count(POOL_SCENE) == 2
    assert outcome.project.briefing["slides_count"] == 6
    assert all("image_category" in slide for slide in outcome.project.carousel["slides"])
    assert all("image_options" in slide for slide in outcome.project.carousel["slides"])


def test_instagram_quota_prefers_the_profile_photo_for_the_hook():
    class _CombinedQuotaClient:
        name = "instagram_pinterest"
        last_fallback_reason = ""

        def search_pool(self, query, limit=10, *, pool=""):
            if pool == POOL_HOOK:
                return [
                    PinterestImage(
                        image_id="ig-profile",
                        image_url="https://img/ig",
                        source_url="https://instagram/profile",
                        title="a woman smiling",
                    ),
                    PinterestImage(
                        image_id="pin-person",
                        image_url="https://img/pin",
                        source_url="https://pinterest/pin",
                        title="a woman smiling",
                    ),
                ]
            return [
                PinterestImage(
                    image_id="pin-scene",
                    image_url="https://img/scene",
                    source_url="https://pinterest/scene",
                    title="morning coffee on a table",
                )
            ]

    service = GenerationService(
        Settings.from_env({"LLM_PROVIDER": "mock"}),
        instagram_images_count=1,
    )
    service._pinterest = _CombinedQuotaClient()  # noqa: SLF001

    outcome = _run(_FakeClient(), service)

    assert outcome.project.carousel["slides"][0]["image_id"] == "ig-profile"
    assert any("Instagram limitado a 1" in warning for warning in outcome.warnings)


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


def test_same_pinterest_file_with_different_pin_ids_is_deduped():
    class _SameMediaClient(_FakeClient):
        def search(self, query: str, limit: int = 10) -> list[PinterestImage]:
            self.queries.append((query, limit))
            call = len(self.queries)
            return [
                PinterestImage(
                    image_id=f"pin-{call}-{i}",
                    image_url=(
                        "https://i.pinimg.com/"
                        + ("originals" if call == 1 else "736x")
                        + f"/aa/bb/same-{i}.{'png' if call == 1 else 'jpg'}"
                    ),
                    source_url=f"https://pinterest/pin/{call}-{i}",
                    title="",
                )
                for i in range(limit)
            ]

    client = _SameMediaClient()
    outcome = _run(client, _service(client))

    assert len(outcome.project.images) == 6


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


# ------------------------------- rótulos no texto colado valem como roteiro
LABELED = (
    "Imagem 1 (hook): ninguém acorda às 5h por disciplina\n"
    "\n"
    "Imagem 2: acorda porque dormiu às 21h\n"
    "\n"
    "ninguém fala essa parte\n"
    "\n"
    "Imagem 3: salva pra começar amanhã"
)


def test_labels_in_the_pasted_text_skip_the_composer():
    """Escrever "Imagem N:" é decidir a distribuição — não há o que um LLM
    redistribua ali sem criar a chance de redistribuir diferente."""
    client = _FakeClient()
    outcome = _run(client, _service(client), raw_text=LABELED)

    slides = outcome.project.carousel["slides"]
    assert outcome.project.carousel["provider"] == "manual"
    assert [s["headline"] for s in slides] == [
        "ninguém acorda às 5h por disciplina",
        "acorda porque dormiu às 21h",
        "salva pra começar amanhã",
    ]
    # A linha em branco dentro do bloco é a segunda caixa daquela imagem.
    assert slides[1]["body"] == "ninguém fala essa parte"
    # E a imagem 1 continua sendo uma caixa só.
    assert slides[0]["body"] == ""


def test_the_label_is_orientation_and_never_becomes_text():
    client = _FakeClient()
    outcome = _run(client, _service(client), raw_text=LABELED)

    todo_o_texto = " ".join(
        f"{s['headline']} {s['body']}" for s in outcome.project.carousel["slides"]
    ).lower()
    assert "imagem 1" not in todo_o_texto
    assert "hook)" not in todo_o_texto


def test_the_warning_says_the_labels_were_obeyed():
    """Pular o composer é uma decisão visível: sem o aviso, o usuário não tem
    como saber por que o texto saiu exatamente como ele escreveu."""
    client = _FakeClient()
    outcome = _run(client, _service(client), raw_text=LABELED)

    assert any("rótulos" in w for w in outcome.warnings)


def test_text_without_labels_still_goes_through_the_composer():
    """O modo texto corrido continua existindo — o rótulo é que é o sinal."""
    client = _FakeClient()
    outcome = _run(client, _service(client), raw_text=RAW)

    assert outcome.project.carousel["provider"] == "mock"
