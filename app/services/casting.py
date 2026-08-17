"""Casting — decide qual foto entra em cada slide, pelo papel do slide.

Antes, o slide `i` usava a imagem `i % len(images)`: pura rotação. Num photo
post de lifestyle o slide 1 é o que para o scroll, e o que para o scroll é uma
pessoa em cena — não um prato de comida. Rotação não garante isso, porque a
ordem vinha do ranking de relevância, que não olha o assunto da foto.

Aqui o slide de `hook` recebe uma foto com pessoa e os demais obedecem às cotas
de pessoa, comida e cenário geral. Três fontes de sinal, em ordem de confiança:

1. `subject` do VLM — o modelo olhou a foto e disse o que tem nela.
2. Título/descrição da foto — o Unsplash escreve "a woman sitting on a bed".
   Descreve *aquela* foto, então vale mais que a busca que a trouxe.
3. `pool` da imagem — de qual busca ela veio (pessoa, comida ou cenário). É o
   sinal que faz o casting funcionar sem visão configurada.

Sem nenhum dos três sinais, o hook fica com a foto melhor ranqueada e o aviso
diz isso — o carrossel sai, mas o usuário sabe que precisa trocar a foto.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from app.adapters.pinterest_client import PinterestImage

logger = logging.getLogger(__name__)

# Assuntos que o VLM pode devolver. "woman"/"man" são leituras da foto de banco
# de imagens, não identificação de indivíduo — servem só para escolher o
# enquadramento do slide de hook.
PERSON_SUBJECTS = ("woman", "man", "person")
FOOD_SUBJECT = "food"
SCENE_SUBJECT = "scene"

POOL_HOOK = "hook"
POOL_FOOD = "food"
POOL_SCENE = "scene"

# Palavras que denunciam pessoa no título/descrição da foto. O Unsplash escreve
# alt_description como "a woman sitting on a bed" — quando o campo vem
# preenchido, é um sinal melhor que o pool, porque descreve *aquela* foto e não
# a busca que a trouxe. Sem acento de propósito: o texto vem normalizado.
_PERSON_WORDS = frozenset({
    "woman", "women", "girl", "lady", "female", "mulher", "menina",
    "man", "men", "boy", "guy", "male", "homem", "menino",
    "person", "people", "human", "pessoa", "portrait", "retrato",
    "model", "modelo", "selfie", "couple", "casal",
})

# Contrapeso: "woman's hands holding a cup" é foto de xícara, não de pessoa.
# Quando a descrição foca numa parte do corpo, o retrato não existe.
_PARTIAL_WORDS = frozenset({
    "hand", "hands", "mao", "maos", "feet", "foot", "pes", "leg", "legs",
    "hair", "cabelo", "eye", "eyes", "olho", "olhos", "skin", "pele",
})

_FOOD_WORDS = frozenset({
    "food", "meal", "dish", "plate", "breakfast", "lunch", "dinner",
    "snack", "dessert", "smoothie", "juice", "drink", "beverage",
    "fruit", "fruits", "berry", "berries", "banana", "orange", "apple",
    "coffee", "latte", "salad", "bowl", "recipe", "comida", "refeicao",
    "refeição", "prato", "cafe", "café", "almoco", "almoço", "jantar",
    "lanche", "sobremesa", "suco",
    "bebida", "fruta", "frutas", "receita",
})

_WORD_RE = re.compile(r"[a-zà-ÿ]+")


def _describes_person(image: PinterestImage) -> bool:
    """A descrição da foto fala de gente (e não de um pedaço de gente)?"""
    text = f"{image.title} {image.description}".lower()
    words = set(_WORD_RE.findall(text))
    if not words & _PERSON_WORDS:
        return False
    return not (words & _PARTIAL_WORDS)


def _describes_food(image: PinterestImage) -> bool:
    """O título/alt descreve comida, bebida, frutas ou uma refeição?"""
    text = f"{image.title} {image.description}".lower()
    return bool(set(_WORD_RE.findall(text)) & _FOOD_WORDS)


@dataclass
class CastingResult:
    """Uma imagem por slide, na ordem dos slides."""

    image_ids: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    image_options: list[list[str]] = field(default_factory=list)
    hook_image_id: str = ""
    # "vision" | "metadata" | "pool" | "fallback" — de onde veio a escolha do
    # hook, para o aviso na prévia dizer a verdade sobre o que aconteceu.
    hook_source: str = ""
    warnings: list[str] = field(default_factory=list)


def cast_carousel(
    slides: list[dict[str, Any]],
    images: list[PinterestImage],
    verdicts: list[Any] | None = None,
    *,
    hook_subject: str = "woman",
    preferred_hook_ids: set[str] | None = None,
    person_images_count: int = 1,
    food_images_count: int = 0,
) -> CastingResult:
    """Escolhe a foto de cada slide. Não muta nada — devolve os image_ids."""
    result = CastingResult()
    if not slides or not images:
        return result

    subjects = _subjects_by_id(verdicts)
    strict_vision = bool(subjects)
    scores = {
        v.image_id: float(getattr(v, "score", 0.0) or 0.0)
        for v in (verdicts or [])
        if getattr(v, "image_id", "")
    }

    hook_index = _hook_index(slides)
    hook_image, hook_source = _pick_hook(
        images,
        subjects,
        scores,
        hook_subject,
        preferred_hook_ids or set(),
    )
    hook_image_id = "" if strict_vision and hook_source == "fallback" else hook_image.image_id
    result.hook_image_id = hook_image_id
    result.hook_source = hook_source

    if hook_source == "fallback" and not strict_vision:
        result.warnings.append(
            "Nenhuma foto com pessoa foi encontrada para o hook — o slide 1 "
            "ficou com a melhor foto disponível. Troque pela galeria na prévia."
        )

    person_images_count = min(max(int(person_images_count or 1), 1), len(slides))
    food_images_count = min(
        max(int(food_images_count or 0), 0),
        max(len(slides) - person_images_count, 0),
    )
    scene_images_count = len(slides) - person_images_count - food_images_count

    person_pool = _subject_pool(
        images,
        subjects,
        scores,
        affinity=lambda image: _person_affinity(image, subjects, hook_subject),
        exclude=hook_image.image_id,
    )
    food_pool = _subject_pool(
        images,
        subjects,
        scores,
        affinity=lambda image: _food_affinity(image, subjects),
        exclude=hook_image.image_id,
    )
    scene_pool = _scene_pool(
        images,
        subjects,
        scores,
        exclude=hook_image.image_id if hook_source != "fallback" else "",
    )

    person_options = (
        [hook_image] + person_pool if hook_source != "fallback" else person_pool
    )
    pools = {
        "person": person_options,
        "food": food_pool,
        "scene": scene_pool,
    }

    result.image_ids = [""] * len(slides)
    result.categories = [""] * len(slides)
    result.image_options = [[] for _ in slides]
    result.image_ids[hook_index] = hook_image_id
    result.categories[hook_index] = "person"
    result.image_options[hook_index] = _image_ids(person_options)
    if hook_image.image_id not in result.image_options[hook_index]:
        result.image_options[hook_index].append(hook_image.image_id)
    used = {hook_image_id} if hook_image_id else set()
    repeat_indexes = {"person": 0, "food": 0, "scene": 0}
    repeated_roles: set[str] = set()
    neutral_slots = 1 if strict_vision and not hook_image_id else 0
    matched_people = 0 if hook_source == "fallback" else 1
    matched_food = 0
    roles = _category_sequence(
        person_images_count - 1,
        food_images_count,
        scene_images_count,
    )
    for index, role in zip(
        (i for i in range(len(slides)) if i != hook_index),
        roles,
    ):
        candidates = pools[role]
        result.categories[index] = role
        result.image_options[index] = _image_ids(candidates)
        image = _pick_unused(candidates, used)
        if image is None and candidates:
            # A cota continua correta quando faltam fotos distintas: repetir
            # dentro da categoria é preferível a vazar pessoa/comida para um
            # slide de cenário. Com pools normais, o ramo não é usado.
            image = candidates[repeat_indexes[role] % len(candidates)]
            repeat_indexes[role] += 1
            repeated_roles.add(role)
        if image is not None:
            if role == "person":
                matched_people += 1
            elif role == "food":
                matched_food += 1
        else:
            # Se a busca não trouxe a categoria pedida, use primeiro cenário
            # confirmado/seguro. Isso pode deixar a cota abaixo do solicitado,
            # mas nunca cria pessoas ou comida extras. O último recurso só
            # existe para o caso extremo de não haver cenário algum no acervo.
            image = _pick_unused(scene_pool, used)
            if image is None and scene_pool:
                image = scene_pool[0]
            if image is None:
                if strict_vision:
                    result.image_ids[index] = ""
                    neutral_slots += 1
                    continue
                image = images[0]
        result.image_ids[index] = image.image_id
        if image.image_id not in result.image_options[index]:
            result.image_options[index].append(image.image_id)
        used.add(image.image_id)

    if matched_people < person_images_count:
        result.warnings.append(
            f"Foram encontradas {matched_people} de {person_images_count} foto(s) "
            "com pessoa/modelo; os outros slides usaram as melhores imagens disponíveis."
        )
    if matched_food < food_images_count:
        result.warnings.append(
            f"Foram encontradas {matched_food} de {food_images_count} foto(s) de "
            "comida; os outros slides usaram as melhores imagens disponíveis."
        )
    if repeated_roles:
        labels = {"person": "pessoa", "food": "comida", "scene": "cenário"}
        repeated = ", ".join(labels[role] for role in sorted(repeated_roles))
        result.warnings.append(
            "O acervo não tinha fotos distintas suficientes em "
            f"{repeated}; as cotas foram preservadas repetindo apenas dentro "
            "da própria categoria."
        )
    if neutral_slots:
        result.warnings.append(
            f"O VLM não confirmou uma categoria segura para {neutral_slots} "
            "slide(s); foi usado fundo neutro para não inserir pessoa, comida "
            "ou cenário fora da cota."
        )

    logger.info(
        "Casting: hook=%s (%s) · pessoas=%d/%d · comida=%d/%d · %d slide(s).",
        hook_image.image_id,
        hook_source,
        matched_people,
        person_images_count,
        matched_food,
        food_images_count,
        len(slides),
    )
    return result


def apply_casting(slides: list[dict[str, Any]], casting: CastingResult) -> None:
    """Grava o image_id escolhido em cada slide, in place.

    `image_id` no slide já é o campo que a prévia, o form de edição e o export
    consultam antes de cair na rotação — o casting só precisa preenchê-lo.
    """
    for index, (slide, image_id) in enumerate(zip(slides, casting.image_ids)):
        slide["image_id"] = image_id
        if index < len(casting.categories):
            slide["image_category"] = casting.categories[index]
        if index < len(casting.image_options):
            slide["image_options"] = list(casting.image_options[index])


def _subjects_by_id(verdicts: list[Any] | None) -> dict[str, str]:
    return {
        v.image_id: str(getattr(v, "subject", "") or "")
        for v in (verdicts or [])
        if getattr(v, "image_id", "")
    }


def _hook_index(slides: list[dict[str, Any]]) -> int:
    """Onde está o hook. Índice 0 quando nenhum slide se declara hook."""
    for i, slide in enumerate(slides):
        if str(slide.get("role") or "") == "hook":
            return i
    return 0


def _pick_hook(
    images: list[PinterestImage],
    subjects: dict[str, str],
    scores: dict[str, float],
    hook_subject: str,
    preferred_hook_ids: set[str],
) -> tuple[PinterestImage, str]:
    """Melhor foto com pessoa para o slide 1, e de onde veio a certeza."""
    ranked = sorted(
        images,
        key=lambda img: (
            _person_affinity(img, subjects, hook_subject),
            img.image_id in preferred_hook_ids,
            scores.get(img.image_id, 0.0),
        ),
        reverse=True,
    )
    best = ranked[0]
    # Mesma escala de `_person_affinity` — o rótulo diz ao usuário quanta
    # confiança a escolha do slide 1 merece.
    affinity = _person_affinity(best, subjects, hook_subject)
    if affinity >= 4:
        return best, "vision"
    if affinity == 3:
        return best, "metadata"
    if affinity == 2:
        return best, "pool"
    return best, "fallback"


def _person_affinity(
    image: PinterestImage,
    subjects: dict[str, str],
    hook_subject: str,
) -> int:
    """Quão bem a foto serve de hook. 0 = sem sinal de pessoa nenhum.

    A escala separa os sinais por confiabilidade, do mais forte ao mais fraco:

      5/4  o VLM olhou a foto e viu pessoa (4 = pessoa, mas não o subject pedido)
      3    a descrição da foto fala de gente — vale a foto, não a busca
      2    a foto veio do pool de retrato — vale a busca, não a foto
      0    nenhum sinal, ou o VLM olhou e disse que não tem pessoa

    Assim uma foto confirmada pelo modelo nunca perde para uma que só veio da
    busca certa, e o metadado desempata quando não há VLM configurado.
    """
    if image.image_id in subjects:
        subject = subjects[image.image_id]
        if subject == hook_subject:
            return 5
        if subject in PERSON_SUBJECTS:
            return 4
        return 0  # o modelo olhou e disse que não tem pessoa
    if subjects:
        return 0  # houve visão no lote, mas esta candidata não foi confirmada
    if _describes_food(image):
        return 0
    if _describes_person(image):
        return 3
    if image.pool == POOL_HOOK:
        return 2
    return 0


def _scene_pool(
    images: list[PinterestImage],
    subjects: dict[str, str],
    scores: dict[str, float],
    *,
    exclude: str,
) -> list[PinterestImage]:
    """Fotos de cenário, melhores primeiro.

    Pessoa e comida ficam fora desta lista; quando o acervo geral não basta, o
    fallback do chamador escolhe outra imagem e mantém o carrossel utilizável.
    """
    candidates = [
        img for img in images
        if img.image_id != exclude and _scene_affinity(img, subjects) > 0
    ]
    if not candidates:
        return []
    return sorted(
        candidates,
        key=lambda img: (
            _scene_affinity(img, subjects),
            scores.get(img.image_id, 0.0),
        ),
        reverse=True,
    )


def _subject_pool(
    images: list[PinterestImage],
    subjects: dict[str, str],
    scores: dict[str, float],
    *,
    affinity,
    exclude: str,
) -> list[PinterestImage]:
    """Candidatas confirmadas por visão, metadado ou pool de busca."""
    candidates = [
        img for img in images
        if img.image_id != exclude and affinity(img) > 0
    ]
    return sorted(
        candidates,
        key=lambda img: (affinity(img), scores.get(img.image_id, 0.0)),
        reverse=True,
    )


def _pick_unused(
    candidates: list[PinterestImage], used: set[str]
) -> PinterestImage | None:
    return next((img for img in candidates if img.image_id not in used), None)


def _image_ids(images: list[PinterestImage]) -> list[str]:
    """IDs únicos, preservando a ordem de preferência do pool."""
    return list(dict.fromkeys(img.image_id for img in images if img.image_id))


def _category_sequence(
    person_count: int, food_count: int, scene_count: int
) -> list[str]:
    """Intercala categorias para evitar blocos repetitivos no carrossel."""
    remaining = {
        "food": max(food_count, 0),
        "scene": max(scene_count, 0),
        "person": max(person_count, 0),
    }
    sequence: list[str] = []
    while any(remaining.values()):
        for role in ("food", "scene", "person"):
            if remaining[role] <= 0:
                continue
            sequence.append(role)
            remaining[role] -= 1
    # O print promocional, quando existe, substitui o último slide depois do
    # casting. Reservar cenário no fim impede que ele apague uma cota de comida
    # ou pessoa em carrosséis curtos.
    if scene_count > 0 and sequence and sequence[-1] != "scene":
        scene_index = max(i for i, role in enumerate(sequence) if role == "scene")
        sequence[scene_index], sequence[-1] = sequence[-1], sequence[scene_index]
    return sequence


def _food_affinity(image: PinterestImage, subjects: dict[str, str]) -> int:
    """Quanto a foto serve à cota de comida."""
    if image.image_id in subjects:
        subject = subjects[image.image_id]
        return 4 if subject == FOOD_SUBJECT else 0
    if subjects:
        return 0
    if _describes_person(image):
        return 0
    if _describes_food(image):
        return 3
    return 2 if image.pool == POOL_FOOD else 0


def _scene_affinity(image: PinterestImage, subjects: dict[str, str]) -> int:
    """Espelho de :func:`_person_affinity` — maior = mais cara de b-roll."""
    if image.image_id in subjects:
        subject = subjects[image.image_id]
        return 3 if subject == SCENE_SUBJECT else 0
    if subjects:
        return 0
    if _describes_person(image) or _describes_food(image):
        return 0
    if image.pool in (POOL_HOOK, POOL_FOOD):
        return 0
    return 2 if image.pool == POOL_SCENE else 1


__all__ = [
    "CastingResult",
    "cast_carousel",
    "apply_casting",
    "PERSON_SUBJECTS",
    "FOOD_SUBJECT",
    "SCENE_SUBJECT",
    "POOL_HOOK",
    "POOL_FOOD",
    "POOL_SCENE",
]
