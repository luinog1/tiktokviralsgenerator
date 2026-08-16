"""Testes dos formulários WTForms."""

from __future__ import annotations

import pytest
from flask import Flask

from app.forms import BriefingForm, SlideEditForm


@pytest.fixture
def app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = "test"
    app.config["WTF_CSRF_ENABLED"] = False
    return app


def test_briefing_validates_required_fields(app):
    raw_text = (
        "Este é um texto gerado pelo goviral.ai que o usuário colou manualmente. "
        "Deve ter pelo menos 20 caracteres para ser aceito."
    )
    with app.test_request_context("/", method="POST", data={
        "raw_text": raw_text,
        "theme": "rotina matinal",
        "language": "pt-BR",
        "style": "list",
        "slides_count": "6",
        "keywords-0": "foco",
    }):
        form = BriefingForm()
        assert form.validate_on_submit(), form.errors
        briefing = form.to_briefing()
        assert briefing["theme"] == "rotina matinal"
        assert briefing["raw_text"] == raw_text
        assert briefing["style"] == "list"
        assert briefing["slides_count"] == 6
        assert briefing["keywords"] == ["foco"]
        # Sem seletor no POST (cliente antigo), a fonte fica com o ambiente.
        assert briefing["image_source"] == ""
        assert briefing["instagram_images_count"] == 1


def test_briefing_carries_the_image_source_choice(app):
    with app.test_request_context("/", method="POST", data={
        "raw_text": "Texto válido com mais de vinte caracteres para passar.",
        "theme": "rotina matinal",
        "language": "pt-BR",
        "style": "sticker",
        "slides_count": "3",
        "script_mode": "auto",
        "image_source": "instagram_pinterest",
        "instagram_images_count": "2",
    }):
        form = BriefingForm()
        assert form.validate_on_submit(), form.errors
        assert form.to_briefing()["image_source"] == "instagram_pinterest"
        assert form.to_briefing()["instagram_images_count"] == 2


def test_instagram_count_never_exceeds_the_carousel_size(app):
    with app.test_request_context("/", method="POST", data={
        "raw_text": "Texto válido com mais de vinte caracteres para passar.",
        "theme": "rotina matinal @fulana",
        "language": "pt-BR",
        "style": "sticker",
        "slides_count": "3",
        "script_mode": "auto",
        "image_source": "instagram_pinterest",
        "instagram_images_count": "12",
    }):
        form = BriefingForm()
        assert form.validate_on_submit(), form.errors
        assert form.to_briefing()["instagram_images_count"] == 3


def test_briefing_rejects_an_unknown_instagram_count(app):
    with app.test_request_context("/", method="POST", data={
        "raw_text": "Texto válido com mais de vinte caracteres para passar.",
        "theme": "rotina matinal",
        "language": "pt-BR",
        "style": "sticker",
        "slides_count": "3",
        "script_mode": "auto",
        "instagram_images_count": "99",
    }):
        form = BriefingForm()
        assert not form.validate_on_submit()
        assert "instagram_images_count" in form.errors


def test_briefing_accepts_the_unsplash_pinterest_source(app):
    with app.test_request_context("/", method="POST", data={
        "raw_text": "Texto válido com mais de vinte caracteres para passar.",
        "theme": "rotina matinal",
        "language": "pt-BR",
        "style": "sticker",
        "slides_count": "3",
        "script_mode": "auto",
        "image_source": "unsplash_pinterest",
    }):
        form = BriefingForm()
        assert form.validate_on_submit(), form.errors
        assert form.to_briefing()["image_source"] == "unsplash_pinterest"


def test_briefing_rejects_an_unknown_image_source(app):
    with app.test_request_context("/", method="POST", data={
        "raw_text": "Texto válido com mais de vinte caracteres para passar.",
        "theme": "rotina matinal",
        "language": "pt-BR",
        "style": "sticker",
        "slides_count": "3",
        "script_mode": "auto",
        "image_source": "orkut",
    }):
        form = BriefingForm()
        assert not form.validate_on_submit()
        assert "image_source" in form.errors


def test_briefing_rejects_short_raw_text(app):
    with app.test_request_context("/", method="POST", data={
        "raw_text": "curto",  # < 20 chars
        "theme": "café",
        "language": "pt-BR",
        "style": "quote",
        "slides_count": "3",
    }):
        form = BriefingForm()
        assert not form.validate_on_submit()
        assert "raw_text" in form.errors


def test_briefing_rejects_empty_theme(app):
    with app.test_request_context("/", method="POST", data={
        "raw_text": "Texto válido com mais de vinte caracteres para passar.",
        "theme": "",
        "language": "pt-BR",
        "style": "quote",
        "slides_count": "3",
    }):
        form = BriefingForm()
        assert not form.validate_on_submit()
        assert "theme" in form.errors


def test_briefing_strips_empty_keywords(app):
    with app.test_request_context("/", method="POST", data={
        "raw_text": "Texto suficiente para validação do campo obrigatório.",
        "theme": "café",
        "language": "pt-BR",
        "style": "list",
        "slides_count": "6",
        "keywords-0": "latte",
        "keywords-1": "",
        "keywords-2": "manha",
    }):
        form = BriefingForm()
        assert form.validate_on_submit(), form.errors
        briefing = form.to_briefing()
        assert briefing["keywords"] == ["latte", "manha"]


def test_briefing_rejects_missing_style(app):
    with app.test_request_context("/", method="POST", data={
        "raw_text": "Texto suficiente para validação do campo obrigatório.",
        "theme": "café",
        "language": "pt-BR",
        "slides_count": "6",
    }):
        form = BriefingForm()
        assert not form.validate_on_submit()
        assert "style" in form.errors


def test_slide_edit_form_merges_with_original(app):
    """O SlideEditForm deve mesclar os campos editados com a estrutura original."""
    original_slides = [
        {"headline": "Original 1", "body": "Body 1", "call_to_action": "CTA 1", "image_id": "img-1"},
        {"headline": "Original 2", "body": "Body 2", "call_to_action": "CTA 2", "image_id": "img-2"},
    ]
    with app.test_request_context("/", method="POST", data={
        "project_id": "abc123",
        "headlines-0": "Editado 1",
        "headlines-1": "",
        "bodies-0": "Body editado 1",
        "bodies-1": "",
        "ctas-0": "Novo CTA",
        "ctas-1": "",
        "selected_image_ids-0": "img-2",
        "selected_image_ids-1": "img-1",
    }):
        form = SlideEditForm()
        # Pré-popular com entradas para cada slide original
        for _ in original_slides:
            form.headlines.append_entry("")
            form.bodies.append_entry("")
            form.ctas.append_entry("")
            form.selected_image_ids.append_entry("")
        assert form.validate_on_submit()
        edited = form.to_edited_slides(original_slides)
        assert len(edited) == 2
        assert edited[0]["headline"] == "Editado 1"
        assert edited[0]["body"] == "Body editado 1"
        assert edited[0]["call_to_action"] == "Novo CTA"
        assert edited[0]["image_id"] == "img-2"
        # Slide 2 ficou vazio — deve preservar o original
        assert edited[1]["headline"] == "Original 2"
        assert edited[1]["image_id"] == "img-1"


def test_slide_edit_form_reads_dragged_text_position(app):
    """O arraste na prévia chega como "x,y" no hidden e vira pos_x/pos_y."""
    original_slides = [{"headline": "Original", "role": "hook"}]
    with app.test_request_context("/", method="POST", data={
        "headlines-0": "Original",
        "text_positions-0": "0.42,0.8125",
    }):
        form = SlideEditForm()
        edited = form.to_edited_slides(original_slides)
        assert edited[0]["pos_x"] == 0.42
        assert edited[0]["pos_y"] == 0.8125


@pytest.mark.parametrize(
    "raw", ["", "0.5", "abc,0.5", "1.4,0.5", "-0.1,0.2", "0.5,0.5,0.5"]
)
def test_slide_edit_form_ignores_invalid_positions(app, raw):
    """Valor fora de 0..1 ou malformado volta à âncora do papel, não quebra."""
    original_slides = [{"headline": "Original", "role": "value"}]
    with app.test_request_context("/", method="POST", data={
        "headlines-0": "Original",
        "text_positions-0": raw,
    }):
        form = SlideEditForm()
        edited = form.to_edited_slides(original_slides)
        assert edited[0]["pos_x"] is None
        assert edited[0]["pos_y"] is None


def test_slide_edit_form_reads_per_box_positions(app):
    """Cada caixa arrasta sozinha: "headline:x,y;cta:x,y" vira um dict."""
    original_slides = [{"headline": "Original", "role": "value"}]
    with app.test_request_context("/", method="POST", data={
        "headlines-0": "Original",
        "box_positions-0": "headline:0.5,0.15;cta:0.4,0.9",
    }):
        form = SlideEditForm()
        edited = form.to_edited_slides(original_slides)
        assert edited[0]["box_positions"] == {
            "headline": [0.5, 0.15],
            "cta": [0.4, 0.9],
        }


def test_slide_edit_form_reads_per_box_scales(app):
    """O resize do editor chega como "headline:1.4" e é preservado."""
    original_slides = [{"headline": "Original", "role": "value"}]
    with app.test_request_context("/", method="POST", data={
        "headlines-0": "Original",
        "box_scales-0": "headline:1.4;body:0.8",
    }):
        form = SlideEditForm()
        edited = form.to_edited_slides(original_slides)
        assert edited[0]["box_scales"] == {"headline": 1.4, "body": 0.8}


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "headline",                # sem valor
        "headline:abc",            # não é número
        "headline:9",              # acima do teto
        "headline:0.1",            # abaixo do piso
        "rodape:1.4",              # chave que a prévia não desenha
    ],
)
def test_slide_edit_form_ignores_invalid_box_scales(app, raw):
    """O hidden é editável pelo cliente — lixo não pode virar fonte gigante."""
    original_slides = [{"headline": "Original", "role": "value"}]
    with app.test_request_context("/", method="POST", data={
        "headlines-0": "Original",
        "box_scales-0": raw,
    }):
        form = SlideEditForm()
        edited = form.to_edited_slides(original_slides)
        assert edited[0]["box_scales"] == {}


@pytest.mark.parametrize(
    "raw", ["headline:2,0.5", "headline:abc,0.2", "rodape:0.5,0.5", "headline:0.5"]
)
def test_slide_edit_form_ignores_invalid_box_positions(app, raw):
    original_slides = [{"headline": "Original", "role": "value"}]
    with app.test_request_context("/", method="POST", data={
        "headlines-0": "Original",
        "box_positions-0": raw,
    }):
        form = SlideEditForm()
        edited = form.to_edited_slides(original_slides)
        assert edited[0]["box_positions"] == {}


# ------------------------------------------- modo roteiro (um bloco por imagem)
def _script_post(app, **over):
    data = {
        "script_mode": "script",
        "theme": "rotina matinal",
        "language": "pt-BR",
        "style": "sticker",
        "slides_count": "3",
        "slide_scripts-0": "ninguém acorda às 5h por disciplina",
        "slide_scripts-1": "acorda porque dormiu às 21h",
        "slide_scripts-2": "comece pela hora de dormir",
    }
    data.update(over)
    return app.test_request_context("/", method="POST", data=data)


def test_script_mode_accepts_blocks_without_raw_text(app):
    """No modo roteiro o raw_text fica vazio de propósito — exigi-lo aqui
    obrigaria a colar o texto duas vezes."""
    with _script_post(app):
        form = BriefingForm()
        assert form.validate_on_submit(), form.errors
        briefing = form.to_briefing()
        assert briefing["script_mode"] == "script"
        assert briefing["script_blocks"] == [
            "ninguém acorda às 5h por disciplina",
            "acorda porque dormiu às 21h",
            "comece pela hora de dormir",
        ]


def test_script_mode_fills_raw_text_from_the_blocks(app):
    """A busca de imagens e o ranking usam raw_text como corpus do tema."""
    with _script_post(app):
        form = BriefingForm()
        assert form.validate_on_submit(), form.errors
        assert "acorda porque dormiu" in form.to_briefing()["raw_text"]


def test_script_mode_needs_at_least_two_images(app):
    with _script_post(app, **{"slide_scripts-1": "", "slide_scripts-2": ""}):
        form = BriefingForm()
        assert not form.validate_on_submit()
        assert "slide_scripts" in form.errors


def test_script_mode_drops_the_gaps_between_filled_blocks(app):
    with _script_post(app, **{"slide_scripts-1": "   "}):
        form = BriefingForm()
        assert form.validate_on_submit(), form.errors
        assert form.to_briefing()["script_blocks"] == [
            "ninguém acorda às 5h por disciplina",
            "comece pela hora de dormir",
        ]


def test_auto_mode_ignores_leftover_blocks(app):
    """Trocou para automático depois de escrever nos campos: a escolha
    explícita manda, senão o texto antigo reapareceria no carrossel."""
    with _script_post(app, script_mode="auto", raw_text="Texto colado do goviral com mais de vinte chars."):
        form = BriefingForm()
        assert form.validate_on_submit(), form.errors
        briefing = form.to_briefing()
        assert briefing["script_mode"] == "auto"
        assert briefing["script_blocks"] == []
        assert briefing["raw_text"].startswith("Texto colado")


def test_auto_mode_still_requires_raw_text(app):
    with _script_post(app, script_mode="auto", **{
        "slide_scripts-0": "", "slide_scripts-1": "", "slide_scripts-2": "",
    }):
        form = BriefingForm()
        assert not form.validate_on_submit()
        assert "raw_text" in form.errors


def test_legacy_post_without_the_mode_field_still_works(app):
    """Cliente que não conhece o campo novo continua válido: o modo é inferido
    do que veio preenchido."""
    with app.test_request_context("/", method="POST", data={
        "raw_text": "Texto colado do goviral.ai com mais de vinte caracteres.",
        "theme": "café",
        "language": "pt-BR",
        "style": "quote",
        "slides_count": "3",
    }):
        form = BriefingForm()
        assert form.validate_on_submit(), form.errors
        assert form.to_briefing()["script_mode"] == "auto"


# ---------- a regra do slide 1 sobrevive à edição na prévia ----------


def test_edit_keeps_the_hook_slide_as_a_single_box(app):
    """A prévia entrega apoio e CTA do hook em leitura apenas; um POST montado
    à mão não deveria conseguir devolver as caixas que a imagem 1 não tem."""
    original_slides = [
        {"headline": "o hook", "body": "", "call_to_action": "", "role": "hook"},
        {"headline": "o valor", "body": "o apoio", "call_to_action": "", "role": "value"},
    ]
    with app.test_request_context("/", method="POST", data={
        "project_id": "abc123",
        "headlines-0": "o hook editado",
        "headlines-1": "o valor",
        "bodies-0": "apoio injetado no hook",
        "bodies-1": "o apoio",
        "ctas-0": "cta injetado no hook",
        "ctas-1": "",
    }):
        form = SlideEditForm()
        for _ in original_slides:
            form.headlines.append_entry("")
            form.bodies.append_entry("")
            form.ctas.append_entry("")
        assert form.validate_on_submit(), form.errors
        edited = form.to_edited_slides(original_slides)

    assert edited[0]["headline"] == "o hook editado", "a frase do hook é editável"
    assert edited[0]["body"] == ""
    assert edited[0]["call_to_action"] == ""
    # Os outros slides continuam com as três caixas.
    assert edited[1]["body"] == "o apoio"


def test_a_long_hook_still_validates_in_the_preview(app):
    """A caixa única do hook cabe mais que uma headline comum — o limite do
    campo tem que acompanhar, senão a prévia reprova o que a geração produziu."""
    from app.adapters.text_composer import HOOK_TEXT_LIMIT

    long_hook = "palavra " * 22  # ~176 caracteres, acima do limite antigo (80)
    long_hook = long_hook[:HOOK_TEXT_LIMIT].strip()
    with app.test_request_context("/", method="POST", data={
        "project_id": "abc123",
        "headlines-0": long_hook,
    }):
        form = SlideEditForm()
        form.headlines.append_entry("")
        assert form.validate_on_submit(), form.errors
