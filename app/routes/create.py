"""Formulário de briefing — roteiro por imagem ou texto colado do goviral.ai."""

from __future__ import annotations

from flask import Blueprint, current_app, jsonify, render_template, request

from app.adapters.goviral_parser import goviral_blocks
from app.adapters.script_parser import split_blocks
from app.forms import (
    MAX_SCRIPT_BLOCKS,
    SLIDES_CHOICES,
    BriefingForm,
    script_field_labels,
)
from app.services.pinned_person import load_pinned

bp = Blueprint("create", __name__)

# Rótulo de cada campo de roteiro para todos os tamanhos de carrossel. O JS troca
# os rótulos quando o usuário muda o nº de slides; sem isso ele teria que
# reimplementar `viral_script_roles` no navegador e as duas versões iam divergir.
def script_labels_by_count() -> dict[str, list[str]]:
    return {
        value: script_field_labels(int(value)) for value, _ in SLIDES_CHOICES
    }


def prepare_script_fields(form: BriefingForm, slides_count: int) -> None:
    """Garante um campo de roteiro por imagem, sem estourar o teto."""
    target = min(max(slides_count, 1), MAX_SCRIPT_BLOCKS)
    while len(form.slide_scripts.entries) < target:
        form.slide_scripts.append_entry()


def create_view_context(form: BriefingForm, settings) -> dict:
    """Contexto do create.html — reusado pelo 422 do POST /generate."""
    slides_count = int(form.slides_count.data or 6)
    return {
        "form": form,
        "ranking_enabled": settings.ranking_enabled,
        "hook_subject": settings.hook_subject,
        "casting_enabled": settings.casting_enabled,
        "script_labels": script_labels_by_count(),
        "current_labels": script_field_labels(slides_count),
        "goviral_url": "https://content.goviralai.app/",
        # Com pessoa fixada, o template mostra o checkbox de reusar a pessoa.
        "pinned_person": load_pinned(),
    }


@bp.route("/create", methods=["GET"])
def create():
    form = BriefingForm()
    # Garantir pelo menos 3 campos de palavras-chave vazios na primeira renderização
    while len(form.keywords.entries) < 3:
        form.keywords.append_entry()
    prepare_script_fields(form, int(form.slides_count.data or 6))
    settings = current_app.config["SETTINGS"]
    return render_template("create.html", **create_view_context(form, settings))


@bp.route("/script/split", methods=["POST"])
def script_split():
    """Divide um roteiro colado em blocos, um por imagem.

    O botão "distribuir" no formulário chama aqui em vez de refazer a divisão em
    JavaScript: `split_blocks` já entende "Imagem 2:", "3.", "---" e parágrafos,
    e duas implementações da mesma regra divergem na primeira correção.

    O painel do goviral é tentado primeiro porque ele é o formato mais
    específico: "Script 1 / Paragraph 1 / Paragraph 2" não casa com nenhum
    separador genérico, então cairia em "uma imagem por linha" — cada rótulo do
    painel viraria um slide.
    """
    payload = request.get_json(silent=True) or {}
    raw_text = str(payload.get("raw_text") or "")
    blocks = goviral_blocks(raw_text)
    source = "goviral" if blocks else "generic"
    if not blocks:
        blocks = split_blocks(raw_text)

    limit = MAX_SCRIPT_BLOCKS
    requested = payload.get("slides_count")
    if isinstance(requested, (int, str)) and str(requested).isdigit():
        limit = min(max(int(requested), 1), MAX_SCRIPT_BLOCKS)

    return jsonify({
        "blocks": blocks[:limit],
        "found": len(blocks),
        "source": source,
    })
