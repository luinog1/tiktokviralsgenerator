"""Testes de rotas — fluxo de geração de carrossel em modo mock."""

from __future__ import annotations

import io
import re
import zipfile

import pytest

from app.main import create_app
from app.config import Settings
from app.services.session_store import reset_store


@pytest.fixture
def app():
    reset_store()
    settings = Settings.from_env({
        "FLASK_ENV": "testing",
        "SECRET_KEY": "test-secret",
        "DEBUG": "false",
        "LLM_PROVIDER": "mock",
        "RANKING_ENABLED": "true",
    })
    app = create_app(settings)
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    return app


@pytest.fixture
def client(app):
    return app.test_client()


def test_health_returns_ok(client):
    response = client.get("/health")
    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "ok"
    assert data["providers"]["composer"] == "mock"
    assert data["providers"]["goviralai"] == "external_manual"


def test_health_reports_mock_images_when_no_key(client, monkeypatch):
    monkeypatch.delenv("UNSPLASH_ACCESS_KEY", raising=False)
    data = client.get("/health").get_json()
    assert data["providers"]["images"] == "mock"
    assert data["images_diagnostic"]["using_mock"] is True


def test_health_reports_unsplash_when_key_is_set(client, monkeypatch):
    """Antes o /health derivava o provider só de PINTEREST_ACCESS_TOKEN, então
    uma chave Unsplash ativa ainda era reportada como 'mock' — não havia como
    saber por que o carrossel saía com gradientes."""
    monkeypatch.setenv("UNSPLASH_ACCESS_KEY", "chave-de-teste")
    data = client.get("/health").get_json()
    assert data["providers"]["images"] == "unsplash"
    assert data["images_diagnostic"]["using_mock"] is False


def test_health_never_leaks_the_unsplash_key(client, monkeypatch):
    monkeypatch.setenv("UNSPLASH_ACCESS_KEY", "segredo-nao-pode-vazar")
    body = client.get("/health").data.decode("utf-8")
    assert "segredo-nao-pode-vazar" not in body


def test_index_returns_landing(client):
    response = client.get("/")
    assert response.status_code == 200
    body = response.data.decode("utf-8")
    assert "ViralPost Studio" in body
    assert "goviral.ai" in body
    assert "Criar carrossel" in body


def test_create_form_renders(client):
    response = client.get("/create")
    assert response.status_code == 200
    body = response.data.decode("utf-8")
    assert "Briefing do carrossel" in body
    assert "goviral.ai" in body
    assert "raw_text" in body


def test_generate_full_flow_creates_project(client):
    response = client.post("/generate", data={
        "raw_text": (
            "5 dicas matinais para começar o dia com energia. "
            "Beba água, faça exercício, escreva prioridades, "
            "evite redes sociais, tome café da manhã."
        ),
        "theme": "rotina matinal",
        "language": "pt-BR",
        "style": "list",
        "slides_count": "6",
        "keywords-0": "foco",
        "keywords-1": "habitos",
    }, follow_redirects=False)
    assert response.status_code in (301, 302)
    location = response.headers.get("Location", "")
    assert "/preview/" in location


def test_generate_invalid_returns_422(client):
    response = client.post("/generate", data={
        "raw_text": "curto",
        "theme": "",
        "language": "",
        "style": "",
        "slides_count": "",
    })
    assert response.status_code == 422


def test_preview_unknown_project_returns_404(client):
    response = client.get("/preview/does-not-exist")
    assert response.status_code == 404


def test_full_flow_with_preview_and_export(client):
    # 1. Generate
    response = client.post("/generate", data={
        "raw_text": (
            "Tutorial completo de como preparar um café latte em casa. "
            "Primeiro aqueça o leite. Depois prepare o espresso. "
            "Misture e adicione espuma. Finalize com canela. "
            "Aproveite sua manhã!"
        ),
        "theme": "café latte",
        "language": "pt-BR",
        "style": "tutorial",
        "slides_count": "3",
        "keywords-0": "latte",
    }, follow_redirects=True)
    assert response.status_code == 200

    html = response.data.decode("utf-8")
    match = re.search(r"/preview/([a-f0-9]{12})", html)
    assert match, "Project ID não encontrado na página"
    project_id = match.group(1)

    # 2. Preview
    response = client.get(f"/preview/{project_id}")
    assert response.status_code == 200
    assert "Carrossel" in response.data.decode("utf-8")

    # 3. Export ZIP — todos os slides como PNG
    response = client.post(f"/preview/{project_id}/export", data={"format": "zip"})
    assert response.status_code == 200
    assert response.mimetype == "application/zip"
    zf = zipfile.ZipFile(io.BytesIO(response.data))
    names = zf.namelist()
    # Deve conter 3 PNGs + 1 MD
    assert sum(1 for n in names if n.endswith(".png")) == 3
    assert any(n.endswith(".md") for n in names)
    # Markdown deve conter a headline do primeiro slide
    md_content = next(zf.read(n) for n in names if n.endswith(".md")).decode("utf-8")
    assert "Slide" in md_content

    # 4. Export PNG único (slide 1)
    response = client.post(f"/preview/{project_id}/export", data={"format": "png"})
    assert response.status_code == 200
    assert response.mimetype == "image/png"
    assert len(response.data) > 5000  # PNG não-trivial

    # 5. Export Markdown
    response = client.post(f"/preview/{project_id}/export", data={"format": "md"})
    assert response.status_code == 200
    assert response.mimetype == "text/markdown"
    body = response.data.decode("utf-8")
    assert "Carrossel" in body


def test_rank_endpoint_returns_json(client):
    response = client.post("/generate", data={
        "raw_text": "Texto longo o suficiente para passar na validação do campo raw_text.",
        "theme": "teste ranking",
        "language": "pt-BR",
        "style": "quote",
        "slides_count": "3",
    }, follow_redirects=True)
    html = response.data.decode("utf-8")
    match = re.search(r"/preview/([a-f0-9]{12})", html)
    assert match
    project_id = match.group(1)

    response = client.post(
        "/rank",
        json={"project_id": project_id},
        content_type="application/json",
    )
    assert response.status_code == 200
    data = response.get_json()
    assert "results" in data


def test_health_html_reports_unsplash_not_mock(monkeypatch):
    """O painel /health/html mostrava 'mock' para imagens sempre que o Pinterest
    não estava configurado — mesmo com o Unsplash respondendo 200. Era o
    diagnóstico que fazia parecer que o carrossel saía em mock."""
    monkeypatch.setenv("UNSPLASH_ACCESS_KEY", "chave-real")
    app = create_app()
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as client:
        body = client.get("/health/html").get_data(as_text=True)

    assert "<th>Imagens</th><td><code>unsplash</code>" in body
    # A linha do Pinterest sumiu — era ela que dizia "mock" com o Unsplash ativo.
    assert "<th>Pinterest</th>" not in body
