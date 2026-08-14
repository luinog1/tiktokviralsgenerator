"""POST /pin-person — fixa a pessoa da foto do hook; /pin-person/clear esquece.

A prévia chama `/pin-person` com o projeto e o `image_id` atualmente escolhido
para a imagem 1; o servidor valida que a foto é um pin do Pinterest (fixar é
pedir pins RELACIONADOS depois, e isso só existe para pin) e grava em
`instance/pinned_person.json`. Os formulários leem o mesmo arquivo para
oferecer o checkbox "buscar mais fotos da pessoa fixada".
"""

from __future__ import annotations

import logging

from flask import Blueprint, abort, current_app, jsonify, request

from app.services.pinned_person import clear_pinned, save_pinned
from app.services.session_store import get_store

bp = Blueprint("pinned", __name__)
logger = logging.getLogger(__name__)


@bp.route("/pin-person", methods=["POST"])
def pin():
    payload = request.get_json(silent=True) or {}
    project_id = str(payload.get("project_id") or "")
    image_id = str(payload.get("image_id") or "")
    if not project_id or not image_id:
        abort(400, description="project_id e image_id são obrigatórios.")

    settings = current_app.config["SETTINGS"]
    project = get_store(settings.session_ttl_minutes).get(project_id)
    if not project:
        abort(404, description="Projeto não encontrado ou expirado.")

    image = next(
        (im for im in (project.images or []) if str(im.get("image_id")) == image_id),
        None,
    )
    if image is None:
        abort(404, description="Imagem não encontrada no projeto.")

    saved = save_pinned(image)
    if saved is None:
        return jsonify({
            "pinned": False,
            "reason": (
                "Esta foto não é um pin do Pinterest — fixar só funciona com "
                "fotos vindas do Pinterest (IMAGE_PROVIDER=pinterest_scrape)."
            ),
        }), 422
    return jsonify({"pinned": True, "title": saved["title"]})


@bp.route("/pin-person/clear", methods=["POST"])
def clear():
    clear_pinned()
    return jsonify({"pinned": False})
