"""POST /generate — executa o fluxo completo de composição de carrossel."""

from __future__ import annotations

import logging

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)

from app.forms import BriefingForm
from app.services.generation import GenerationService

bp = Blueprint("generate", __name__)
logger = logging.getLogger(__name__)


@bp.route("/generate", methods=["POST"])
def generate():
    form = BriefingForm()
    if not form.validate_on_submit():
        while len(form.keywords.entries) < 3:
            form.keywords.append_entry()
        for field_name, errors in form.errors.items():
            for err in errors:
                flash(f"{field_name}: {err}", "error")
        return render_template("create.html", form=form, ranking_enabled=True), 422

    briefing = form.to_briefing()
    settings = current_app.config["SETTINGS"]
    service = GenerationService(settings)

    try:
        outcome = service.run(
            raw_text=briefing["raw_text"],
            theme=briefing["theme"],
            niche=briefing["niche"],
            keywords=briefing["keywords"],
            style=briefing["style"],
            slides_count=briefing["slides_count"],
            language=briefing["language"],
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("Falha de geração: %s", type(exc).__name__)
        flash("Falha ao gerar carrossel. Tente novamente.", "error")
        return redirect(url_for("create.create"))

    for warning in outcome.warnings:
        flash(warning, "warning")

    return redirect(url_for("preview.preview", project_id=outcome.project_id))


@bp.route("/rank", methods=["POST"])
def rank():
    """Endpoint opcional — reordena imagens existentes via ranking."""
    from flask import jsonify

    payload = request.get_json(silent=True) or {}
    project_id = payload.get("project_id")
    if not project_id:
        abort(400, description="project_id ausente.")

    settings = current_app.config["SETTINGS"]
    service = GenerationService(settings)
    project = service.store().get(project_id)
    if not project:
        abort(404, description="Projeto não encontrado.")

    from app.adapters import PinterestImage
    images = [
        PinterestImage(
            image_id=img["image_id"],
            image_url=img["image_url"],
            source_url=img["source_url"],
            title=img.get("title", ""),
            description=img.get("description", ""),
            attribution_text=img.get("attribution_text", ""),
        )
        for img in project.images
    ]
    try:
        results = service._ranking.rank(project.briefing, images)  # noqa: SLF001
    except Exception as exc:
        logger.warning("Re-ranking falhou: %s", type(exc).__name__)
        results = []
    return jsonify({"results": [r.to_dict() for r in results]})
