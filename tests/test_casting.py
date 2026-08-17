"""Testes do casting — qual foto entra em qual slide, pelo papel do slide.

A regra do formato: a imagem 1 (hook) traz uma pessoa, porque é o rosto que
para o scroll; as demais trazem cenário (estética, viagem, comida).
"""

from __future__ import annotations

from app.adapters.pinterest_client import PinterestImage
from app.adapters.vision_provider import VisionVerdict
from app.services.casting import (
    POOL_FOOD,
    POOL_HOOK,
    POOL_SCENE,
    apply_casting,
    cast_carousel,
)


def _slides(*roles: str) -> list[dict]:
    return [{"headline": f"s{i}", "role": role} for i, role in enumerate(roles)]


def _image(image_id: str, pool: str = "", title: str = "", description: str = "") -> PinterestImage:
    return PinterestImage(
        image_id=image_id,
        image_url=f"https://img/{image_id}",
        source_url="https://src",
        title=title,
        description=description,
        pool=pool,
    )


def _verdict(image_id: str, subject: str, score: float = 0.5) -> VisionVerdict:
    return VisionVerdict(image_id=image_id, score=score, subject=subject)


# ------------------------------------------------------- sinal da visão (VLM)
def test_hook_gets_the_photo_with_a_woman_even_if_it_ranked_last():
    """O ranking ordena por relevância, não por assunto — sem casting, a foto
    de comida melhor ranqueada abriria o carrossel."""
    images = [_image("comida"), _image("praia"), _image("retrato")]
    verdicts = [
        _verdict("comida", "scene", 0.95),
        _verdict("praia", "scene", 0.9),
        _verdict("retrato", "woman", 0.4),
    ]

    casting = cast_carousel(_slides("hook", "value", "cta"), images, verdicts)

    assert casting.hook_image_id == "retrato"
    assert casting.hook_source == "vision"


def test_scene_photos_fill_the_rest_and_the_person_is_not_reused():
    images = [_image("retrato"), _image("praia"), _image("cafe")]
    verdicts = [
        _verdict("retrato", "woman"),
        _verdict("praia", "scene"),
        _verdict("cafe", "scene"),
    ]

    casting = cast_carousel(_slides("hook", "value", "cta"), images, verdicts)

    assert casting.image_ids[0] == "retrato"
    assert set(casting.image_ids[1:]) == {"praia", "cafe"}


def test_requested_people_food_and_scene_quotas_are_applied():
    images = [
        _image("pessoa-1", POOL_HOOK),
        _image("pessoa-2", POOL_HOOK),
        _image("comida-1", POOL_FOOD),
        _image("comida-2", POOL_FOOD),
        _image("cena-1", POOL_SCENE),
        _image("cena-2", POOL_SCENE),
    ]

    casting = cast_carousel(
        _slides("hook", *["value"] * 4, "cta"),
        images,
        person_images_count=2,
        food_images_count=2,
    )

    pool_by_id = {image.image_id: image.pool for image in images}
    chosen_pools = [pool_by_id[image_id] for image_id in casting.image_ids]
    assert chosen_pools.count(POOL_HOOK) == 2
    assert chosen_pools.count(POOL_FOOD) == 2
    assert chosen_pools.count(POOL_SCENE) == 2
    assert len(casting.image_ids) == len(set(casting.image_ids))


def test_food_quota_stays_before_the_scene_reserved_for_the_promo():
    images = [
        _image("pessoa", POOL_HOOK),
        _image("comida-1", POOL_FOOD),
        _image("comida-2", POOL_FOOD),
        _image("cena", POOL_SCENE),
    ]

    casting = cast_carousel(
        _slides("hook", "value", "value", "cta"),
        images,
        person_images_count=1,
        food_images_count=2,
    )

    assert casting.categories == ["person", "food", "food", "scene"]
    assert casting.image_ids[-1] == "cena"


def test_scene_options_never_offer_known_people_or_food():
    images = [
        _image("pessoa", POOL_HOOK),
        _image("outra-pessoa", POOL_SCENE),
        _image("comida", POOL_SCENE),
        _image("cena", POOL_SCENE),
    ]
    verdicts = [
        _verdict("pessoa", "woman"),
        _verdict("outra-pessoa", "person"),
        _verdict("comida", "food"),
        _verdict("cena", "scene"),
    ]

    casting = cast_carousel(_slides("hook", "value"), images, verdicts)

    assert casting.categories == ["person", "scene"]
    assert casting.image_options[1] == ["cena"]


def test_unjudged_pool_results_do_not_bypass_a_partial_vision_response():
    images = [
        _image("hook-rejeitado", POOL_HOOK),
        _image("food-nao-visto", POOL_FOOD),
        _image("scene-confirmada", POOL_SCENE),
    ]
    verdicts = [
        _verdict("hook-rejeitado", "scene"),
        _verdict("scene-confirmada", "scene"),
    ]

    casting = cast_carousel(
        _slides("hook", "value", "cta"),
        images,
        verdicts,
        food_images_count=1,
    )

    assert "food-nao-visto" not in casting.image_options[1]
    assert casting.image_ids[1] in {"hook-rejeitado", "scene-confirmada"}
    assert any("0 de 1" in warning for warning in casting.warnings)


def test_strict_vision_uses_a_neutral_background_when_no_safe_scene_exists():
    images = [
        _image("pessoa", POOL_HOOK),
        _image("comida", POOL_FOOD),
    ]
    verdicts = [
        _verdict("pessoa", "woman"),
        _verdict("comida", "food"),
    ]

    casting = cast_carousel(_slides("hook", "value"), images, verdicts)

    assert casting.image_ids == ["pessoa", ""]
    assert casting.categories == ["person", "scene"]
    assert any("fundo neutro" in warning for warning in casting.warnings)


def test_smoothie_and_fruit_metadata_count_as_food():
    images = [
        _image("pessoa", POOL_HOOK),
        _image("smoothie", POOL_SCENE, title="fresh berry smoothie bowl with fruit"),
        _image("cena", POOL_SCENE, title="bright kitchen interior"),
    ]

    casting = cast_carousel(
        _slides("hook", "value", "cta"),
        images,
        food_images_count=1,
    )

    assert casting.image_ids[1] == "smoothie"
    assert not casting.warnings


def test_photo_described_as_a_person_does_not_enter_the_food_quota():
    images = [
        _image("hook", POOL_HOOK, title="a woman smiling"),
        _image("pessoa-com-bebida", POOL_FOOD, title="woman drinking smoothie"),
        _image("comida", POOL_FOOD, title="fresh berry smoothie bowl"),
        _image("cena", POOL_SCENE, title="bright kitchen interior"),
    ]

    casting = cast_carousel(
        _slides("hook", "value", "cta"), images, food_images_count=1
    )

    assert casting.image_ids[1] == "comida"
    assert "pessoa-com-bebida" not in casting.image_options[1]


def test_vision_can_reject_a_false_food_pool_result():
    images = [
        _image("pessoa", POOL_HOOK),
        _image("pool-errou", POOL_FOOD),
        _image("cena", POOL_SCENE),
    ]
    verdicts = [
        _verdict("pessoa", "woman"),
        _verdict("pool-errou", "scene"),
        _verdict("cena", "scene"),
    ]

    casting = cast_carousel(
        _slides("hook", "value", "cta"),
        images,
        verdicts,
        food_images_count=1,
    )

    assert any("0 de 1" in warning for warning in casting.warnings)


def test_a_man_serves_as_hook_when_no_woman_was_found():
    """"pessoa" é o requisito do formato; o recorte preferido é só preferência."""
    images = [_image("praia"), _image("homem")]
    verdicts = [_verdict("praia", "scene", 0.9), _verdict("homem", "man", 0.2)]

    casting = cast_carousel(_slides("hook", "cta"), images, verdicts)

    assert casting.hook_image_id == "homem"
    assert casting.hook_source == "vision"


def test_hook_subject_setting_picks_between_two_people():
    images = [_image("mulher"), _image("homem")]
    verdicts = [_verdict("mulher", "woman", 0.1), _verdict("homem", "man", 0.99)]

    casting = cast_carousel(
        _slides("hook", "cta"), images, verdicts, hook_subject="woman"
    )

    assert casting.hook_image_id == "mulher"


# ------------------------------------------------ sinal do pool (sem visão)
def test_pool_decides_the_hook_when_vision_is_off():
    """A visão é opcional e vem desligada por padrão — o casting não pode
    depender dela para funcionar."""
    images = [_image("cenario", POOL_SCENE), _image("retrato", POOL_HOOK)]

    casting = cast_carousel(_slides("hook", "cta"), images, verdicts=None)

    assert casting.hook_image_id == "retrato"
    assert casting.hook_source == "pool"


def test_preferred_instagram_hook_wins_a_same_quality_tie():
    images = [
        _image("ig-profile", POOL_HOOK, title="a woman smiling"),
        _image("pinterest", POOL_HOOK, title="a woman smiling"),
    ]
    verdicts = [
        _verdict("ig-profile", "woman", 0.2),
        _verdict("pinterest", "woman", 0.95),
    ]

    casting = cast_carousel(
        _slides("hook", "cta"),
        images,
        verdicts,
        preferred_hook_ids={"ig-profile"},
    )

    assert casting.hook_image_id == "ig-profile"


def test_vision_beats_the_pool_when_the_two_disagree():
    """A busca de retrato devolve paisagem às vezes; quem olhou a foto ganha."""
    images = [_image("veio-do-pool-hook", POOL_HOOK), _image("cenario", POOL_SCENE)]
    verdicts = [
        _verdict("veio-do-pool-hook", "scene", 0.9),
        _verdict("cenario", "woman", 0.1),
    ]

    casting = cast_carousel(_slides("hook", "cta"), images, verdicts)

    assert casting.hook_image_id == "cenario"
    assert casting.hook_source == "vision"


# ------------------------------------------------------------- degradações
def test_warns_when_no_photo_with_a_person_was_found():
    """Silenciar isso deixaria o usuário achando que o hook tem pessoa."""
    images = [_image("praia", POOL_SCENE), _image("cafe", POOL_SCENE)]
    verdicts = [_verdict("praia", "scene"), _verdict("cafe", "scene")]

    casting = cast_carousel(_slides("hook", "cta"), images, verdicts)

    assert casting.hook_source == "fallback"
    assert casting.warnings
    assert "pessoa" in casting.warnings[0].lower()


def test_single_image_still_fills_every_slide():
    images = [_image("unica")]

    casting = cast_carousel(_slides("hook", "value", "cta"), images, verdicts=None)

    assert casting.image_ids == ["unica", "unica", "unica"]


def test_no_images_produces_no_casting():
    casting = cast_carousel(_slides("hook", "cta"), [], verdicts=None)

    assert casting.image_ids == []


def test_hook_is_found_wherever_the_role_is():
    """O papel manda, não o índice — se o hook não for o slide 0, a foto de
    pessoa vai junto com ele."""
    images = [_image("retrato", POOL_HOOK), _image("cenario", POOL_SCENE)]
    slides = [{"headline": "a", "role": "value"}, {"headline": "b", "role": "hook"}]

    casting = cast_carousel(slides, images, verdicts=None)

    assert casting.image_ids[1] == "retrato"


def test_scene_pool_rotates_across_many_slides():
    images = [_image("retrato", POOL_HOOK)] + [
        _image(f"cena{i}", POOL_SCENE) for i in range(3)
    ]

    casting = cast_carousel(_slides("hook", *["value"] * 6, "cta"), images, None)

    assert casting.image_ids[0] == "retrato"
    # As fotos de cenário circulam sem repetir em sequência
    assert casting.image_ids[1] != casting.image_ids[2]


def test_apply_casting_writes_the_image_id_on_each_slide():
    slides = _slides("hook", "value", "cta")
    images = [_image("retrato", POOL_HOOK), _image("cena", POOL_SCENE)]

    casting = cast_carousel(slides, images, verdicts=None)
    apply_casting(slides, casting)

    assert slides[0]["image_id"] == "retrato"
    assert all(s["image_id"] for s in slides)
    assert slides[0]["image_category"] == "person"
    assert slides[1]["image_category"] == "scene"
    assert slides[1]["image_options"] == ["cena"]


# ------------------------------------------- sinal do metadado (sem visão)
def test_description_of_a_person_beats_the_pool():
    """O alt_description do Unsplash descreve *aquela* foto; o pool descreve só
    a busca que a trouxe."""
    images = [
        _image("veio-do-pool", POOL_HOOK, title="morning coffee on a table"),
        _image("descrita", POOL_SCENE, title="a woman sitting on a bed"),
    ]

    casting = cast_carousel(_slides("hook", "cta"), images, verdicts=None)

    assert casting.hook_image_id == "descrita"
    assert casting.hook_source == "metadata"


def test_body_part_photos_do_not_count_as_a_person():
    """"woman's hands holding a cup" é foto de xícara — não serve de hook."""
    images = [
        _image("maos", POOL_SCENE, title="woman hands holding a cup"),
        _image("retrato", POOL_HOOK, title=""),
    ]

    casting = cast_carousel(_slides("hook", "cta"), images, verdicts=None)

    assert casting.hook_image_id == "retrato"


def test_vision_still_beats_the_metadata():
    images = [
        _image("descrita", POOL_SCENE, title="a woman walking"),
        _image("real", POOL_SCENE, title="empty street"),
    ]
    verdicts = [_verdict("descrita", "scene", 0.9), _verdict("real", "woman", 0.1)]

    casting = cast_carousel(_slides("hook", "cta"), images, verdicts)

    assert casting.hook_image_id == "real"
    assert casting.hook_source == "vision"


def test_metadata_keeps_person_photos_out_of_the_scene_slots():
    images = [
        _image("retrato", POOL_HOOK, title="a woman smiling"),
        _image("outra-pessoa", POOL_SCENE, title="a girl reading"),
        _image("cena", POOL_SCENE, title="sunset over the sea"),
    ]

    casting = cast_carousel(_slides("hook", "value"), images, verdicts=None)

    assert casting.image_ids[1] == "cena"


def test_portuguese_descriptions_are_understood():
    images = [
        _image("cena", POOL_SCENE, title="xícara de café na mesa"),
        _image("pessoa", POOL_SCENE, description="retrato de uma mulher na janela"),
    ]

    casting = cast_carousel(_slides("hook", "cta"), images, verdicts=None)

    assert casting.hook_image_id == "pessoa"
