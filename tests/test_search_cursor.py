"""Testes do cursor de busca — onde a última geração parou em cada query.

Nenhum teste toca o disco real: o `conftest.py` manda o JSON para o tmp_path.

O defeito que este módulo existe para corrigir: a busca é **determinística**.
Medido em 2026-08-24, `pinterest-dl` devolve os mesmos 50 pins na mesma ordem
em duas chamadas seguidas com a mesma query, e o Unsplash faz igual com
`order_by=relevant`. Guardar a posição é o que faz a geração seguinte pedir a
página SEGUINTE, em vez de sortear de novo dentro do mesmo pool.
"""

from __future__ import annotations

import json

from app.services import search_cursor
from app.services.search_cursor import (
    CURSOR_TTL_SECONDS,
    MAX_CURSORS,
    clear_cursors,
    cursor_key,
    load_cursor,
    reset_cursor,
    save_cursor,
)


def test_a_query_never_searched_has_no_cursor():
    assert load_cursor("pinterest_search", "rotina matinal") == {}


def test_what_was_saved_comes_back():
    save_cursor("pinterest_search", "rotina matinal", bookmarks=["bm1"])

    assert load_cursor("pinterest_search", "rotina matinal") == {"bookmarks": ["bm1"]}


def test_the_page_and_the_bookmarks_are_independent_fields():
    """O Pinterest pagina por bookmark opaco e o Unsplash por número de página.
    São duas fontes com dois tipos de cursor, no mesmo arquivo."""
    save_cursor("pinterest_search", "cafe", bookmarks=["bm1"])
    save_cursor("unsplash_search", "cafe", page=3)

    assert load_cursor("pinterest_search", "cafe") == {"bookmarks": ["bm1"]}
    assert load_cursor("unsplash_search", "cafe") == {"page": 3}


def test_the_source_is_part_of_the_key():
    """Busca, "mais como este" e Unsplash paginam streams diferentes: uma
    posição compartilhada faria uma pular o começo da outra."""
    save_cursor("pinterest_search", "cafe", bookmarks=["busca"])
    save_cursor("pinterest_related", "cafe", bookmarks=["relacionado"])

    assert load_cursor("pinterest_search", "cafe")["bookmarks"] == ["busca"]
    assert load_cursor("pinterest_related", "cafe")["bookmarks"] == ["relacionado"]


def test_the_same_search_written_differently_shares_the_cursor():
    """"Rotina Matinal" e "rotina matinal" são a MESMA busca para a API. Duas
    chaves dariam a cada uma seu cursor, e as duas voltariam ao topo."""
    save_cursor("pinterest_search", "Rotina Matinal", bookmarks=["bm1"])

    assert load_cursor("pinterest_search", "rotina  matinal")["bookmarks"] == ["bm1"]
    assert load_cursor("pinterest_search", "ROTINA MATINAL")["bookmarks"] == ["bm1"]


def test_the_order_of_the_terms_does_not_create_a_second_cursor():
    """A busca por "cafe manha" e por "manha cafe" devolve o mesmo acervo."""
    assert cursor_key("pinterest_search", "cafe manha") == cursor_key(
        "pinterest_search", "manha cafe"
    )


def test_accents_do_not_create_a_second_cursor():
    assert cursor_key("pinterest_search", "café da manhã") == cursor_key(
        "pinterest_search", "cafe da manha"
    )


def test_a_reset_sends_the_query_back_to_the_top():
    """É o `-end-` do Pinterest: acervo esgotado tem que voltar ao começo, não
    ficar preso no fim devolvendo nada."""
    save_cursor("pinterest_search", "tema", bookmarks=["bm9"])
    reset_cursor("pinterest_search", "tema")

    assert load_cursor("pinterest_search", "tema").get("bookmarks") == []


def test_an_expired_cursor_is_ignored(monkeypatch):
    """Cursor velho aponta para um trecho do acervo que pode já não existir —
    e a essa altura o topo é material novo de verdade."""
    save_cursor("pinterest_search", "tema", bookmarks=["bm-antigo"])
    envelhecido = json.loads(
        open(search_cursor.SEARCH_CURSOR_PATH, encoding="utf-8").read()
    )
    chave = cursor_key("pinterest_search", "tema")
    envelhecido["cursors"][chave]["used"] -= CURSOR_TTL_SECONDS + 1
    with open(search_cursor.SEARCH_CURSOR_PATH, "w", encoding="utf-8") as fh:
        json.dump(envelhecido, fh)

    assert load_cursor("pinterest_search", "tema") == {}


def test_the_file_does_not_grow_without_a_ceiling():
    """Cada tema distinto é uma entrada. O corte tira as menos usadas
    recentemente — que são as que podem recomeçar do topo sem ninguém notar."""
    for i in range(MAX_CURSORS + 20):
        save_cursor("pinterest_search", f"tema {i}", bookmarks=[f"bm{i}"])

    with open(search_cursor.SEARCH_CURSOR_PATH, encoding="utf-8") as fh:
        cursors = json.load(fh)["cursors"]

    assert len(cursors) <= MAX_CURSORS
    # As últimas gravadas sobrevivem; as primeiras é que saem.
    assert cursor_key("pinterest_search", f"tema {MAX_CURSORS + 19}") in cursors
    assert cursor_key("pinterest_search", "tema 0") not in cursors


def test_a_corrupt_file_reads_as_no_cursor(monkeypatch):
    """Arquivo ilegível não pode derrubar a geração: sem cursor, a busca
    recomeça do topo, que é o comportamento antigo."""
    with open(search_cursor.SEARCH_CURSOR_PATH, "w", encoding="utf-8") as fh:
        fh.write("{isto nao e json")

    assert load_cursor("pinterest_search", "tema") == {}


def test_a_write_failure_does_not_raise(monkeypatch):
    """O carrossel já existe quando o cursor é gravado: perder a gravação custa
    uma repetição na próxima geração, não o resultado desta."""

    def _explode(*args, **kwargs):
        raise OSError("disco cheio")

    monkeypatch.setattr("builtins.open", _explode)
    save_cursor("pinterest_search", "tema", bookmarks=["bm1"])  # não levanta


def test_clearing_removes_the_file():
    save_cursor("pinterest_search", "tema", bookmarks=["bm1"])
    clear_cursors()

    assert load_cursor("pinterest_search", "tema") == {}
