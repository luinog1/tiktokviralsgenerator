"""Testes do casting — qual foto entra em qual slide, pelo papel do slide.

A regra do formato: a imagem 1 (hook) traz uma pessoa, porque é o rosto que
para o scroll; as demais trazem cenário (estética, viagem, comida).
"""

from __future__ import annotations

from app.adapters.pinterest_client import PinterestImage
from app.adapters.vision_provider import VisionVerdict
from app.services.casting import (
    MIN_IMAGE_ALTERNATIVES,
    MIN_IMAGE_OPTIONS,
    POOL_FOOD,
    POOL_HOOK,
    POOL_SCENE,
    apply_casting,
    cast_carousel,
)


def _slides(*roles: str) -> list[dict]:
    return [{"headline": f"s{i}", "role": role} for i, role in enumerate(roles)]


def _image(image_id: str, pool: str = "", alt: str = "", description: str = "") -> PinterestImage:
    # O `title` acompanha o `alt` como nos adapters (`title = alt or query`).
    # O casting só pode ler o `alt`; quem garante isso é
    # `test_the_search_query_in_the_title_is_not_read_as_the_photo_caption`.
    return PinterestImage(
        image_id=image_id,
        image_url=f"https://img/{image_id}",
        source_url="https://src",
        title=alt,
        alt=alt,
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


def test_scene_options_lead_with_scene_photos_then_top_up():
    """A galeria abre pela categoria do slide e só depois completa com o resto.

    Pessoa e comida confirmadas pelo VLM não podem ser *escolhidas* para um
    slide de cenário — mas podem ser oferecidas, porque a troca é um clique do
    usuário e uma galeria de uma foto só não é uma troca.
    """
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
    assert casting.image_ids[1] == "cena"
    assert casting.image_options[1][0] == "cena"
    assert set(casting.image_options[1]) == {i.image_id for i in images}


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

    assert casting.image_ids[1] != "food-nao-visto"
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
        _image("smoothie", POOL_SCENE, alt="fresh berry smoothie bowl with fruit"),
        _image("cena", POOL_SCENE, alt="bright kitchen interior"),
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
        _image("hook", POOL_HOOK, alt="a woman smiling"),
        _image("pessoa-com-bebida", POOL_FOOD, alt="woman drinking smoothie"),
        _image("comida", POOL_FOOD, alt="fresh berry smoothie bowl"),
        _image("cena", POOL_SCENE, alt="bright kitchen interior"),
    ]

    casting = cast_carousel(
        _slides("hook", "value", "cta"), images, food_images_count=1
    )

    assert casting.image_ids[1] == "comida"
    assert casting.image_options[1][0] == "comida"


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
        _image("ig-profile", POOL_HOOK, alt="a woman smiling"),
        _image("pinterest", POOL_HOOK, alt="a woman smiling"),
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
    assert slides[1]["image_options"][0] == "cena"


# ------------------------------------------------ alternativas da galeria
def test_every_slide_offers_five_alternatives_beyond_the_one_it_got():
    """A cota limita o que é ESCOLHIDO, não o que pode ser escolhido.

    Antes, a galeria de um slide era o pool da categoria dele — e um pool curto
    deixava a troca sem alternativa. Ela era curta na prática justamente quando
    mais importava: com visão ligada, quem o VLM não avaliou tem afinidade 0 em
    todas as categorias e some dos três pools.

    "Cinco alternativas" é cinco **além** da foto que já está no slide: a foto
    escolhida não é uma opção de troca, então a galeria tem seis.
    """
    images = [_image(f"cena-{i}", POOL_SCENE) for i in range(8)]
    images += [_image("retrato", POOL_HOOK), _image("prato", POOL_FOOD)]

    casting = cast_carousel(
        _slides("hook", "value", "cta"), images, food_images_count=1
    )

    assert casting.categories == ["person", "food", "scene"]
    assert casting.image_ids[1] == "prato"
    for escolhida, options in zip(casting.image_ids, casting.image_options):
        assert len(set(options)) == len(options)
        alternativas = [o for o in options if o != escolhida]
        assert len(alternativas) >= MIN_IMAGE_ALTERNATIVES


def test_the_slide_own_category_still_comes_first_in_the_gallery():
    """O acréscimo é um complemento, não uma mistura: a primeira alternativa
    continua sendo do mesmo tipo da foto escolhida."""
    images = [
        _image("retrato", POOL_HOOK),
        _image("prato", POOL_FOOD),
        _image("cena", POOL_SCENE),
        _image("cena-2", POOL_SCENE),
    ]

    casting = cast_carousel(
        _slides("hook", "value", "cta"), images, food_images_count=1
    )

    assert casting.image_options[0][0] == "retrato"
    assert casting.image_options[1][0] == "prato"
    assert casting.image_options[2][0].startswith("cena")


def test_a_gallery_cannot_offer_photos_that_were_never_found():
    """`MIN_IMAGE_OPTIONS` é um alvo, não uma promessa: com três fotos no
    acervo inteiro, a galeria tem três."""
    images = [
        _image("retrato", POOL_HOOK),
        _image("cena", POOL_SCENE),
        _image("cena-2", POOL_SCENE),
    ]

    casting = cast_carousel(_slides("hook", "value"), images)

    for options in casting.image_options:
        assert len(options) == 3


# ------------------------------------------- sinal do metadado (sem visão)
def test_description_of_a_person_beats_the_pool():
    """O alt_description do Unsplash descreve *aquela* foto; o pool descreve só
    a busca que a trouxe."""
    images = [
        _image("veio-do-pool", POOL_HOOK, alt="morning coffee on a table"),
        _image("descrita", POOL_SCENE, alt="a woman sitting on a bed"),
    ]

    casting = cast_carousel(_slides("hook", "cta"), images, verdicts=None)

    assert casting.hook_image_id == "descrita"
    assert casting.hook_source == "metadata"


def test_body_part_photos_do_not_count_as_a_person():
    """"woman's hands holding a cup" é foto de xícara — não serve de hook."""
    images = [
        _image("maos", POOL_SCENE, alt="woman hands holding a cup"),
        _image("retrato", POOL_HOOK, alt=""),
    ]

    casting = cast_carousel(_slides("hook", "cta"), images, verdicts=None)

    assert casting.hook_image_id == "retrato"


def test_vision_still_beats_the_metadata():
    images = [
        _image("descrita", POOL_SCENE, alt="a woman walking"),
        _image("real", POOL_SCENE, alt="empty street"),
    ]
    verdicts = [_verdict("descrita", "scene", 0.9), _verdict("real", "woman", 0.1)]

    casting = cast_carousel(_slides("hook", "cta"), images, verdicts)

    assert casting.hook_image_id == "real"
    assert casting.hook_source == "vision"


def test_metadata_keeps_person_photos_out_of_the_scene_slots():
    images = [
        _image("retrato", POOL_HOOK, alt="a woman smiling"),
        _image("outra-pessoa", POOL_SCENE, alt="a girl reading"),
        _image("cena", POOL_SCENE, alt="sunset over the sea"),
    ]

    casting = cast_carousel(_slides("hook", "value"), images, verdicts=None)

    assert casting.image_ids[1] == "cena"


def test_portuguese_descriptions_are_understood():
    images = [
        _image("cena", POOL_SCENE, alt="xícara de café na mesa"),
        _image("pessoa", POOL_SCENE, description="retrato de uma mulher na janela"),
    ]

    casting = cast_carousel(_slides("hook", "cta"), images, verdicts=None)

    assert casting.hook_image_id == "pessoa"


# --------------------------------------- foco da legenda vs. segundo plano
def test_coffee_in_the_background_does_not_empty_the_scene_pool():
    """Num tema como "rotina matinal" há café em quase toda foto.

    Vetar qualquer menção deixava três candidatas de doze, e aí o carrossel
    repetia foto. A cota de comida existe para limitar o FOCO da imagem — uma
    xícara na mesa do fundo não faz da foto do quarto uma foto de comida.
    """
    images = [
        _image("pessoa", POOL_HOOK, alt="a woman waking up"),
        _image(
            "quarto",
            POOL_SCENE,
            alt="a bright bedroom with a cup of coffee on the nightstand",
        ),
        _image("mesa", POOL_SCENE, alt="an open notebook with a latte beside it"),
        _image("janela", POOL_SCENE, alt="morning light through a window"),
    ]

    casting = cast_carousel(_slides("hook", "value", "value", "cta"), images)

    assert casting.image_ids[0] == "pessoa"
    assert set(casting.image_ids[1:]) == {"quarto", "mesa", "janela"}
    assert not casting.warnings


def test_a_photo_that_is_about_the_coffee_still_counts_as_food():
    """O outro lado do mesmo corte: em primeiro plano, o café é comida."""
    images = [
        _image("pessoa", POOL_HOOK, alt="a woman waking up"),
        _image("cafe", POOL_SCENE, alt="a cup of coffee on a wooden table"),
        _image("quarto", POOL_SCENE, alt="a bright bedroom with a cup of coffee"),
    ]

    casting = cast_carousel(
        _slides("hook", "value", "cta"), images, food_images_count=1
    )

    assert casting.categories == ["person", "food", "scene"]
    assert casting.image_ids[1] == "cafe"
    assert casting.image_ids[2] == "quarto"


def test_a_person_holding_a_coffee_can_still_be_the_hook():
    """"A man drinking a coffee" — o exemplo da própria doc do Unsplash — é
    foto de pessoa. Vetar pela menção à bebida esvaziava o pool de retrato
    justamente no tema em que ele mais importa."""
    images = [
        _image("pessoa", POOL_SCENE, alt="a man drinking a coffee"),
        _image("mesa", POOL_HOOK, alt="an empty table"),
    ]

    casting = cast_carousel(_slides("hook", "cta"), images)

    assert casting.hook_image_id == "pessoa"
    assert casting.hook_source == "metadata"


def test_the_photo_own_caption_beats_the_pool_it_came_from():
    """A busca de retrato devolve paisagem às vezes. Se a legenda da foto diz
    que não há ninguém ali, ela serve de cenário — a mesma regra que já valia
    no sentido contrário (`test_description_of_a_person_beats_the_pool`).

    Antes, o pool de origem vetava: sem candidata de cenário, o slide 2
    repetia o retrato do slide 1.
    """
    images = [
        _image("retrato", POOL_HOOK, alt="a woman smiling"),
        _image("paisagem", POOL_HOOK, alt="sunset over the sea"),
    ]

    casting = cast_carousel(_slides("hook", "cta"), images)

    assert casting.image_ids == ["retrato", "paisagem"]


def test_the_search_query_in_the_title_is_not_read_as_the_photo_caption():
    """Sem legenda, os adapters põem a query no `title` — e a query descreve a
    busca, não a foto. Lido como metadado, o "cafe" do tema faria de comida
    toda foto sem legenda, inclusive as que vieram do pool de cenário."""
    sem_legenda = PinterestImage(
        image_id="sem-legenda",
        image_url="https://img/sem-legenda",
        source_url="https://src",
        title="cafe da manha aesthetic lifestyle travel interior workspace",
        pool=POOL_SCENE,
    )
    images = [_image("pessoa", POOL_HOOK), sem_legenda]

    casting = cast_carousel(_slides("hook", "cta"), images)

    assert casting.image_ids == ["pessoa", "sem-legenda"]
    assert casting.categories == ["person", "scene"]


# ---------- as alternativas de cada imagem são diferentes das dos outros ----------


def test_two_slides_of_the_same_category_do_not_share_a_gallery():
    """O defeito: a galeria de um slide ERA o pool inteiro da categoria dele.

    Num carrossel com quatro slides de cenário, os quatro abriam a mesma lista,
    na mesma ordem — trocar a foto do slide 3 oferecia exatamente as opções do
    slide 4. A leitura correta disso, do lado de quem gera, é que não há
    alternativa nenhuma.
    """
    images = [_image("retrato", POOL_HOOK)]
    images += [_image(f"cena-{i}", POOL_SCENE) for i in range(30)]

    casting = cast_carousel(_slides("hook", "value", "value", "value", "cta"), images)

    galerias = [set(options) for options in casting.image_options]
    for i, uma in enumerate(galerias):
        for outra in galerias[i + 1 :]:
            assert not (uma & outra), "duas galerias ofereceram a mesma foto"


def test_every_image_gets_five_alternatives_of_its_own():
    """O pedido é cinco alternativas POR IMAGEM, distintas das demais — com
    acervo suficiente, é o que tem que acontecer."""
    images = [_image("retrato", POOL_HOOK)]
    images += [_image(f"prato-{i}", POOL_FOOD) for i in range(12)]
    images += [_image(f"cena-{i}", POOL_SCENE) for i in range(30)]

    casting = cast_carousel(
        _slides("hook", "value", "value", "value", "value", "cta"),
        images,
        food_images_count=1,
    )

    todas: set[str] = set()
    for escolhida, options in zip(casting.image_ids, casting.image_options):
        alternativas = [o for o in options if o != escolhida]
        assert len(alternativas) >= MIN_IMAGE_ALTERNATIVES
        assert not (set(options) & todas), "uma foto foi oferecida em dois slides"
        todas |= set(options)


def test_a_chosen_photo_is_not_offered_as_an_alternative_elsewhere():
    """Alternativa que já está em outro slide não é troca, é duplicata.

    Vale enquanto houver material: com o acervo esgotado, a última passagem de
    `_deal_options` oferece o que houver (ver
    `test_a_short_pool_shares_instead_of_leaving_a_gallery_empty`).
    """
    images = [_image("retrato", POOL_HOOK)]
    images += [_image(f"cena-{i}", POOL_SCENE) for i in range(30)]

    casting = cast_carousel(_slides("hook", "value", "cta"), images)

    escolhidas = {image_id for image_id in casting.image_ids if image_id}
    for escolhida, options in zip(casting.image_ids, casting.image_options):
        alheias = escolhidas - {escolhida}
        assert not (set(options) & alheias)


def test_the_first_alternative_still_comes_from_the_slide_category():
    """A repartição não pode virar mistura: a primeira alternativa continua
    sendo do mesmo tipo da foto escolhida."""
    images = [_image(f"retrato-{i}", POOL_HOOK) for i in range(8)]
    images += [_image(f"prato-{i}", POOL_FOOD) for i in range(8)]
    images += [_image(f"cena-{i}", POOL_SCENE) for i in range(8)]

    casting = cast_carousel(
        _slides("hook", "value", "cta"), images, food_images_count=1
    )

    assert casting.image_options[0][1].startswith("retrato")
    assert casting.image_options[1][1].startswith("prato")
    assert casting.image_options[2][1].startswith("cena")


def test_a_short_pool_shares_instead_of_leaving_a_gallery_empty():
    """Exclusividade é o alvo, não a promessa: seis slides × seis fotos são 36
    distintas, e o acervo pode não ter tanto. Galeria vazia é pior que galeria
    compartilhada."""
    images = [_image("retrato", POOL_HOOK)]
    images += [_image(f"cena-{i}", POOL_SCENE) for i in range(3)]

    casting = cast_carousel(_slides("hook", "value", "value", "cta"), images)

    for options in casting.image_options:
        assert options, "galeria vazia"
        assert len(set(options)) == len(options), "foto repetida na mesma galeria"
