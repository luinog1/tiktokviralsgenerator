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
