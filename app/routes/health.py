"""Health check — não expõe segredos, mas mostra diagnóstico útil."""

from __future__ import annotations

import os

from flask import Blueprint, current_app, jsonify, render_template

from app.adapters import build_pinterest_client, pinterest_scrape_available

bp = Blueprint("health", __name__)


@bp.route("/health")
def health():
    settings = current_app.config["SETTINGS"]
    # Nome real do cliente de imagens: "pinterest_scrape" | "unsplash" |
    # "instagram_scrape" | "instagram_pinterest" | "unsplash_pinterest" |
    # "mock". Antes isso era derivado só de `pinterest_configured`, então uma
    # chave Unsplash válida ainda aparecia como "mock" aqui.
    images_provider = getattr(build_pinterest_client(settings), "name", "unknown")
    payload = {
        "status": "ok",
        "version": "0.3.1",
        "flask_env": settings.flask_env,
        "providers": {
            "composer": settings.llm_provider,
            "images": images_provider,
            "ranking": settings.llm_provider if settings.ranking_enabled else "disabled",
            "vision": "configured" if settings.vision_configured else "off",
            "casting": settings.hook_subject if settings.casting_enabled else "off",
            "content_generation": (
                "llm" if settings.llm_provider != "mock" and settings.llm_configured
                else "not_configured"
            ),
            "goviralai": "optional_import",
        },
        "carousel": {
            "slide_width": settings.slide_width,
            "slide_height": settings.slide_height,
        },
        # Diagnóstico de imagens — booleanos, NUNCA valores secretos
        "images_diagnostic": {
            "active_client": images_provider,
            "using_mock": images_provider == "mock",
            "image_provider_env": settings.image_provider,
            "unsplash_key_set": bool(os.environ.get("UNSPLASH_ACCESS_KEY", "").strip()),
            # `pinterest-dl` é dependência opcional: ausente, o cliente de
            # scraping existe mas só sabe cair no mock.
            "pinterest_scrape_installed": pinterest_scrape_available(),
            # Transportes do Instagram sem token — booleanos, nunca o token.
            # A Apify vence o Scrape.do quando os dois existem: ela raspa com
            # sessão própria, e é a única com chance na busca por hashtag (o
            # 302 do endpoint anônimo não é gate de IP — ver README v0.14).
            "apify_token_set": bool(settings.apify_token),
            "apify_actor_value": settings.apify_actor,
            "scrapedo_token_set": bool(settings.scrapedo_token),
        },
        # Diagnóstico LLM — booleanos, NUNCA valores secretos
        "llm_diagnostic": {
            "llm_provider_env": settings.llm_provider,
            "llm_api_base_url_set": bool(settings.llm_api_base_url),
            "llm_api_key_set": bool(settings.llm_api_key),
            "llm_model_set": bool(settings.llm_model),
            "llm_model_value": settings.llm_model or "(empty)",
            "llm_fully_configured": settings.llm_configured,
            "ranking_enabled_env": settings.ranking_enabled,
        },
        # Diagnóstico de visão — booleanos + o id do modelo, que não é segredo
        # e é a causa mais comum de 404 quando o prefixo da org falta.
        "vision_diagnostic": {
            "vision_enabled_env": settings.vision_enabled,
            "vision_api_base_url_set": bool(settings.vision_api_base_url),
            "vision_api_key_set": bool(settings.vision_api_key),
            "vision_model_value": settings.vision_model or "(empty)",
            "vision_fully_configured": settings.vision_configured,
            # O timeout efetivo da visão — a segunda causa mais comum de
            # "configurei tudo e continua caindo no ranking textual".
            "vision_timeout_seconds": settings.vision_timeout_seconds,
        },
    }
    if current_app.config.get("DEBUG"):
        payload["debug"] = True
    return jsonify(payload)


@bp.route("/health/html")
def health_html():
    settings = current_app.config["SETTINGS"]
    return render_template(
        "health.html",
        settings=settings,
        images_provider=getattr(build_pinterest_client(settings), "name", "unknown"),
    )
