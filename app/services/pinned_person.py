"""Pessoa fixada — o pin do hook guardado para os próximos carrosséis.

O botão "Fixar esta pessoa" na prévia grava aqui o pin da foto do hook. Nos
formulários, um checkbox opcional (desligado por padrão) manda a busca do hook
usar os pins RELACIONADOS a esse pin — o "mais como este" do Pinterest — em vez
da query de retrato. Para um pin de retrato, os relacionados costumam trazer a
mesma pessoa: o sinal é a similaridade visual do próprio Pinterest, nenhum
reconhecimento facial acontece aqui.

Arquivo em vez da sessão: os projetos vivem em memória com TTL, e a pessoa
fixada é uma escolha do usuário que precisa sobreviver ao restart. Só um pin é
guardado — fixar outra pessoa substitui a anterior.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

logger = logging.getLogger(__name__)

# Raiz do repo: app/services/ → app/ → raiz. `instance/` está no .gitignore —
# a pessoa fixada é estado local, como o .env.
INSTANCE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "instance",
)
PINNED_PERSON_PATH = os.path.join(INSTANCE_DIR, "pinned_person.json")

# URL de pin em qualquer domínio do Pinterest (www, br, pt...). O id numérico é
# o que importa: a URL guardada é canonizada para o domínio principal, que é o
# que a pinterest-dl espera receber.
_PIN_URL_RE = re.compile(
    r"^https?://(?:[a-z0-9-]+\.)?pinterest\.[a-z.]+/pin/(\d+)", re.IGNORECASE
)


def pin_url_from_image(image: dict[str, Any]) -> str:
    """URL canônica do pin, ou "" quando a foto não é um pin do Pinterest.

    Unsplash, mock e os prints do goviral_assets/ caem no "" — fixar só faz
    sentido quando há um pin para pedir relacionados.
    """
    match = _PIN_URL_RE.match(str(image.get("source_url") or ""))
    if not match:
        return ""
    return f"https://www.pinterest.com/pin/{match.group(1)}/"


def load_pinned() -> dict[str, Any] | None:
    """A pessoa fixada, ou None. Arquivo ausente ou ilegível = ninguém fixado."""
    try:
        with open(PINNED_PERSON_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not str(data.get("pin_url") or ""):
        return None
    return data


def save_pinned(image: dict[str, Any]) -> dict[str, Any] | None:
    """Fixa a pessoa desta foto. None quando a foto não é um pin do Pinterest."""
    pin_url = pin_url_from_image(image)
    if not pin_url:
        return None
    data = {
        "pin_url": pin_url,
        "image_id": str(image.get("image_id") or ""),
        "image_url": str(image.get("image_url") or ""),
        "thumb_url": str(image.get("thumb_url") or ""),
        "title": str(image.get("title") or ""),
    }
    os.makedirs(INSTANCE_DIR, exist_ok=True)
    with open(PINNED_PERSON_PATH, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    logger.info("Pessoa fixada: %s", pin_url)
    return data


def clear_pinned() -> None:
    try:
        os.remove(PINNED_PERSON_PATH)
    except OSError:
        pass


__all__ = [
    "INSTANCE_DIR",
    "PINNED_PERSON_PATH",
    "pin_url_from_image",
    "load_pinned",
    "save_pinned",
    "clear_pinned",
]
