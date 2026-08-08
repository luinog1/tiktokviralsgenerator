"""Formulário de briefing — usuário cola o texto do goviral.ai."""

from __future__ import annotations

from flask import Blueprint, current_app, render_template

from app.forms import BriefingForm

bp = Blueprint("create", __name__)


@bp.route("/create", methods=["GET"])
def create():
    form = BriefingForm()
    # Garantir pelo menos 3 campos de palavras-chave vazios na primeira renderização
    while len(form.keywords.entries) < 3:
        form.keywords.append_entry()
    settings = current_app.config["SETTINGS"]
    return render_template(
        "create.html",
        form=form,
        ranking_enabled=settings.ranking_enabled,
        goviral_url="https://content.goviralai.app/",
    )
