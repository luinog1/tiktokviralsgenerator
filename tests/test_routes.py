"""Testes de rotas — fluxo de geração de carrossel em modo mock."""

from __future__ import annotations

import io
import json
import re
import zipfile

import pytest

from app.main import create_app
from app.config import Settings
from app.services.session_store import get_store, reset_store


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
    assert data["providers"]["goviralai"] == "optional_import"
    assert data["providers"]["content_generation"] == "not_configured"


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
    # Os dois caminhos de entrada: colar o painel (atalho) e o briefing completo.
    assert "Gerar hook e scripts" in body
    assert "Briefing completo" in body


def test_create_form_renders(client):
    response = client.get("/create")
    assert response.status_code == 200
    body = response.data.decode("utf-8")
    assert "Briefing do carrossel" in body
    assert "goviral.ai" in body
    assert "raw_text" in body
    assert "person_images_count" in body
    assert "food_images_count" in body


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


def test_labelled_paste_reaches_the_preview_exactly_as_written(client):
    """O caminho que o usuário usa: colar na caixa única, com os rótulos.

    O texto colado indica a imagem de cada trecho, então o composer é pulado —
    o que chega na prévia é o que foi escrito, sem o rótulo e com a imagem 1
    numa caixa só.
    """
    response = client.post("/generate", data={
        "raw_text": (
            "Imagem 1 (hook): ninguém acorda às 5h por disciplina\n"
            "\n"
            "Imagem 2: acorda porque dormiu às 21h\n"
            "\n"
            "ninguém fala essa parte\n"
            "\n"
            "Imagem 3: salva pra começar amanhã"
        ),
        "theme": "rotina matinal",
        "language": "pt-BR",
        "style": "sticker",
        "slides_count": "6",
    }, follow_redirects=True)

    body = response.data.decode("utf-8")
    assert response.status_code == 200
    assert "ninguém acorda às 5h por disciplina" in body
    assert "ninguém fala essa parte" in body
    # O rótulo é orientação para a montagem — nunca texto do slide.
    assert "Imagem 1 (hook)" not in body
    assert "Imagem 2:" not in body


def test_preview_unknown_project_returns_404(client):
    response = client.get("/preview/does-not-exist")
    assert response.status_code == 404


def test_preview_gallery_only_offers_images_from_the_slide_category(client):
    images = [
        {
            "image_id": image_id,
            "image_url": f"https://img/{image_id}.jpg",
            "source_url": "https://source",
            "title": image_id,
            "description": "",
            "attribution_text": "Teste",
            "pool": category,
        }
        for image_id, category in [
            ("person-1", "hook"),
            ("food-1", "food"),
            ("scene-1", "scene"),
            ("scene-2", "scene"),
        ]
    ]
    slides = [
        {
            "headline": "Hook",
            "role": "hook",
            "image_id": "person-1",
            "image_category": "person",
            "image_options": ["person-1"],
        },
        {
            "headline": "Comida",
            "role": "value",
            "image_id": "food-1",
            "image_category": "food",
            "image_options": ["food-1"],
        },
        {
            "headline": "Cena",
            "role": "cta",
            "image_id": "scene-1",
            "image_category": "scene",
            "image_options": ["scene-1", "scene-2"],
        },
    ]
    project = get_store().create(
        briefing={"theme": "teste"},
        carousel={"slides": slides, "hashtags": [], "caption": ""},
        images=images,
        ranking=[
            {"image_id": "person-1", "score": 0.9, "subject": "woman"},
            {"image_id": "food-1", "score": 0.8, "subject": "food"},
            {"image_id": "scene-1", "score": 0.7, "subject": "scene"},
        ],
        style="quote",
        slides_count=3,
        raw_text="teste",
    )

    body = client.get(f"/preview/{project.project_id}").get_data(as_text=True)
    gallery = re.search(
        r'<div class="mini-gallery" data-slide="2">(.*?)</div>', body, re.S
    ).group(1)

    assert 'data-image-id="scene-1"' in gallery
    assert 'data-image-id="scene-2"' in gallery
    assert 'data-image-id="person-1"' not in gallery
    assert 'data-image-id="food-1"' not in gallery
    assert "comida/bebida" in body


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
    assert "metadata.json" in names
    metadata = json.loads(zf.read("metadata.json"))
    assert metadata["canvas"] == {
        "width": 1080,
        "height": 1350,
        "format": "PNG",
        "compression": "lossless",
    }
    assert len(metadata["slides"]) == 3
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
    monkeypatch.setenv("IMAGE_PROVIDER", "auto")
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


# --------------------------------- painel do goviral: colar inteiro e gerar
GOVIRAL_PANEL = (
    "Content Dashboard\n"
    "Last updated: 6/25/2026, 2:35:03 PM\n"
    "Hook\n"
    "i regret posting consistently and here is why...\n"
    "Scripts\n"
    "Script 1\n"
    "Position 1\n"
    "Paragraph 1:\n"
    "i was consistent, but i was still guessing.\n"
    "Paragraph 2:\n"
    "i posted every day with no plan and no clear promise.\n"
    "Script 2\n"
    "Position 2\n"
    "Paragraph 1:\n"
    "the quiet phase fooled me into panic changes.\n"
    "Paragraph 2:\n"
    "i switched topics and styles instead of stacking signals.\n"
)


def test_goviral_page_renders(client):
    body = client.get("/goviral").data.decode("utf-8")
    assert "Gerador de hooks e scripts" in body
    assert "content-brief" in body
    assert "raw_text" in body
    assert "person_images_count" in body
    assert "food_images_count" in body
    assert "instagram_images_count" in body


def test_goviral_panel_generates_the_carousel_without_asking_slide_count(client):
    """O fluxo inteiro da ferramenta: colar o painel e gerar. O nº de imagens
    vem do painel (hook + 2 scripts = 3), e o texto chega à prévia como
    escrito — hook numa caixa só, parágrafos nas duas caixas."""
    response = client.post("/goviral", data={
        "raw_text": GOVIRAL_PANEL,
        "theme": "consistência",
        "style": "sticker",
    }, follow_redirects=True)

    assert response.status_code == 200
    body = response.data.decode("utf-8")
    assert "i regret posting consistently and here is why..." in body
    assert "i was consistent, but i was still guessing." in body
    assert "the quiet phase fooled me into panic changes." in body
    # Os rótulos do painel são orientação — nunca texto de slide.
    assert "Paragraph 1" not in body
    assert "Position 1" not in body
    # 3 imagens: os campos da prévia param no índice 2.
    assert "text_positions-2" in body
    assert "text_positions-3" not in body


def test_goviral_visual_quotas_are_saved_with_the_project(client):
    response = client.post("/goviral", data={
        "raw_text": GOVIRAL_PANEL,
        "theme": "smoothie de frutas",
        "style": "sticker",
        "person_images_count": "1",
        "food_images_count": "1",
    })

    project_id = response.headers["Location"].rsplit("/", 1)[-1]
    project = get_store().get(project_id)
    assert project is not None
    assert project.briefing["person_images_count"] == 1
    assert project.briefing["food_images_count"] == 1


def test_goviral_rejects_text_that_is_not_the_panel(client):
    response = client.post("/goviral", data={
        "raw_text": "um texto qualquer, sem os rótulos do painel do goviral",
        "style": "sticker",
    })
    assert response.status_code == 422
    assert "Não reconheci o painel" in response.data.decode("utf-8")


def test_goviral_parse_endpoint_previews_the_distribution(client):
    response = client.post("/goviral/parse", json={"raw_text": GOVIRAL_PANEL})
    data = response.get_json()

    assert response.status_code == 200
    assert data["recognized"] is True
    assert data["hook"] == "i regret posting consistently and here is why..."
    assert len(data["blocks"]) == 3
    assert data["blocks"][1] == (
        "i was consistent, but i was still guessing."
        "\n\n"
        "i posted every day with no plan and no clear promise."
    )


def test_goviral_parse_endpoint_says_when_it_is_not_a_panel(client):
    response = client.post("/goviral/parse", json={"raw_text": "texto corrido"})
    data = response.get_json()

    assert data["recognized"] is False
    assert data["blocks"] == []


def test_script_split_recognizes_the_goviral_panel(client):
    """O botão "distribuir" do briefing completo também entende o painel: cada
    script vira um campo, com a linha em branco separando as duas caixas."""
    response = client.post("/script/split", json={
        "raw_text": GOVIRAL_PANEL,
        "slides_count": "6",
    })
    data = response.get_json()

    assert data["source"] == "goviral"
    assert data["found"] == 3
    assert data["blocks"][0] == "i regret posting consistently and here is why..."
    assert "\n\n" in data["blocks"][1]


def test_generate_with_pasted_panel_in_raw_text_skips_the_llm(client):
    """O painel colado na caixa única do modo automático: mesma regra dos
    rótulos `Imagem N:` — composição determinística, sem composer no meio."""
    response = client.post("/generate", data={
        "raw_text": GOVIRAL_PANEL,
        "theme": "consistência",
        "language": "pt-BR",
        "style": "sticker",
        "slides_count": "6",
    }, follow_redirects=True)

    assert response.status_code == 200
    body = response.data.decode("utf-8")
    assert "Painel do goviral reconhecido" in body
    # Sem aviso de composer mock: o composer não rodou.
    assert "Composição em modo mock" not in body
    assert "i was consistent, but i was still guessing." in body


# ---------- proxy de imagem do Instagram (CORP) ----------


def test_image_proxy_serves_instagram_cdn_bytes(client, monkeypatch):
    """O CDN do Instagram manda Cross-Origin-Resource-Policy: same-origin — o
    navegador baixa a foto e a DESCARTA na checagem de CORP (thumb branco com
    o alt escrito). A prévia pede ao app, que busca do lado do servidor."""
    fetched = []

    class _Upstream:
        status_code = 200
        content = b"\xff\xd8jpeg-fake"
        headers = {"Content-Type": "image/jpeg"}

    def _get(url, **kwargs):
        fetched.append(url)
        return _Upstream()

    monkeypatch.setattr("app.routes.preview.requests.get", _get)
    url = "https://scontent-waw2-1.cdninstagram.com/v/t51/foto.jpg?oe=abc"
    response = client.get("/image-proxy", query_string={"u": url})

    assert response.status_code == 200
    assert response.data == b"\xff\xd8jpeg-fake"
    assert response.headers["Content-Type"].startswith("image/jpeg")
    assert "max-age" in response.headers.get("Cache-Control", "")
    assert fetched == [url]


def test_image_proxy_accepts_the_fbcdn_profile_variant(client, monkeypatch):
    """O caminho @perfil devolve hosts instagram.f<região>.fna.fbcdn.net — o
    mesmo CDN com outro domínio, e o mesmo header de CORP."""

    class _Upstream:
        status_code = 200
        content = b"ok"
        headers = {"Content-Type": "image/jpeg"}

    monkeypatch.setattr(
        "app.routes.preview.requests.get", lambda *a, **k: _Upstream()
    )
    response = client.get("/image-proxy", query_string={
        "u": "https://instagram.fmex19-1.fna.fbcdn.net/v/t51/foto.jpg"
    })
    assert response.status_code == 200


def test_image_proxy_refuses_anything_that_is_not_the_instagram_cdn(
    client, monkeypatch
):
    """Sem a lista fechada de hosts, o proxy seria um SSRF de brinde."""
    calls = []
    monkeypatch.setattr(
        "app.routes.preview.requests.get",
        lambda *a, **k: calls.append(a),
    )
    for bad in (
        "https://evil.com/x.jpg",
        "https://cdninstagram.com.evil.com/x.jpg",
        "http://scontent.cdninstagram.com/x.jpg",
        "https://i.pinimg.com/originals/a.jpg",
        "",
    ):
        response = client.get("/image-proxy", query_string={"u": bad})
        assert response.status_code == 404, bad
    assert client.get("/image-proxy").status_code == 404
    assert calls == []


def test_image_proxy_maps_upstream_failures_to_502(client, monkeypatch):
    """URL assinada expirada (403 do CDN) ou rede fora — o thumb quebra só
    quando a foto está morta mesmo, sem virar 500 na prévia."""
    import requests as _requests

    class _Dead:
        status_code = 403
        content = b""
        headers = {}

    monkeypatch.setattr("app.routes.preview.requests.get", lambda *a, **k: _Dead())
    url = "https://scontent.cdninstagram.com/v/morta.jpg"
    assert client.get("/image-proxy", query_string={"u": url}).status_code == 502

    def _timeout(*a, **k):
        raise _requests.Timeout()

    monkeypatch.setattr("app.routes.preview.requests.get", _timeout)
    assert client.get("/image-proxy", query_string={"u": url}).status_code == 502


def test_browser_src_proxies_instagram_and_leaves_the_rest_alone(app):
    from urllib.parse import parse_qs, urlsplit

    from app.routes.preview import browser_src

    with app.test_request_context("/"):
        original = "https://instagram.fmex19-1.fna.fbcdn.net/v/x.jpg?a=1&b=2"
        proxied = browser_src(original)
        assert proxied.startswith("/image-proxy?u=")
        # O que importa é o round-trip: o `u` decodificado é a URL original,
        # com a query interna (a=1&b=2) intacta.
        assert parse_qs(urlsplit(proxied).query)["u"][0] == original
        # As outras fontes não mandam o header de CORP: passam intactas.
        pin = "https://i.pinimg.com/originals/x.jpg"
        assert browser_src(pin) == pin
        assert browser_src("data:image/svg+xml;utf8,<svg/>").startswith("data:")
        assert browser_src("") == ""


def test_preview_page_sends_instagram_images_through_the_proxy(client):
    """Integração: com uma foto do Instagram no projeto, a prévia inteira
    (galeria e fundo do slide) aponta para o proxy — nenhum src direto do
    CDN sobra para o navegador bloquear."""
    response = client.post("/generate", data={
        "raw_text": (
            "Texto de teste com tamanho suficiente para o formulário. "
            "Uma frase a mais para garantir a validação."
        ),
        "theme": "rotina matinal",
        "language": "pt-BR",
        "style": "sticker",
        "slides_count": "3",
    }, follow_redirects=False)
    project_id = response.headers["Location"].rstrip("/").split("/")[-1]

    project = get_store().get(project_id)
    project.images[0]["image_url"] = (
        "https://scontent-waw2-1.cdninstagram.com/v/t51/foto.jpg"
    )
    project.images[0]["thumb_url"] = ""

    body = client.get(f"/preview/{project_id}").data.decode("utf-8")
    assert "/image-proxy?u=https://scontent-waw2-1.cdninstagram.com" in body
    assert 'src="https://scontent' not in body
    assert "background-image: url('https://scontent" not in body


# ---------- busca on-spot: mais fotos do mesmo @, direto da prévia ----------


def _hook_project(options=("person-1",)):
    """Um projeto pronto na prévia, com a imagem 1 no papel de hook."""
    images = [{
        "image_id": "person-1",
        "image_url": "https://img/person-1.jpg",
        "source_url": "https://source",
        "title": "retrato",
        "description": "",
        "attribution_text": "Teste",
        "pool": "hook",
    }]
    slides = [
        {
            "headline": "Hook",
            "role": "hook",
            "image_id": "person-1",
            "image_category": "person",
            "image_options": list(options),
        },
        {
            "headline": "Cena",
            "role": "cta",
            "image_id": "person-1",
            "image_category": "scene",
            "image_options": ["person-1"],
        },
    ]
    return get_store().create(
        briefing={"theme": "teste"},
        carousel={"slides": slides, "hashtags": [], "caption": ""},
        images=images,
        ranking=[],
        style="quote",
        slides_count=2,
        raw_text="teste",
    )


def _found(*ids):
    from app.adapters.pinterest_client import PinterestImage

    return [
        PinterestImage(
            image_id=image_id,
            image_url=f"https://img/{image_id}.jpg",
            source_url="https://source",
            title=image_id,
        )
        for image_id in ids
    ]


def test_the_on_spot_search_adds_the_photos_to_the_hook_gallery(client, monkeypatch):
    project = _hook_project()
    monkeypatch.setattr(
        "app.routes.preview.search_by_handle",
        lambda *a, **k: (_found("ig-1", "ig-2"), "instagram", ""),
    )

    response = client.post(
        f"/preview/{project.project_id}/hook-alternatives",
        json={"handle": "@bellebres"},
    )

    data = response.get_json()
    assert data["ok"] is True
    assert data["source"] == "instagram"
    assert [img["image_id"] for img in data["images"]] == ["ig-1", "ig-2"]

    stored = get_store().get(project.project_id)
    assert [img["image_id"] for img in stored.images] == ["person-1", "ig-1", "ig-2"]


def test_the_new_photos_land_in_the_canonical_image_options(client, monkeypatch):
    """`to_edited_slides` valida a foto escolhida contra o `image_options` do
    `carousel` e devolve a antiga quando ela não está lá.

    Se a alternativa nova só existisse na tela, escolher e salvar descartaria a
    escolha em silêncio — o usuário veria a foto voltar sozinha.
    """
    project = _hook_project()
    monkeypatch.setattr(
        "app.routes.preview.search_by_handle",
        lambda *a, **k: (_found("ig-1"), "instagram", ""),
    )

    client.post(
        f"/preview/{project.project_id}/hook-alternatives",
        json={"handle": "bellebres"},
    )

    stored = get_store().get(project.project_id)
    assert stored.carousel["slides"][0]["image_options"] == ["person-1", "ig-1"]


def test_a_photo_found_on_the_spot_survives_saving_the_edit(client, monkeypatch):
    """A prova de ponta a ponta: buscar, escolher a nova e salvar."""
    project = _hook_project()
    monkeypatch.setattr(
        "app.routes.preview.search_by_handle",
        lambda *a, **k: (_found("ig-1"), "instagram", ""),
    )
    client.post(
        f"/preview/{project.project_id}/hook-alternatives",
        json={"handle": "bellebres"},
    )

    client.post(
        f"/preview/{project.project_id}/edit",
        data={
            "headlines-0": "Hook", "headlines-1": "Cena",
            "bodies-0": "", "bodies-1": "corpo",
            "ctas-0": "", "ctas-1": "cta",
            "selected_image_ids-0": "ig-1",
            "selected_image_ids-1": "person-1",
            "text_positions-0": "", "text_positions-1": "",
            "box_positions-0": "", "box_positions-1": "",
            "box_scales-0": "", "box_scales-1": "",
        },
    )

    stored = get_store().get(project.project_id)
    assert stored.edited_slides[0]["image_id"] == "ig-1"


def test_the_on_spot_search_explains_itself_when_it_finds_nothing(client, monkeypatch):
    project = _hook_project()
    monkeypatch.setattr(
        "app.routes.preview.search_by_handle",
        lambda *a, **k: ([], "", "Sem APIFY_TOKEN, o Instagram não responde por perfil."),
    )

    response = client.post(
        f"/preview/{project.project_id}/hook-alternatives",
        json={"handle": "bellebres"},
    )

    data = response.get_json()
    assert data["ok"] is False
    assert "APIFY_TOKEN" in data["reason"]


def test_the_on_spot_search_needs_a_handle(client):
    project = _hook_project()

    response = client.post(
        f"/preview/{project.project_id}/hook-alternatives", json={"handle": "  @  "}
    )

    assert response.status_code == 400
    assert response.get_json()["ok"] is False


def test_the_on_spot_search_on_an_expired_project_says_so(client):
    response = client.post(
        "/preview/does-not-exist/hook-alternatives", json={"handle": "bellebres"}
    )

    assert response.status_code == 404


def test_an_instagram_photo_comes_back_already_proxied(client, monkeypatch):
    """O CDN do Instagram manda `Cross-Origin-Resource-Policy: same-origin`.

    A URL responde, mas o navegador recusa pintar a imagem na prévia — a foto
    sai branca com a URL viva, que é o jeito mais confuso possível de falhar.
    O Instagram é a fonte principal desta busca, então a resposta já sai
    apontando para o `/image-proxy`.
    """
    project = _hook_project()
    from app.adapters.pinterest_client import PinterestImage

    monkeypatch.setattr(
        "app.routes.preview.search_by_handle",
        lambda *a, **k: (
            [PinterestImage(
                image_id="ig-1",
                image_url="https://scontent-lhr8-1.cdninstagram.com/v/t51.jpg",
                source_url="https://instagram.com/p/x",
                title="post",
            )],
            "instagram",
            "",
        ),
    )

    response = client.post(
        f"/preview/{project.project_id}/hook-alternatives",
        json={"handle": "bellebres"},
    )

    url = response.get_json()["images"][0]["url"]
    assert url.startswith("/image-proxy?u=")
