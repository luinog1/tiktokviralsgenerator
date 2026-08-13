"""Testes da simplificação opcional dos parágrafos (botão do /goviral)."""

from __future__ import annotations

import json

import pytest

from app.adapters import text_enhancer
from app.adapters.text_enhancer import enhance_paragraphs
from app.config import Settings
from app.main import create_app
from app.services.session_store import reset_store

_LLM_ENV = {
    "LLM_PROVIDER": "openai_compatible",
    "LLM_API_BASE_URL": "https://llm.example/v1",
    "LLM_API_KEY": "k",
    "LLM_MODEL": "test-model",
}

PANEL = (
    "Hook\n"
    "eu postava todo dia e nada acontecia\n"
    "Script 1\n"
    "Paragraph 1:\n"
    "eu era consistente mas continuava chutando o que postar\n"
    "Paragraph 2:\n"
    "postava todo dia sem plano nenhum e sem olhar os dados\n"
    "Script 2\n"
    "Paragraph 1:\n"
    "comecei a analisar o que funcionava de verdade\n"
    "Paragraph 2:\n"
    "e o alcance dobrou em duas semanas\n"
)


class _Response:
    status_code = 200

    def __init__(self, content: str):
        self._content = content

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return {"choices": [{"message": {"content": self._content}}]}


def _post_returning(monkeypatch, content: str):
    calls: list[dict] = []

    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append({"url": url, "payload": json})
        return _Response(content)

    monkeypatch.setattr(text_enhancer.requests, "post", fake_post)
    return calls


# ------------------------------------------------------------ enhancer puro
def test_returns_simplified_paragraphs_in_order(monkeypatch):
    calls = _post_returning(
        monkeypatch, json.dumps({"paragraphs": ["curto 1", "curto 2"]})
    )
    result = enhance_paragraphs(
        Settings.from_env(_LLM_ENV), ["parágrafo longo 1", "parágrafo longo 2"]
    )
    assert result == ["curto 1", "curto 2"]
    # Os parágrafos vão para o LLM como JSON, na ordem dada.
    sent = calls[0]["payload"]["messages"][1]["content"]
    assert json.loads(sent) == ["parágrafo longo 1", "parágrafo longo 2"]


def test_mock_provider_returns_none_without_calling_anything(monkeypatch):
    def boom(*args, **kwargs):  # pragma: no cover - não deve rodar
        raise AssertionError("não deveria chamar o LLM em modo mock")

    monkeypatch.setattr(text_enhancer.requests, "post", boom)
    assert enhance_paragraphs(Settings.from_env({"LLM_PROVIDER": "mock"}), ["a"]) is None


def test_wrong_count_discards_the_whole_answer(monkeypatch):
    """Contagem diferente mudaria a distribuição pelas imagens — a única coisa
    que o botão promete não mexer."""
    _post_returning(monkeypatch, json.dumps({"paragraphs": ["só um"]}))
    assert enhance_paragraphs(Settings.from_env(_LLM_ENV), ["a", "b"]) is None


def test_empty_paragraph_discards_the_whole_answer(monkeypatch):
    _post_returning(monkeypatch, json.dumps({"paragraphs": ["ok", "  "]}))
    assert enhance_paragraphs(Settings.from_env(_LLM_ENV), ["a", "b"]) is None


def test_non_json_answer_returns_none(monkeypatch):
    _post_returning(monkeypatch, "claro! aqui vão os parágrafos mais curtos…")
    assert enhance_paragraphs(Settings.from_env(_LLM_ENV), ["a"]) is None


# ------------------------------------------------------- rota /goviral/enhance
@pytest.fixture
def client(request):
    reset_store()
    env = getattr(request, "param", {"LLM_PROVIDER": "mock"})
    app = create_app(Settings.from_env({"SECRET_KEY": "t", "DEBUG": "false", **env}))
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    return app.test_client()


def test_route_rebuilds_the_panel_with_hook_untouched(client, monkeypatch):
    monkeypatch.setattr(
        "app.routes.goviral.enhance_paragraphs",
        lambda settings, paragraphs: [f"curto {i + 1}" for i in range(len(paragraphs))],
    )
    response = client.post("/goviral/enhance", json={"raw_text": PANEL})
    assert response.status_code == 200
    data = response.get_json()
    assert data["enhanced"] is True
    text = data["raw_text"]
    # O hook sai como entrou; os parágrafos saem simplificados, na ordem.
    assert "Hook: eu postava todo dia e nada acontecia" in text
    assert "Script 1\nParagraph 1: curto 1\nParagraph 2: curto 2" in text
    assert "Script 2\nParagraph 1: curto 3\nParagraph 2: curto 4" in text
    # O texto remontado continua sendo um painel reconhecível — re-colável.
    from app.adapters.goviral_parser import goviral_blocks

    blocks = goviral_blocks(text)
    assert blocks[0] == "eu postava todo dia e nada acontecia"
    assert blocks[1] == "curto 1\n\ncurto 2"


def test_route_without_llm_says_why(client):
    response = client.post("/goviral/enhance", json={"raw_text": PANEL})
    assert response.status_code == 200
    data = response.get_json()
    assert data["enhanced"] is False
    assert "LLM" in data["reason"]


def test_route_rejects_text_that_is_not_the_panel(client):
    response = client.post("/goviral/enhance", json={"raw_text": "texto qualquer"})
    assert response.status_code == 422
    assert response.get_json()["enhanced"] is False
