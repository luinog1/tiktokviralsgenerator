"""Aplicação Flask — factory e bootstrap."""

from __future__ import annotations

import logging
import os
from typing import Any

from flask import Flask, render_template
from flask_wtf.csrf import CSRFProtect

from app.config import Settings

csrf = CSRFProtect()


def create_app(settings: Settings | None = None) -> Flask:
    """Application factory."""
    settings = settings or Settings.from_env()

    # Configurar logging antes de qualquer coisa
    logging.basicConfig(
        level=logging.INFO if not settings.debug else logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    template_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates")
    static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")

    app = Flask(
        __name__,
        template_folder=template_dir,
        static_folder=static_dir,
    )
    app.config.update(
        SECRET_KEY=settings.secret_key or "dev-insecure-change-me",
        WTF_CSRF_TIME_LIMIT=None,
        DEBUG=settings.debug,
        MAX_CONTENT_LENGTH=2 * 1024 * 1024,  # 2MB safety
    )
    app.config["SETTINGS"] = settings
    app.config["VPS_SETTINGS"] = settings  # alias usado em templates

    csrf.init_app(app)

    # injetar no jinja
    @app.context_processor
    def inject_globals() -> dict[str, Any]:
        return {
            "settings": settings,
            "app_version": "0.2.0",
        }

    # Registrar blueprints
    from app.routes.main import bp as main_bp
    from app.routes.create import bp as create_bp
    from app.routes.generate import bp as generate_bp
    from app.routes.preview import bp as preview_bp
    from app.routes.health import bp as health_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(create_bp)
    app.register_blueprint(generate_bp)
    app.register_blueprint(preview_bp)
    app.register_blueprint(health_bp)

    # Tratamento de erros
    @app.errorhandler(400)
    def bad_request(err):  # noqa: ANN001
        return render_template("error.html", code=400, message="Requisição inválida."), 400

    @app.errorhandler(404)
    def not_found(err):  # noqa: ANN001
        return render_template("error.html", code=404, message="Página não encontrada."), 404

    @app.errorhandler(422)
    def unprocessable(err):  # noqa: ANN001
        return render_template("error.html", code=422, message="Dados inválidos."), 422

    @app.errorhandler(500)
    def server_error(err):  # noqa: ANN001
        logging.getLogger(__name__).exception("Erro interno: %s", err)
        return render_template(
            "error.html",
            code=500,
            message="Erro interno. Tente novamente em instantes.",
        ), 500

    @app.errorhandler(CSRFError)
    def csrf_error(reason):  # noqa: ANN001
        return render_template("error.html", code=400, message=str(reason)), 400

    return app


# CSRF é exportado como símbolo público para reuso em testes.
__all__ = ["create_app", "csrf"]


# Necessário para import direto em run.py
try:
    from flask_wtf.csrf import CSRFError  # noqa: F401
except Exception:  # pragma: no cover - se Flask-WTF ausente
    pass
