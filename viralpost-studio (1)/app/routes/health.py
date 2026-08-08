"""Health check — não expõe segredos."""

from __future__ import annotations

from flask import Blueprint, current_app, jsonify, render_template

bp = Blueprint("health", __name__)


@bp.route("/health")
def health():
    settings = current_app.config["SETTINGS"]
    payload = {
        "status": "ok",
        "version": "0.3.0",
        "flask_env": settings.flask_env,
        "providers": {
            "composer": settings.llm_provider,
            "pinterest": "configured" if settings.pinterest_configured else "mock",
            "ranking": settings.llm_provider if settings.ranking_enabled else "disabled",
            "goviralai": "external_manual",
        },
        "carousel": {
            "slide_width": settings.slide_width,
            "slide_height": settings.slide_height,
        },
    }
    if current_app.config.get("DEBUG"):
        payload["debug"] = True
    return jsonify(payload)


@bp.route("/health/html")
def health_html():
    settings = current_app.config["SETTINGS"]
    return render_template("health.html", settings=settings)
