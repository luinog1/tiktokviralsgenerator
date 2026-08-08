"""Rotas raiz: landing + dashboard simples."""

from __future__ import annotations

from flask import Blueprint, current_app, render_template

bp = Blueprint("main", __name__)


@bp.route("/")
def index():
    settings = current_app.config["SETTINGS"]
    recent = []
    try:
        from app.services.generation import GenerationService
        svc = GenerationService(settings)
        recent = [
            {
                "project_id": p.project_id,
                "theme": p.briefing.get("theme", ""),
                "style": p.style,
                "slides_count": p.slides_count,
                "updated_at": p.updated_at,
            }
            for p in svc.store().list_recent(limit=5)
        ]
    except Exception:
        pass

    return render_template(
        "index.html",
        recent=recent,
        composer_provider=_safe_provider_name("composer"),
        pinterest_provider=_safe_provider_name("pinterest"),
        ranking_provider=_safe_provider_name("ranking"),
        goviral_url="https://content.goviralai.app/",
    )


def _safe_provider_name(kind: str) -> str:
    """Helper defensivo para exibir nome do provider na UI."""
    try:
        settings = current_app.config["SETTINGS"]
        from app.services.generation import GenerationService
        svc = GenerationService(settings)
        return {
            "composer": svc.composer_name,
            "pinterest": svc.pinterest_provider_name,
            "ranking": svc.ranking_provider_name,
        }.get(kind, "—")
    except Exception:
        return "—"
