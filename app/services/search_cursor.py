"""Onde a última busca parou — o cursor de paginação de cada query.

O problema que este arquivo resolve: **a busca é determinística**. Medido em
2026-08-24, `pinterest-dl` com a query "morning routine aesthetic" devolve os
MESMOS 50 pins, na MESMA ordem, em duas chamadas seguidas (`ordem identica:
True`). O Unsplash faz o mesmo com `order_by=relevant`. Sortear um recorte
desse pool ajuda, mas não resolve: dois sorteios de 14 num pool de 40 se
sobrepõem por aritmética, e o ranking depois reordena os dois recortes pelo
mesmo critério — então as fotos do topo voltam ao carrossel toda vez.

A correção é **não pedir a mesma página**. O `/resource/BaseSearchResource/`
do Pinterest pagina por `bookmarks`: guardar o bookmark da última página lida
faz a próxima geração continuar de onde a anterior parou, com custo idêntico
(as páginas puladas não são baixadas de novo). Medido no mesmo dia: página 1 e
página 2 têm **overlap zero**, e o bookmark funciona em outra instância de
`Api` — ou seja, sobrevive ao fim da requisição HTTP. O Unsplash não tem
bookmark, mas tem `page`, e um contador serve para a mesma coisa.

O arquivo guarda, por fonte e por query normalizada:

* `bookmarks` — o cursor opaco do Pinterest (lista, como a API pede).
* `page` — o número da próxima página do Unsplash.

Quando o acervo acaba (`-end-` nos bookmarks, ou página além do catálogo), o
cursor **volta ao começo**: acervo esgotado tem que continuar devolvendo
carrossel, e a essa altura o que estava no topo já não sai há muitas gerações.

Arquivo em vez de sessão, pelo mesmo motivo do `recent_media.py`: os projetos
vivem em memória com TTL e o cursor precisa sobreviver ao restart. No Render,
sem disco persistente montado, um redeploy zera isto — e aí a primeira geração
depois do deploy repete a de antes dele, uma vez. Nada mais quebra: o sorteio
de `_cut_pool` e a memória de `recent_media` continuam valendo.
"""

from __future__ import annotations

import json
import logging
import os
import time
import unicodedata

from app.services.pinned_person import INSTANCE_DIR

logger = logging.getLogger(__name__)

SEARCH_CURSOR_PATH = os.path.join(INSTANCE_DIR, "search_cursors.json")

# Quantas queries diferentes lembrar. Cada entrada custa ~200 bytes; 400 cobre
# meses de temas distintos e evita que o arquivo cresça sem teto. O corte
# descarta as menos usadas recentemente — que são justamente as que já podem
# recomeçar do topo sem ninguém notar.
MAX_CURSORS = 400

# Um cursor velho não vale nada: o acervo do Pinterest para "rotina matinal"
# mudou nesse tempo, e retomar de um bookmark de duas semanas atrás pode cair
# num trecho que já não existe. Vencido, ele é descartado e a busca recomeça
# do topo — que a essa altura é material novo de verdade.
CURSOR_TTL_SECONDS = 14 * 24 * 3600


def cursor_key(source: str, query: str) -> str:
    """A chave do cursor: a fonte mais a query sem acento, caixa nem ordem.

    Normalizada porque "Rotina Matinal" e "rotina matinal" são a MESMA busca do
    ponto de vista da API — duas chaves aqui dariam a cada uma seu cursor, e as
    duas gerações voltariam a começar do topo. A ordem dos termos também não
    conta: `sorted` faz "cafe manha" e "manha cafe" compartilharem o cursor,
    porque compartilham o resultado.
    """
    plain = "".join(
        char
        for char in unicodedata.normalize("NFKD", str(query or "").casefold())
        if not unicodedata.combining(char)
    )
    terms = sorted(set(plain.split()))
    return f"{str(source or '?').strip().lower()}|{' '.join(terms)}"


def load_cursor(source: str, query: str) -> dict:
    """Onde a busca parou. `{}` quando é a primeira vez (ou o cursor venceu)."""
    entries = _entries()
    entry = entries.get(cursor_key(source, query))
    if not isinstance(entry, dict):
        return {}
    if time.time() - float(entry.get("used") or 0) > CURSOR_TTL_SECONDS:
        return {}
    cursor: dict = {}
    bookmarks = entry.get("bookmarks")
    if isinstance(bookmarks, list):
        cursor["bookmarks"] = [str(item) for item in bookmarks if str(item or "").strip()]
    try:
        page = int(entry.get("page") or 0)
    except (TypeError, ValueError):
        page = 0
    if page > 0:
        cursor["page"] = page
    return cursor


def save_cursor(
    source: str,
    query: str,
    *,
    bookmarks: list[str] | None = None,
    page: int | None = None,
) -> None:
    """Grava onde esta busca parou, para a próxima geração continuar dali.

    Falha de escrita não derruba a geração: o carrossel já existe, e perder o
    cursor custa uma repetição na próxima vez, não o resultado.
    """
    key = cursor_key(source, query)
    entries = _entries()
    entry: dict = {"used": time.time()}
    if bookmarks is not None:
        entry["bookmarks"] = [str(item) for item in bookmarks if str(item or "").strip()]
    if page is not None:
        entry["page"] = max(int(page), 0)
    entries[key] = entry

    if len(entries) > MAX_CURSORS:
        # Menos usadas recentemente primeiro: o corte tira o cursor de quem não
        # gera com aquele tema há mais tempo.
        ordered = sorted(
            entries.items(), key=lambda item: float((item[1] or {}).get("used") or 0)
        )
        entries = dict(ordered[-MAX_CURSORS:])

    try:
        os.makedirs(INSTANCE_DIR, exist_ok=True)
        with open(SEARCH_CURSOR_PATH, "w", encoding="utf-8") as fh:
            json.dump({"cursors": entries}, fh, ensure_ascii=False)
    except OSError as exc:
        logger.warning("Não foi possível gravar o cursor de busca: %s", exc)


def reset_cursor(source: str, query: str) -> None:
    """Volta esta busca para o começo do acervo — o `-end-` do Pinterest."""
    save_cursor(source, query, bookmarks=[], page=0)


def clear_cursors() -> None:
    try:
        os.remove(SEARCH_CURSOR_PATH)
    except OSError:
        pass


def _entries() -> dict:
    try:
        with open(SEARCH_CURSOR_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    cursors = data.get("cursors") if isinstance(data, dict) else None
    if not isinstance(cursors, dict):
        return {}
    return {str(key): value for key, value in cursors.items() if isinstance(value, dict)}


__all__ = [
    "CURSOR_TTL_SECONDS",
    "MAX_CURSORS",
    "SEARCH_CURSOR_PATH",
    "clear_cursors",
    "cursor_key",
    "load_cursor",
    "reset_cursor",
    "save_cursor",
]
