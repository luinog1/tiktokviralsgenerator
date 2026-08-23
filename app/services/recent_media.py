"""Memória do que já saiu — as fotos dos carrosséis recentes.

O problema que este arquivo resolve: gerar duas vezes com a mesma hashtag
devolvia quase as mesmas fotos. A causa principal era o pool raso da busca
(ver `_POOL_SIZE` em `pinterest_client.py`), mas mesmo com pool fundo o sorteio
é sem memória — nada impede o acaso de repetir a foto do carrossel anterior.

Aqui ficam as identidades (`media_identity`, não `image_id`: o mesmo pin muda
de id entre buscas) das fotos que **entraram nos slides**. Só os slides, não a
galeria inteira: a galeria são as alternativas, e marcar as ~30 candidatas de
cada geração esgotaria a memória em duas rodadas, deixando-a inútil na terceira.

O efeito é uma **preferência**, não um veto: `_cut_pool` manda o que já saiu
para o fim do sorteio e ainda usa essas fotos quando não há material novo. Um
acervo pequeno tem que continuar devolvendo carrossel.

Arquivo em vez de sessão, pelo mesmo motivo do `pinned_person.py`: os projetos
vivem em memória com TTL e a memória precisa sobreviver ao restart.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Iterable

from app.services.pinned_person import INSTANCE_DIR

logger = logging.getLogger(__name__)

RECENT_MEDIA_PATH = os.path.join(INSTANCE_DIR, "recent_media.json")

# Quantas fotos lembrar. Uma busca por query rende ~40 pins acima do piso de
# resolução e um carrossel consome de 3 a 12; 240 cobre bem mais que as poucas
# gerações seguidas que o usuário faz com a mesma hashtag, e passar disso só
# faria a memória saturar o pool e virar sorteio puro de novo.
MAX_REMEMBERED = 240


def load_recent() -> frozenset[str]:
    """As identidades já usadas. Arquivo ausente ou ilegível = memória vazia."""
    try:
        with open(RECENT_MEDIA_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return frozenset()
    identities = data.get("identities") if isinstance(data, dict) else None
    if not isinstance(identities, list):
        return frozenset()
    return frozenset(str(item) for item in identities if str(item or "").strip())


def remember(identities: Iterable[str]) -> None:
    """Grava as fotos deste carrossel no fim da fila, cortando as mais antigas.

    A ordem importa: a fila é antiga → recente, então o corte descarta o que foi
    usado há mais tempo, que é exatamente o que pode voltar a aparecer sem
    incomodar. Uma foto repetida no mesmo carrossel ocupa uma vaga só. Falha de
    escrita não derruba a geração — o carrossel já existe, e perder a memória
    custa uma repetição, não o resultado.
    """
    fresh = list(
        dict.fromkeys(str(item).strip() for item in identities if str(item or "").strip())
    )
    if not fresh:
        return
    queue = [item for item in _ordered() if item not in set(fresh)]
    queue.extend(fresh)
    try:
        os.makedirs(INSTANCE_DIR, exist_ok=True)
        with open(RECENT_MEDIA_PATH, "w", encoding="utf-8") as fh:
            json.dump({"identities": queue[-MAX_REMEMBERED:]}, fh, ensure_ascii=False)
    except OSError as exc:
        logger.warning("Não foi possível gravar a memória de fotos: %s", exc)


def clear_recent() -> None:
    try:
        os.remove(RECENT_MEDIA_PATH)
    except OSError:
        pass


def _ordered() -> list[str]:
    """A fila como está no disco — antiga → recente."""
    try:
        with open(RECENT_MEDIA_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return []
    identities = data.get("identities") if isinstance(data, dict) else None
    if not isinstance(identities, list):
        return []
    return [str(item) for item in identities if str(item or "").strip()]


__all__ = [
    "MAX_REMEMBERED",
    "RECENT_MEDIA_PATH",
    "clear_recent",
    "load_recent",
    "remember",
]
