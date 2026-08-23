"""Fixtures válidas para a suíte inteira.

O único conteúdo até aqui é isolamento de disco: o `GenerationService.run`
grava as fotos usadas em `instance/recent_media.json` para a próxima geração
com a mesma hashtag sortear outras. Sem redirecionar o caminho, **qualquer**
teste que gere um carrossel escreveria no `instance/` do repo e, pior, a
memória gravada por um teste mudaria o sorteio do seguinte.
"""

from __future__ import annotations

import pytest

from app.services import recent_media


@pytest.fixture(autouse=True)
def _tmp_recent_media(tmp_path, monkeypatch):
    monkeypatch.setattr(recent_media, "INSTANCE_DIR", str(tmp_path))
    monkeypatch.setattr(
        recent_media, "RECENT_MEDIA_PATH", str(tmp_path / "recent_media.json")
    )
