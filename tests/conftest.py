"""Fixtures válidas para a suíte inteira.

O único conteúdo até aqui é isolamento de disco: o `GenerationService.run`
grava as fotos usadas em `instance/recent_media.json` para a próxima geração
com a mesma hashtag sortear outras, e a busca grava em
`instance/search_cursors.json` a página onde parou. Sem redirecionar os dois
caminhos, **qualquer** teste que gere um carrossel escreveria no `instance/` do
repo e, pior, o estado gravado por um teste mudaria o resultado do seguinte.
"""

from __future__ import annotations

import pytest

from app.services import recent_media, search_cursor


@pytest.fixture(autouse=True)
def _tmp_recent_media(tmp_path, monkeypatch):
    monkeypatch.setattr(recent_media, "INSTANCE_DIR", str(tmp_path))
    monkeypatch.setattr(
        recent_media, "RECENT_MEDIA_PATH", str(tmp_path / "recent_media.json")
    )


@pytest.fixture(autouse=True)
def _tmp_search_cursor(tmp_path, monkeypatch):
    monkeypatch.setattr(search_cursor, "INSTANCE_DIR", str(tmp_path))
    monkeypatch.setattr(
        search_cursor, "SEARCH_CURSOR_PATH", str(tmp_path / "search_cursors.json")
    )
