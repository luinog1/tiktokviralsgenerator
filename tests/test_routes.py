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


# --------------------------------- modo roteiro: um bloco por imagem, na ordem
def test_create_form_renders_the_script_section(client):
    body = client.get("/create").data.decode("utf-8")
    assert "slide_scripts-0" in body
    assert "script_mode" in body
    assert "Imagem 1" in body


def test_script_mode_keeps_the_text_and_the_order_through_the_preview(client):
    response = client.post("/generate", data={
        "script_mode": "script",
        "theme": "rotina matinal",
        "language": "pt-BR",
        "style": "sticker",
        "slides_count": "3",
        "slide_scripts-0": "ninguém acorda às 5h por disciplina",
        "slide_scripts-1": "acorda porque dormiu às 21h",
        "slide_scripts-2": "salva pra tentar amanhã",
    }, follow_redirects=True)

    assert response.status_code == 200
    body = response.data.decode("utf-8")
    hook = body.index("ninguém acorda às 5h por disciplina")
    middle = body.index("acorda porque dormiu às 21h")
    cta = body.index("salva pra tentar amanhã")
    assert hook < middle < cta


def test_script_mode_still_positions_and_casts(client):
    """O modo roteiro só troca de onde vem o texto: reposicionamento e escolha
    de imagem por slide continuam valendo."""
    response = client.post("/generate", data={
        "script_mode": "script",
        "theme": "café",
        "language": "pt-BR",
        "style": "sticker",
        "slides_count": "3",
        "slide_scripts-0": "o segredo do café",
        "slide_scripts-1": "salva esse post",
    }, follow_redirects=True)

    body = response.data.decode("utf-8")
    assert "text_positions-0" in body
    assert "selected_image_ids-0" in body
    # 2 blocos preenchidos de 3 possíveis = carrossel de 2 imagens.
    assert "text_positions-2" not in body


def test_the_sticker_preview_paints_the_letters_in_a_second_layer(client):
    """A frase sai duas vezes por caixa: etiquetas embaixo, letras em cima.

    As etiquetas brancas se sobrepõem de propósito, e o navegador pinta uma
    linha inteira (fundo e texto) antes da seguinte — o fundo da linha de baixo
    comia o rabo dos "g" da linha de cima. A prévia faz o mesmo que o Pillow em
    `_draw_sticker_block`: uma passada de caixas, outra de texto.
    """
    response = client.post("/generate", data={
        "script_mode": "script",
        "theme": "rotina",
        "language": "pt-BR",
        "style": "sticker",
        "slides_count": "3",
        "slide_scripts-0": "engaging does not mean paging",
        "slide_scripts-1": "reposting helps you",
    }, follow_redirects=True)

    body = response.data.decode("utf-8")
    assert body.count("engaging does not mean paging") >= 2, (
        "a camada de tinta precisa repetir o texto da etiqueta"
    )
    assert 'class="sticker-ink-layer"' in body
    # Frase repetida no DOM não pode ser lida duas vezes pelo leitor de tela.
    assert 'class="sticker-ink-layer" aria-hidden="true"' in body


def test_other_styles_have_no_second_layer(client):
    """Só o sticker pinta etiqueta por linha — o resto não tem o que corrigir."""
    response = client.post("/generate", data={
        "raw_text": (
            "Tutorial completo de café latte em casa. Aqueça o leite. "
            "Prepare o espresso. Misture e finalize com canela."
        ),
        "theme": "café",
        "language": "pt-BR",
        "style": "tutorial",
        "slides_count": "3",
    }, follow_redirects=True)

    # O comentário do script cita a classe; o que não pode existir é a marcação.
    assert 'class="sticker-ink-layer"' not in response.data.decode("utf-8")


def test_script_mode_without_blocks_returns_422(client):
    response = client.post("/generate", data={
        "script_mode": "script",
        "theme": "café",
        "language": "pt-BR",
        "style": "sticker",
        "slides_count": "3",
        "slide_scripts-0": "só um bloco",
    })
    assert response.status_code == 422


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


def test_text_position_survives_edit_and_changes_the_png(client):
    """O arraste na prévia só serve se sobreviver ao POST /edit e chegar no PNG
    exportado — senão é enfeite de tela."""
    response = client.post("/generate", data={
        "raw_text": (
            "Você posta todo dia e não cresce. O problema não é o algoritmo. "
            "Salva esse post para aplicar hoje mesmo."
        ),
        "theme": "crescimento",
        "language": "pt-BR",
        "style": "sticker",
        "slides_count": "3",
    }, follow_redirects=True)
    project_id = re.search(r"/preview/([a-f0-9]{12})", response.get_data(as_text=True)).group(1)

    before = client.post(f"/preview/{project_id}/export", data={"format": "png"}).data

    payload = {"project_id": project_id}
    for i in range(3):
        payload[f"headlines-{i}"] = "frase fixa para comparar o png"
        payload[f"text_positions-{i}"] = "0.5,0.2"
    response = client.post(
        f"/preview/{project_id}/edit", data=payload, follow_redirects=True
    )
    assert response.status_code == 200
    # A prévia devolve o hidden preenchido, senão o arraste se perde no reload.
    assert 'value="0.5,0.2"' in response.get_data(as_text=True)

    after = client.post(f"/preview/{project_id}/export", data={"format": "png"}).data
    assert after != before, "a posição salva não mudou o PNG exportado"


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


# ------------------------------- POST /script/split — colar tudo e distribuir
def test_split_distributes_a_labelled_script(client):
    response = client.post("/script/split", json={
        "raw_text": "Imagem 1: o hook\nImagem 2: o meio\nImagem 3: o fim",
        "slides_count": 6,
    })

    assert response.status_code == 200
    assert response.get_json()["blocks"] == ["o hook", "o meio", "o fim"]


def test_split_caps_at_the_requested_slide_count(client):
    """Distribuir 9 partes em 3 campos perderia texto em silêncio — o que
    sobrou é reportado para o usuário aumentar o nº de slides."""
    raw = "\n\n".join(f"parte {i}" for i in range(1, 10))
    data = client.post(
        "/script/split", json={"raw_text": raw, "slides_count": 3}
    ).get_json()

    assert len(data["blocks"]) == 3
    assert data["found"] == 9


def test_split_of_empty_text_returns_no_blocks(client):
    data = client.post("/script/split", json={"raw_text": "   "}).get_json()

    assert data["blocks"] == []
    assert data["found"] == 0


def test_split_ignores_a_bogus_slide_count(client):
    data = client.post("/script/split", json={
        "raw_text": "um\n\ndois", "slides_count": "abacaxi",
    }).get_json()

    assert data["blocks"] == ["um", "dois"]


def test_create_page_offers_the_paste_box(client):
    body = client.get("/create").get_data(as_text=True)

    assert "script-paste-input" in body
    assert "/script/split" in body


def test_the_preview_does_not_offer_body_and_cta_on_the_hook_slide(client):
    """A imagem 1 é uma caixa só. Oferecer os campos e depois ignorá-los na
    gravação seria pior que não oferecer."""
    response = client.post("/generate", data={
        "script_mode": "script",
        "theme": "rotina matinal",
        "language": "pt-BR",
        "style": "sticker",
        "slides_count": "3",
        "slide_scripts-0": "ninguém acorda às 5h por disciplina",
        "slide_scripts-1": "acorda porque dormiu às 21h\ne ninguém fala isso",
        "slide_scripts-2": "salva pra tentar amanhã",
    }, follow_redirects=True)

    body = response.data.decode("utf-8")
    hook_body = re.search(r'<textarea[^>]*name="bodies-0"[^>]*>', body)
    other_body = re.search(r'<textarea[^>]*name="bodies-1"[^>]*>', body)
    hook_cta = re.search(r'<input[^>]*name="ctas-0"[^>]*>', body)

    assert hook_body and "readonly" in hook_body.group(0)
    assert hook_cta and "readonly" in hook_cta.group(0)
    assert other_body and "readonly" not in other_body.group(0)


def test_the_hook_image_renders_a_single_box_end_to_end(client):
    """Duas linhas no campo da imagem 1 saem como uma frase só, sem virar
    headline + apoio."""
    response = client.post("/generate", data={
        "script_mode": "script",
        "theme": "rotina matinal",
        "language": "pt-BR",
        "style": "sticker",
        "slides_count": "3",
        "slide_scripts-0": "ninguém acorda às 5h por disciplina\nninguém fala essa parte",
        "slide_scripts-1": "comece pela hora de dormir",
    }, follow_redirects=True)

    body = response.data.decode("utf-8")
    assert (
        "ninguém acorda às 5h por disciplina ninguém fala essa parte" in body
    )
    # A caixa de apoio do hook fica vazia — o CSS :empty a esconde na prévia.
    hook_body = re.search(r'<textarea[^>]*name="bodies-0"[^>]*>\s*</textarea>', body)
    assert hook_body
