"""Automatic Hook/Scripts generation without the external Go Viral dashboard."""

from __future__ import annotations

import json

import pytest

from app.adapters import content_generator
from app.adapters.content_generator import generate_content_panel
from app.adapters.goviral_parser import goviral_blocks
from app.config import Settings
from app.main import create_app


_LLM_ENV = {
    "SECRET_KEY": "test",
    "DEBUG": "false",
    "LLM_PROVIDER": "openai_compatible",
    "LLM_API_BASE_URL": "https://llm.example/v1",
    "LLM_API_KEY": "secret",
    "LLM_MODEL": "test-model",
}


class _Response:
    def __init__(self, content: str, status_code: int = 200):
        self._content = content
        self.status_code = status_code
        self.text = content

    def raise_for_status(self):
        if self.status_code >= 400:
            raise content_generator.requests.HTTPError(str(self.status_code))

    def json(self):
        return {
            "choices": [
                {
                    "message": {"content": self._content},
                    "finish_reason": "stop",
                }
            ]
        }


def _answer(script_count: int = 5, *, include_app: bool = False) -> str:
    scripts = []
    for i in range(1, script_count + 1):
        body = f"detalhe concreto do momento {i} que fecha a ideia"
        if include_app and i == script_count - 1:
            body = "eu revisei o video no Go Viral app antes de postar"
        scripts.append(
            {
                "position": i,
                "paragraph_1": f"momento {i} — resultado",
                "paragraph_2": body,
            }
        )
    return json.dumps(
        {
            "hook": "minha jornada — e o que quase me fez desistir",
            "scripts": scripts,
            "image_theme": "creator lifestyle",
            "image_keywords": ["creator", "phone", "analytics"],
        }
    )


def test_generates_a_canonical_parseable_panel(monkeypatch):
    calls: list[dict] = []

    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append({"url": url, "payload": json, "timeout": timeout})
        return _Response(_answer())

    monkeypatch.setattr(content_generator.requests, "post", fake_post)
    result = generate_content_panel(
        Settings.from_env(_LLM_ENV),
        brief="meus primeiros meses criando conteudo, com altos e baixos reais",
        audience="micro influencers",
        language="pt-BR",
        slide_count=6,
        include_app=True,
    )

    assert result is not None
    assert len(result["scripts"]) == 5
    assert result["theme"] == "creator lifestyle"
    assert result["keywords"] == ["creator", "phone", "analytics"]
    assert goviral_blocks(result["raw_text"]) == result["blocks"]
    assert "—" not in result["raw_text"]
    # The model ignored the app rule, so the penultimate script is reserved for it.
    assert "Go Viral app" in result["scripts"][-2]["paragraph_2"]

    payload = calls[0]["payload"]
    assert payload["response_format"] == {"type": "json_object"}
    assert payload["reasoning_effort"] == "none"
    system = payload["messages"][0]["content"]
    assert "exatamente 5 scripts" in system
    assert "nunca invente autoridade" in system
    assert "travessao longo" in system


def test_keeps_the_model_app_script_when_present(monkeypatch):
    monkeypatch.setattr(
        content_generator.requests,
        "post",
        lambda *args, **kwargs: _Response(_answer(include_app=True)),
    )
    result = generate_content_panel(
        Settings.from_env(_LLM_ENV),
        brief="uma historia real de consistencia e crescimento",
        slide_count=6,
        include_app=True,
    )

    assert result is not None
    assert result["scripts"][-2]["paragraph_1"].startswith("momento 4")
    assert "Go Viral app" in result["scripts"][-2]["paragraph_2"]


def test_rejects_a_partial_script_list(monkeypatch):
    monkeypatch.setattr(
        content_generator.requests,
        "post",
        lambda *args, **kwargs: _Response(_answer(script_count=4)),
    )
    result = generate_content_panel(
        Settings.from_env(_LLM_ENV),
        brief="uma historia longa o bastante para gerar o roteiro",
        slide_count=6,
    )

    assert result is None


def test_retries_without_optional_openai_parameters(monkeypatch):
    calls: list[dict] = []

    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append(dict(json))
        if len(calls) == 1:
            return _Response("unsupported parameter", status_code=400)
        return _Response(_answer())

    monkeypatch.setattr(content_generator.requests, "post", fake_post)
    result = generate_content_panel(
        Settings.from_env(_LLM_ENV),
        brief="uma historia real para transformar em roteiro",
        slide_count=6,
    )

    assert result is not None
    assert len(calls) == 2
    assert "response_format" not in calls[1]
    assert "reasoning_effort" not in calls[1]


@pytest.fixture
def configured_client():
    app = create_app(Settings.from_env(_LLM_ENV))
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    return app.test_client()


def test_generate_content_route_returns_the_editable_panel(configured_client, monkeypatch):
    generated = {
        "hook": "hook pronto",
        "scripts": [
            {"position": 1, "paragraph_1": "caixa 1", "paragraph_2": "caixa 2"},
            {"position": 2, "paragraph_1": "caixa 3", "paragraph_2": "caixa 4"},
        ],
        "theme": "creator lifestyle",
        "keywords": ["creator", "phone"],
        "raw_text": "Hook\nhook pronto\nScript 1\nParagraph 1: caixa 1\nParagraph 2: caixa 2",
        "blocks": ["hook pronto", "caixa 1\n\ncaixa 2", "caixa 3\n\ncaixa 4"],
    }
    monkeypatch.setattr(
        "app.routes.goviral.generate_content_panel",
        lambda settings, **kwargs: generated,
    )

    response = configured_client.post(
        "/goviral/generate-content",
        json={
            "brief": "minha historia real como criadora",
            "audience": "small creators",
            "language": "en-US",
            "slide_count": 3,
            "include_app": True,
        },
    )
    data = response.get_json()

    assert response.status_code == 200
    assert data["generated"] is True
    assert data["raw_text"].startswith("Hook")
    assert data["theme"] == "creator lifestyle"


def test_generate_content_route_explains_when_llm_is_not_configured():
    app = create_app(Settings.from_env({"SECRET_KEY": "test", "LLM_PROVIDER": "mock"}))
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    response = app.test_client().post(
        "/goviral/generate-content",
        json={"brief": "uma historia real com detalhes suficientes", "slide_count": 6},
    )

    assert response.status_code == 503
    assert "LLM" in response.get_json()["reason"]

