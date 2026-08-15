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
    send_from_directory,
    url_for,
)

from app.adapters.goviral_parser import goviral_blocks, parse_goviral
from app.adapters.text_enhancer import enhance_panel
from app.forms import MAX_SCRIPT_BLOCKS, GoviralForm
from app.services.generation import GenerationService
from app.services.goviral_assets import GOVIRAL_ASSETS_DIR
from app.services.pinned_person import load_pinned

bp = Blueprint("goviral", __name__)
logger = logging.getLogger(__name__)


@bp.route("/goviral-assets/<path:filename>")
def asset(filename: str):
    """Serve os prints do GoViral app (pasta `goviral_assets/` na raiz).

    É a URL que a galeria da prévia e o `image_url` do slide de fecho usam —
    o PNG exportado não passa por aqui (o renderer abre direto do disco).
    """
    return send_from_directory(GOVIRAL_ASSETS_DIR, filename)


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


@bp.route("/goviral/enhance", methods=["POST"])
def enhance():
    """Melhora o painel via LLM — opcional, antes de gerar.

    O resultado volta como um painel remontado no formato canônico (Hook /
    Script N / Paragraph N), que o JS põe DE VOLTA na caixa de colar: o usuário
    revisa, edita e gera pelo caminho de sempre — a geração continua sem LLM.
    O hook e os parágrafos saem reescritos (mais curtos, mesma linha), a
    distribuição pelas imagens não muda (o enhancer devolve a mesma contagem de
    parágrafos ou nada), e um script novo fecha o carrossel promovendo o
    goviral app — na última imagem, a mesma que recebe o print do app quando a
    pasta goviral_assets/ existe.
    """
    payload = request.get_json(silent=True) or {}
    parsed = parse_goviral(str(payload.get("raw_text") or ""))
    if not parsed.recognized:
        return jsonify({
            "enhanced": False,
            "reason": "Não reconheci o painel — cole o dashboard inteiro antes.",
        }), 422

    settings = current_app.config["SETTINGS"]
    scripts = parsed.ordered_scripts()
    chunks_per_script = [[c for c in s.chunks if c] for s in scripts]
    paragraphs = [c for chunks in chunks_per_script for c in chunks]

    result = enhance_panel(settings, parsed.hook, paragraphs)
    if result is None:
        reason = (
            "LLM não configurado — defina LLM_API_BASE_URL e LLM_API_KEY."
            if settings.llm_provider == "mock" or not settings.llm_configured
            else "O LLM não devolveu uma melhoria utilizável. Tente de novo."
        )
        return jsonify({"enhanced": False, "reason": reason})

    # Remonta o painel no formato canônico, consumindo os parágrafos na mesma
    # ordem em que foram enviados. `Position` some de propósito: os scripts já
    # saem na ordem final, e renumerar é o que mantém o texto re-colável.
    cursor = iter(result["paragraphs"])
    lines = [f"Hook: {result['hook']}"]
    for number, chunks in enumerate(chunks_per_script, start=1):
        lines.append(f"Script {number}")
        for para_number, _ in enumerate(chunks, start=1):
            lines.append(f"Paragraph {para_number}: {next(cursor)}")
    # O script promo entra como fecho — vira a última imagem, a mesma que
    # recebe o print do goviral_assets/. Só não entra se estourar o teto de
    # blocos (hook + N scripts + promo): um script cortado depois em silêncio
    # é pior que nenhum promo.
    if 2 + len(chunks_per_script) <= MAX_SCRIPT_BLOCKS:
        lines.append(f"Script {len(chunks_per_script) + 1}")
        for para_number, para in enumerate(result["promo"], start=1):
            lines.append(f"Paragraph {para_number}: {para}")
    return jsonify({"enhanced": True, "raw_text": "\n".join(lines)})


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

    service = GenerationService(
        current_app.config["SETTINGS"],
        image_source=(form.image_source.data or "").strip(),
    )
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
            use_pinned_person=bool(form.use_pinned_person.data),
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
        # Com pessoa fixada, o template mostra o checkbox de reusar a pessoa.
        "pinned_person": load_pinned(),
    }
