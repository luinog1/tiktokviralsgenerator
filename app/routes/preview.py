"""GET /preview/<id>, POST /preview/<id>/edit, POST /preview/<id>/export.

Exporta: PNG (slide único), ZIP (carrossel completo), Markdown (texto).
"""

from __future__ import annotations

import io
import logging
import zipfile
from urllib.parse import urlsplit

import requests
from flask import (
    Blueprint,
    Response,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)

from app.adapters import PinterestImage
from app.adapters.text_composer import SlideContent
from app.forms import SlideEditForm
from app.services.generation import GenerationService
from app.services.slide_renderer import SlideRenderer

bp = Blueprint("preview", __name__)
logger = logging.getLogger(__name__)

# Rótulos legíveis dos papéis do roteiro viral, exibidos na prévia.
ROLE_LABELS = {
    "hook": "1 · Hook",
    "problem": "2 · Problema",
    "agitation": "3 · Agitação",
    "value": "Valor",
    "proof": "Prova",
    "cta": "Fecho · CTA",
}

# O que a visão viu na foto — mostrado na prévia para o casting ser auditável:
# sem isso, "por que essa foto no slide 1?" não tem resposta na tela.
SUBJECT_LABELS = {
    "woman": "👤 mulher",
    "man": "👤 homem",
    "person": "👤 pessoa",
    "scene": "🏞 cenário",
}


def _get_service() -> GenerationService:
    settings = current_app.config["SETTINGS"]
    return GenerationService(settings)


def _position_field(slide: dict) -> str:
    """Serializa a posição arrastada de volta para o campo hidden ("x,y")."""
    x, y = slide.get("pos_x"), slide.get("pos_y")
    if x is None or y is None:
        return ""
    return f"{x},{y}"


def _box_positions(raw) -> dict[str, tuple[float, float]]:
    """dict do store → {"headline": (x, y)} para o SlideContent.

    O que foi persistido é JSON, então o par chega como lista. Entradas
    malformadas (projeto antigo, edição manual) são ignoradas em vez de
    derrubarem o export inteiro.
    """
    result: dict[str, tuple[float, float]] = {}
    for key, value in (raw or {}).items():
        try:
            x, y = float(value[0]), float(value[1])
        except (TypeError, ValueError, IndexError, KeyError):
            continue
        result[str(key)] = (x, y)
    return result


def _box_scales(raw) -> dict[str, float]:
    result: dict[str, float] = {}
    for key, value in (raw or {}).items():
        try:
            result[str(key)] = float(value)
        except (TypeError, ValueError):
            continue
    return result


def _box_positions_field(slide: dict) -> str:
    """{"headline": [x, y]} → "headline:x,y" para o campo hidden da prévia."""
    parts = []
    for key, value in (slide.get("box_positions") or {}).items():
        try:
            parts.append(f"{key}:{float(value[0])},{float(value[1])}")
        except (TypeError, ValueError, IndexError, KeyError):
            continue
    return ";".join(parts)


def _box_scales_field(slide: dict) -> str:
    parts = []
    for key, value in (slide.get("box_scales") or {}).items():
        try:
            parts.append(f"{key}:{float(value)}")
        except (TypeError, ValueError):
            continue
    return ";".join(parts)


# ---------------------------------------------------------------------------
# Fotos do Instagram na prévia — o CDN deles manda
# `Cross-Origin-Resource-Policy: same-origin` (medido em 2026-08-16 no
# scontent-*.cdninstagram.com E no instagram.f*.fna.fbcdn.net): o navegador
# baixa a foto e a DESCARTA na checagem de CORP, porque a página é de outra
# origem. O <img> vira o quadrado branco com o alt escrito — com a URL viva e
# o download do servidor funcionando, que é o que torna o sintoma enganoso.
# Nenhum atributo (referrerpolicy/crossorigin) contorna CORP; a saída é a
# prévia pedir a foto AO APP, que a busca do lado do servidor, onde CORP não
# vale. Só as URLs do CDN do Instagram passam por aqui: as outras fontes não
# mandam o header, e um proxy aberto viraria SSRF.
# ---------------------------------------------------------------------------

def _is_instagram_cdn(url: str) -> bool:
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    host = (parts.hostname or "").lower()
    return parts.scheme == "https" and (
        host == "cdninstagram.com"
        or host.endswith(".cdninstagram.com")
        or host == "fbcdn.net"
        or host.endswith(".fbcdn.net")
    )


@bp.app_template_filter("browser_src")
def browser_src(url: str) -> str:
    """URL que o NAVEGADOR consegue exibir. Foto do Instagram sai proxiada;
    qualquer outra (Pinterest, Unsplash, data URI do mock) passa intacta."""
    if not _is_instagram_cdn(url or ""):
        return url or ""
    return url_for("preview.image_proxy", u=url)


@bp.route("/image-proxy")
def image_proxy():
    url = request.args.get("u", "")
    if not _is_instagram_cdn(url):
        abort(404)
    settings = current_app.config["SETTINGS"]
    try:
        upstream = requests.get(
            url,
            timeout=settings.request_timeout_seconds,
            # O CDN não redireciona; um redirect aqui seria o proxy sendo
            # apontado para outro lugar — falha em vez de seguir.
            allow_redirects=False,
        )
    except requests.RequestException as exc:
        logger.warning("Proxy de imagem falhou (%s).", type(exc).__name__)
        return Response(status=502)
    if upstream.status_code != 200:
        # URL assinada expirada (a prévia é da sessão, não para guardar) ou
        # CDN indisponível — o thumb quebra só quando a foto está morta mesmo.
        return Response(status=502)
    return Response(
        upstream.content,
        mimetype=upstream.headers.get("Content-Type", "image/jpeg"),
        # A URL assinada é imutável enquanto vale: o navegador pode guardar o
        # thumb em vez de re-proxiar a cada render da prévia.
        headers={"Cache-Control": "public, max-age=86400"},
    )


@bp.route("/preview/<project_id>")
def preview(project_id: str):
    svc = _get_service()
    project = svc.store().get(project_id)
    if not project:
        abort(404, description="Projeto não encontrado ou expirado.")

    carousel = project.carousel or {}
    slides = project.edited_slides or carousel.get("slides", [])
    images = project.images or []
    style = project.style or "quote"

    # Pré-selecionar imagem para cada slide (índice % imagens)
    image_for_slide: list[dict | None] = []
    for i, slide in enumerate(slides):
        # Se houver image_id no slide editado, usar; senão round-robin
        img_id = slide.get("image_id") if isinstance(slide, dict) else None
        if img_id:
            img = next((im for im in images if im["image_id"] == img_id), None)
        else:
            img = images[i % len(images)] if images else None
        image_for_slide.append(img)

    form = SlideEditForm()
    # Pré-popular campos
    for i, slide in enumerate(slides):
        form.headlines.append_entry(slide.get("headline", ""))
        form.bodies.append_entry(slide.get("body", ""))
        form.ctas.append_entry(slide.get("call_to_action", ""))
        form.selected_image_ids.append_entry(
            slide.get("image_id") or (images[i % len(images)]["image_id"] if images else "")
        )
        form.text_positions.append_entry(_position_field(slide))
        form.box_positions.append_entry(_box_positions_field(slide))
        form.box_scales.append_entry(_box_scales_field(slide))

    return render_template(
        "preview.html",
        project=project.to_public_dict(),
        slides=slides,
        images=images,
        image_for_slide=image_for_slide,
        style=style,
        form=form,
        role_labels=ROLE_LABELS,
        subject_labels=_subject_labels(project),
        casting_enabled=current_app.config["SETTINGS"].casting_enabled,
    )


def _subject_labels(project) -> dict[str, str]:
    """image_id → rótulo do assunto, para as fotos que a visão classificou.

    O `ranking` guardado é o veredicto da visão quando ela rodou (o
    GenerationService persiste os dois no mesmo campo), então o `subject` chega
    aqui de graça — sem ele, "por que essa foto no slide 1?" não tem resposta.
    """
    labels: dict[str, str] = {}
    for entry in project.ranking or []:
        if not isinstance(entry, dict):
            continue
        label = SUBJECT_LABELS.get(str(entry.get("subject") or "").strip())
        if label and entry.get("image_id"):
            labels[str(entry["image_id"])] = label
    return labels


@bp.route("/preview/<project_id>/edit", methods=["POST"])
def edit(project_id: str):
    svc = _get_service()
    project = svc.store().get(project_id)
    if not project:
        abort(404, description="Projeto não encontrado.")

    original_slides = project.carousel.get("slides", [])
    form = SlideEditForm()
    # Recriar as entradas para que o FieldList tenha o tamanho certo
    for i, slide in enumerate(original_slides):
        form.headlines.append_entry("")
        form.bodies.append_entry("")
        form.ctas.append_entry("")
        form.selected_image_ids.append_entry("")
        form.text_positions.append_entry("")
        form.box_positions.append_entry("")
        form.box_scales.append_entry("")

    if not form.validate_on_submit():
        for field_name, errors in form.errors.items():
            for err in errors:
                flash(f"{field_name}: {err}", "error")
        return redirect(url_for("preview.preview", project_id=project_id))

    edited_slides = form.to_edited_slides(original_slides)
    svc.store().update(
        project_id,
        edited_slides=edited_slides,
        selected_image_ids=[s.get("image_id", "") for s in edited_slides],
    )
    flash("Carrossel atualizado.", "success")
    return redirect(url_for("preview.preview", project_id=project_id))


@bp.route("/preview/<project_id>/export", methods=["POST"])
def export(project_id: str):
    """Exporta o carrossel em um dos formatos: png, zip, md."""
    svc = _get_service()
    project = svc.store().get(project_id)
    if not project:
        abort(404, description="Projeto não encontrado.")

    fmt = (request.form.get("format") or "zip").lower()
    slides_data = project.edited_slides or project.carousel.get("slides", [])
    images = project.images or []
    style = project.style or "quote"

    if not slides_data:
        abort(400, description="Carrossel vazio.")

    if fmt in {"md", "markdown"}:
        return _export_markdown(project, slides_data, images)
    if fmt == "png":
        # Renderiza apenas o primeiro slide
        return _export_single_png(project, slides_data, images, style)
    # default: zip com todos os slides
    return _export_zip(project, slides_data, images, style)


def _build_slides_and_images(slides_data, images):
    """Converte dicts para objetos tipados."""
    slides = [
        SlideContent(
            headline=s.get("headline", ""),
            body=s.get("body", ""),
            call_to_action=s.get("call_to_action", ""),
            order=i,
            role=s.get("role", "value"),
            pos_x=s.get("pos_x"),
            pos_y=s.get("pos_y"),
            box_positions=_box_positions(s.get("box_positions")),
            box_scales=_box_scales(s.get("box_scales")),
            image_id=s.get("image_id", ""),
        )
        for i, s in enumerate(slides_data)
    ]
    image_objs: list[PinterestImage | None] = []
    for i, s in enumerate(slides_data):
        img_id = s.get("image_id")
        img = None
        if img_id:
            img = next((im for im in images if im["image_id"] == img_id), None)
        if not img and images:
            img = images[i % len(images)]
        if img:
            image_objs.append(
                PinterestImage(
                    image_id=img["image_id"],
                    image_url=img["image_url"],
                    source_url=img["source_url"],
                    title=img.get("title", ""),
                    description=img.get("description", ""),
                    attribution_text=img.get("attribution_text", ""),
                )
            )
        else:
            image_objs.append(None)
    return slides, image_objs


def _render_zip(project, slides_data, images, style) -> bytes:
    settings = current_app.config["SETTINGS"]
    renderer = SlideRenderer(settings)
    slides, image_objs = _build_slides_and_images(slides_data, images)
    # image_objs já vem alinhado slide a slide (casting + escolha na galeria).
    # Filtrar os None aqui desalinharia tudo: o slide 3 herdaria a foto do 4.
    rendered = renderer.render_carousel(slides, image_objs, style=style)

    # Criar ZIP em memória
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for r in rendered:
            zf.writestr(r.filename, r.png_bytes)
        # Markdown anexo com legendas e atribuição
        md_lines = [
            f"# Carrossel — {project.briefing.get('theme', '')}",
            "",
            f"**Estilo:** {style}",
            f"**Slides:** {len(rendered)}",
            "",
        ]
        for r in rendered:
            md_lines.extend([
                f"## Slide {r.slide_index + 1}",
                f"**Headline:** {r.headline}",
                "",
                r.body,
                "",
                f"**CTA:** {r.call_to_action}" if r.call_to_action else "",
                f"**Imagem:** {r.image_source_url}" if r.image_source_url else "",
                f"**Atribuição:** {r.attribution_text}" if r.attribution_text else "",
                "",
                "---",
                "",
            ])
        if project.carousel.get("hashtags"):
            md_lines.append("**Hashtags:** " + " ".join(f"#{h}" for h in project.carousel["hashtags"]))
        if project.carousel.get("caption"):
            md_lines.append("")
            md_lines.append(f"**Legenda:** {project.carousel['caption']}")
        zf.writestr("carrossel.md", "\n".join(md_lines).encode("utf-8"))
    buffer.seek(0)
    return buffer.getvalue()


def _export_zip(project, slides_data, images, style):
    zip_bytes = _render_zip(project, slides_data, images, style)
    return send_file(
        io.BytesIO(zip_bytes),
        as_attachment=True,
        download_name=f"viralpost-{project.project_id}.zip",
        mimetype="application/zip",
    )


def _export_single_png(project, slides_data, images, style):
    settings = current_app.config["SETTINGS"]
    renderer = SlideRenderer(settings)
    slides, image_objs = _build_slides_and_images(slides_data, images)
    if not slides:
        abort(400, description="Sem slides para renderizar.")
    img_for_first = image_objs[0] if image_objs else None
    rendered = renderer.render_single(slides[0], img_for_first, style=style, index=0)
    return send_file(
        io.BytesIO(rendered.png_bytes),
        as_attachment=True,
        download_name=f"viralpost-{project.project_id}-slide1.png",
        mimetype="image/png",
    )


def _export_markdown(project, slides_data, images):
    lines = [
        f"# Carrossel — {project.briefing.get('theme', '')}",
        "",
        f"**Estilo:** {project.style}",
        f"**Slides:** {len(slides_data)}",
        "",
    ]
    for i, slide in enumerate(slides_data):
        lines.extend([
            f"## Slide {i + 1}",
            f"**Headline:** {slide.get('headline', '')}",
            "",
            slide.get("body", ""),
            "",
        ])
        if slide.get("call_to_action"):
            lines.append(f"**CTA:** {slide['call_to_action']}")
            lines.append("")
        img_id = slide.get("image_id")
        if img_id:
            img = next((im for im in images if im["image_id"] == img_id), None)
            if img:
                lines.append(f"**Imagem:** {img['source_url']}")
                if img.get("attribution_text"):
                    lines.append(f"**Atribuição:** {img['attribution_text']}")
                lines.append("")
        lines.append("---")
        lines.append("")

    if project.carousel.get("hashtags"):
        lines.append("**Hashtags:** " + " ".join(f"#{h}" for h in project.carousel["hashtags"]))
        lines.append("")
    if project.carousel.get("caption"):
        lines.append(f"**Legenda:** {project.carousel['caption']}")

    buffer = io.BytesIO("\n".join(lines).encode("utf-8"))
    buffer.seek(0)
    return send_file(
        buffer,
        as_attachment=True,
        download_name=f"viralpost-{project.project_id}.md",
        mimetype="text/markdown",
    )
