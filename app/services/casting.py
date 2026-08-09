"""Casting — decide qual foto entra em cada slide, pelo papel do slide.

Antes, o slide `i` usava a imagem `i % len(images)`: pura rotação. Num photo
post de lifestyle o slide 1 é o que para o scroll, e o que para o scroll é uma
pessoa em cena — não um prato de comida. Rotação não garante isso, porque a
ordem vinha do ranking de relevância, que não olha o assunto da foto.

Aqui o slide de `hook` recebe uma foto com pessoa e os demais recebem cenário
(estética, viagem, comida, objeto). Três fontes de sinal, em ordem de confiança:

1. `subject` do VLM — o modelo olhou a foto e disse o que tem nela.
2. Título/descrição da foto — o Unsplash escreve "a woman sitting on a bed".
   Descreve *aquela* foto, então vale mais que a busca que a trouxe.
3. `pool` da imagem — de qual das duas buscas ela veio (a query do hook pede
   retrato; a de cenário pede estética). É o sinal que faz o casting funcionar
   sem visão configurada, que é o estado padrão do projeto.

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
SCENE_SUBJECT = "scene"

POOL_HOOK = "hook"
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

_WORD_RE = re.compile(r"[a-zà-ÿ]+")


def _describes_person(image: PinterestImage) -> bool:
    """A descrição da foto fala de gente (e não de um pedaço de gente)?"""
    text = f"{image.title} {image.description}".lower()
    words = set(_WORD_RE.findall(text))
    if not words & _PERSON_WORDS:
        return False
    return not (words & _PARTIAL_WORDS)


@dataclass
class CastingResult:
    """Uma imagem por slide, na ordem dos slides."""

    image_ids: list[str] = field(default_factory=list)
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
) -> CastingResult:
    """Escolhe a foto de cada slide. Não muta nada — devolve os image_ids."""
    result = CastingResult()
    if not slides or not images:
        return result

    subjects = _subjects_by_id(verdicts)
    scores = {
        v.image_id: float(getattr(v, "score", 0.0) or 0.0)
        for v in (verdicts or [])
        if getattr(v, "image_id", "")
    }

    hook_index = _hook_index(slides)
    hook_image, hook_source = _pick_hook(images, subjects, scores, hook_subject)
    result.hook_image_id = hook_image.image_id
    result.hook_source = hook_source

    if hook_source == "fallback":
        result.warnings.append(
            "Nenhuma foto com pessoa foi encontrada para o hook — o slide 1 "
            "ficou com a melhor foto disponível. Troque pela galeria na prévia."
        )

    scene_pool = _scene_pool(images, subjects, scores, exclude=hook_image.image_id)
    if not scene_pool:
        scene_pool = [img for img in images if img.image_id != hook_image.image_id]
    if not scene_pool:
        scene_pool = [hook_image]

    scene_cursor = 0
    for index in range(len(slides)):
        if index == hook_index:
            result.image_ids.append(hook_image.image_id)
            continue
        result.image_ids.append(scene_pool[scene_cursor % len(scene_pool)].image_id)
        scene_cursor += 1

    logger.info(
        "Casting: hook=%s (%s) · %d foto(s) de cenário para %d slide(s).",
        hook_image.image_id, hook_source, len(scene_pool), len(slides),
    )
    return result


def apply_casting(slides: list[dict[str, Any]], casting: CastingResult) -> None:
    """Grava o image_id escolhido em cada slide, in place.

    `image_id` no slide já é o campo que a prévia, o form de edição e o export
    consultam antes de cair na rotação — o casting só precisa preenchê-lo.
    """
    for slide, image_id in zip(slides, casting.image_ids):
        slide["image_id"] = image_id


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
) -> tuple[PinterestImage, str]:
    """Melhor foto com pessoa para o slide 1, e de onde veio a certeza."""
    ranked = sorted(
        images,
        key=lambda img: (
            _person_affinity(img, subjects, hook_subject),
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
    subject = subjects.get(image.image_id, "")
    if subject:
        if subject == hook_subject:
            return 5
        if subject in PERSON_SUBJECTS:
            return 4
        return 0  # o modelo olhou e disse que não tem pessoa
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

    "geralmente" cenário, não "só" cenário: uma segunda foto com pessoa entra
    se sobrar espaço, mas atrás de todas as de cenário — é o que dá ao
    carrossel a cara de hook + b-roll em vez de álbum de retratos.
    """
    candidates = [img for img in images if img.image_id != exclude]
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


def _scene_affinity(image: PinterestImage, subjects: dict[str, str]) -> int:
    """Espelho de :func:`_person_affinity` — maior = mais cara de b-roll."""
    subject = subjects.get(image.image_id, "")
    if subject == SCENE_SUBJECT:
        return 3
    if subject in PERSON_SUBJECTS:
        return 0
    if _describes_person(image):
        return 0
    return 2 if image.pool == POOL_SCENE else 1


__all__ = [
    "CastingResult",
    "cast_carousel",
    "apply_casting",
    "PERSON_SUBJECTS",
    "SCENE_SUBJECT",
    "POOL_HOOK",
    "POOL_SCENE",
]
