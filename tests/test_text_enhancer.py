"""Testes da melhoria opcional do painel (botão do /goviral)."""

from __future__ import annotations

import json

import pytest

from app.adapters import text_enhancer
from app.adapters.text_enhancer import GOVIRAL_PROMO_FALLBACK, enhance_panel
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
    def __init__(self, content: str, status_code: int = 200, message_extra: dict | None = None):
        self._content = content
        self.status_code = status_code
        self.text = content
        self._message_extra = message_extra or {}

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return {
            "choices": [
                {
                    "message": {"content": self._content, **self._message_extra},
                    "finish_reason": "stop",
                }
            ]
        }


def _answer(paragraphs: dict | list, hook: str = "hook novo", **extra) -> str:
    return json.dumps({"hook": hook, "paragraphs": paragraphs, **extra})


def _post_returning(monkeypatch, content: str):
    calls: list[dict] = []

    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append({"url": url, "payload": json})
        return _Response(content)

    monkeypatch.setattr(text_enhancer.requests, "post", fake_post)
    return calls


# ------------------------------------------------------------ enhancer puro
def test_returns_hook_and_paragraphs_in_order(monkeypatch):
    calls = _post_returning(
        monkeypatch,
        _answer({"1": "curto 1", "2": "curto 2"}, goviral=["promo 1", "promo 2"]),
    )
    result = enhance_panel(
        Settings.from_env(_LLM_ENV), "hook antigo", ["parágrafo longo 1", "parágrafo longo 2"]
    )
    assert result == {
        "hook": "hook novo",
        "paragraphs": ["curto 1", "curto 2"],
        "promo": ["promo 1", "promo 2"],
    }
    # O hook e os parágrafos NUMERADOS vão juntos para o LLM: é o que torna o
    # alinhamento verificável e impede o modelo de imitar o exemplo do prompt.
    sent = calls[0]["payload"]["messages"][1]["content"]
    assert json.loads(sent) == {
        "hook": "hook antigo",
        "1": "parágrafo longo 1",
        "2": "parágrafo longo 2",
    }
    system = calls[0]["payload"]["messages"][0]["content"]
    assert "2 parágrafos" in system
    assert "goviral" in system


def test_asks_for_json_mode_without_reasoning(monkeypatch):
    """O pedido vai em JSON mode (no Groq, tira o raciocínio de `content`) e
    com reasoning_effort=none (senão o Qwen gastava o orçamento pensando e o
    JSON nem começava — finish_reason=length dentro de <think>)."""
    calls = _post_returning(monkeypatch, _answer({"1": "curto"}))
    assert enhance_panel(Settings.from_env(_LLM_ENV), "h", ["a"]) is not None
    payload = calls[0]["payload"]
    assert payload["response_format"] == {"type": "json_object"}
    assert payload["reasoning_effort"] == "none"
    assert payload["max_tokens"] >= 4096


def test_endpoint_that_rejects_the_payload_gets_a_minimal_retry(monkeypatch):
    """Endpoint que não aceite json_mode/reasoning_effort responde 400 na hora
    — a chamada é repetida sem os dois, e a melhoria ainda acontece."""
    calls: list[dict] = []

    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append({"payload": json})
        if "response_format" in json or "reasoning_effort" in json:
            return _Response("param not supported", status_code=400)
        return _Response(_answer({"1": "curto"}))

    monkeypatch.setattr(text_enhancer.requests, "post", fake_post)
    result = enhance_panel(Settings.from_env(_LLM_ENV), "h", ["a"])
    assert result is not None and result["paragraphs"] == ["curto"]
    assert len(calls) == 2
    assert "response_format" not in calls[1]["payload"]
    assert "reasoning_effort" not in calls[1]["payload"]


def test_think_block_before_the_json_is_stripped(monkeypatch):
    """No retry sem reasoning_effort o pensamento vem em <think>…</think> antes
    do JSON — inclusive com chaves dentro, que enganariam o parser."""
    _post_returning(
        monkeypatch,
        '<think>vou responder {"paragraphs": "exemplo"}…</think>\n' + _answer({"1": "curto"}),
    )
    result = enhance_panel(Settings.from_env(_LLM_ENV), "h", ["a"])
    assert result is not None and result["paragraphs"] == ["curto"]


def test_json_in_reasoning_field_with_empty_content_is_used(monkeypatch):
    """Modelo de raciocínio pode deixar `content` vazio e pôr a resposta no
    campo `reasoning` (Groq) — ela ainda é aproveitada."""

    def fake_post(url, json=None, headers=None, timeout=None):
        return _Response("", message_extra={"reasoning": _answer({"1": "curto"})})

    monkeypatch.setattr(text_enhancer.requests, "post", fake_post)
    result = enhance_panel(Settings.from_env(_LLM_ENV), "h", ["a"])
    assert result is not None and result["paragraphs"] == ["curto"]


def test_accepts_a_plain_list_with_the_exact_count(monkeypatch):
    """Modelo que ignore os números e devolva lista crua ainda serve — desde
    que venha a contagem exata, que é o que garante o alinhamento."""
    _post_returning(monkeypatch, _answer(["curto 1", "curto 2"]))
    result = enhance_panel(Settings.from_env(_LLM_ENV), "h", ["a", "b"])
    assert result is not None and result["paragraphs"] == ["curto 1", "curto 2"]


def test_empty_hook_in_the_answer_keeps_the_original(monkeypatch):
    _post_returning(monkeypatch, json.dumps({"paragraphs": {"1": "curto"}}))
    result = enhance_panel(Settings.from_env(_LLM_ENV), "hook original", ["a"])
    assert result is not None and result["hook"] == "hook original"


def test_missing_promo_falls_back_to_the_fixed_one(monkeypatch):
    """A promessa do botão — uma das imagens promove o goviral app — não pode
    depender de o LLM obedecer ao campo "goviral"."""
    _post_returning(monkeypatch, _answer({"1": "curto"}))
    result = enhance_panel(Settings.from_env(_LLM_ENV), "h", ["a"])
    assert result is not None and result["promo"] == list(GOVIRAL_PROMO_FALLBACK)


def test_promo_as_a_single_string_still_counts(monkeypatch):
    _post_returning(monkeypatch, _answer({"1": "curto"}, goviral="testa o goviral"))
    result = enhance_panel(Settings.from_env(_LLM_ENV), "h", ["a"])
    assert result is not None and result["promo"] == ["testa o goviral"]


def test_mock_provider_returns_none_without_calling_anything(monkeypatch):
    def boom(*args, **kwargs):  # pragma: no cover - não deve rodar
        raise AssertionError("não deveria chamar o LLM em modo mock")

    monkeypatch.setattr(text_enhancer.requests, "post", boom)
    assert enhance_panel(Settings.from_env({"LLM_PROVIDER": "mock"}), "h", ["a"]) is None


def test_wrong_count_discards_the_whole_answer(monkeypatch):
    """Contagem diferente mudaria a distribuição pelas imagens — a única coisa
    que o botão promete não mexer."""
    _post_returning(monkeypatch, _answer(["só um"]))
    assert enhance_panel(Settings.from_env(_LLM_ENV), "h", ["a", "b"]) is None


def test_missing_number_discards_the_whole_answer(monkeypatch):
    _post_returning(monkeypatch, _answer({"1": "ok"}))
    assert enhance_panel(Settings.from_env(_LLM_ENV), "h", ["a", "b"]) is None


def test_empty_paragraph_discards_the_whole_answer(monkeypatch):
    _post_returning(monkeypatch, _answer({"1": "ok", "2": "  "}))
    assert enhance_panel(Settings.from_env(_LLM_ENV), "h", ["a", "b"]) is None


def test_non_json_answer_returns_none(monkeypatch):
    _post_returning(monkeypatch, "claro! aqui vão os parágrafos mais curtos…")
    assert enhance_panel(Settings.from_env(_LLM_ENV), "h", ["a"]) is None


# ------------------------------------------------------- rota /goviral/enhance
@pytest.fixture
def client(request):
    reset_store()
    env = getattr(request, "param", {"LLM_PROVIDER": "mock"})
    app = create_app(Settings.from_env({"SECRET_KEY": "t", "DEBUG": "false", **env}))
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    return app.test_client()


def test_route_rebuilds_the_panel_with_promo_script_at_the_end(client, monkeypatch):
    monkeypatch.setattr(
        "app.routes.goviral.enhance_panel",
        lambda settings, hook, paragraphs: {
            "hook": "hook melhor",
            "paragraphs": [f"curto {i + 1}" for i in range(len(paragraphs))],
            "promo": ["promo a", "promo b"],
        },
    )
    response = client.post("/goviral/enhance", json={"raw_text": PANEL})
    assert response.status_code == 200
    data = response.get_json()
    assert data["enhanced"] is True
    text = data["raw_text"]
    # O hook sai reescrito; os parágrafos saem melhorados, na ordem; e o promo
    # do goviral fecha o painel como um script novo.
    assert "Hook: hook melhor" in text
    assert "Script 1\nParagraph 1: curto 1\nParagraph 2: curto 2" in text
    assert "Script 2\nParagraph 1: curto 3\nParagraph 2: curto 4" in text
    assert text.endswith("Script 3\nParagraph 1: promo a\nParagraph 2: promo b")
    # O texto remontado continua sendo um painel reconhecível — re-colável.
    from app.adapters.goviral_parser import goviral_blocks

    blocks = goviral_blocks(text)
    assert blocks[0] == "hook melhor"
    assert blocks[1] == "curto 1\n\ncurto 2"
    assert blocks[-1] == "promo a\n\npromo b"


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
