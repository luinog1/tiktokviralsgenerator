"""Ponto de entrada — Flask dev server (Docker usa gunicorn)."""

from __future__ import annotations

from app.main import create_app

app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
