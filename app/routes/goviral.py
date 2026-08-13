"""A ferramenta interna: o painel do goviral colado inteiro vira carrossel.

O `/create` é o formulário completo — dois modos, um campo por imagem, nº de
slides. Para quem já tem o roteiro pronto no painel do goviral, quase tudo isso
é pergunta que o painel já responde: quantas imagens, o que é hook e o que são
as duas caixas de cada imagem. O que sobra é colar e gerar.

A composição é a mesma do modo roteiro (`compose_from_blocks`, chamado pelo
`GenerationService`): esta rota só traduz o painel em blocos e entrega ao fluxo
que já existe — nenhum render, ranking ou busca de foto próprios, e nenhum LLM
no caminho do texto.
"""

from __future__ import annotations

import logging

from flask import (
    Blueprint,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)

from app.adapters.goviral_parser import goviral_blocks, parse_goviral
from app.forms import MAX_SCRIPT_BLOCKS, GoviralForm
from app.services.generation import GenerationService

bp = Blueprint("goviral", __name__)
logger = logging.getLogger(__name__)


@bp.route("/goviral", methods=["GET"])
def paste():
    return render_template("goviral.html", form=GoviralForm(), **_context())


@bp.route("/goviral/parse", methods=["POST"])
def parse():
    """O que o parser entendeu do painel, sem gerar nada.

    O painel é HTML de terceiro: quando o goviral mudar o layout, o parser vai
    errar — e sem esta rota o sintoma seria um carrossel com o texto no slide
    errado, que é caro de diagnosticar. Aqui a distribuição aparece antes.
    """
    payload = request.get_json(silent=True) or {}
    parsed = parse_goviral(str(payload.get("raw_text") or ""))
    blocks = parsed.blocks()
    return jsonify({
        "recognized": parsed.recognized,
        "hook": parsed.hook,
        "blocks": blocks[:MAX_SCRIPT_BLOCKS],
        "found": len(blocks),
        "limit": MAX_SCRIPT_BLOCKS,
    })


@bp.route("/goviral", methods=["POST"])
def generate():
    form = GoviralForm()
    if not form.validate_on_submit():
        for field_name, errors in form.errors.items():
            for err in errors:
                flash(f"{field_name}: {err}", "error")
        return render_template("goviral.html", form=form, **_context()), 422

    blocks = goviral_blocks(form.raw_text.data or "")
    if not blocks:
        flash(
            'Não reconheci o painel: preciso do rótulo "Hook" com a frase e de '
            'pelo menos um "Script 1" com os parágrafos. Clique em "Conferir o '
            'que foi entendido" para ver o que chegou.',
            "error",
        )
        return render_template("goviral.html", form=form, **_context()), 422

    warnings: list[str] = []
    if len(blocks) > MAX_SCRIPT_BLOCKS:
        warnings.append(
            f"O painel trouxe {len(blocks)} imagens; o carrossel usa as "
            f"{MAX_SCRIPT_BLOCKS} primeiras."
        )
        blocks = blocks[:MAX_SCRIPT_BLOCKS]

    # O corpus da busca de fotos, do ranking e da visão é o texto LIMPO, não o
    # painel colado: com os rótulos dentro, um tema vazio faria a query virar
    # "Content Dashboard Last updated".
    clean_text = "\n\n".join(blocks)

    service = GenerationService(current_app.config["SETTINGS"])
    try:
        outcome = service.run(
            raw_text=clean_text,
            theme=(form.theme.data or "").strip(),
            keywords=form.keyword_list(),
            style=(form.style.data or "sticker").strip(),
            # O painel decide quantas imagens o carrossel tem — é a pergunta
            # que esta tela existe para não fazer.
            slides_count=len(blocks),
            script_blocks=blocks,
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("Falha de geração pelo painel: %s", type(exc).__name__)
        flash("Falha ao gerar carrossel. Tente novamente.", "error")
        return render_template("goviral.html", form=form, **_context()), 422

    for warning in warnings + outcome.warnings:
        flash(warning, "warning")
    return redirect(url_for("preview.preview", project_id=outcome.project_id))


def _context() -> dict:
    """Contexto do goviral.html — reusado pelo 422 do POST."""
    settings = current_app.config["SETTINGS"]
    return {
        "goviral_url": "https://content.goviralai.app/",
        "casting_enabled": settings.casting_enabled,
        "hook_subject": settings.hook_subject,
        "max_images": MAX_SCRIPT_BLOCKS,
    }
