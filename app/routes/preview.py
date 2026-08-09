"""GET /preview/<id>, POST /preview/<id>/edit, POST /preview/<id>/export.

Exporta: PNG (slide único), ZIP (carrossel completo), Markdown (texto).
"""

from __future__ import annotations

import io
import logging
import zipfile

from flask import (
    Blueprint,
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


def _get_service() -> GenerationService:
    settings = current_app.config["SETTINGS"]
    return GenerationService(settings)


def _position_field(slide: dict) -> str:
    """Serializa a posição arrastada de volta para o campo hidden ("x,y")."""
    x, y = slide.get("pos_x"), slide.get("pos_y")
    if x is None or y is None:
        return ""
    return f"{x},{y}"


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

    return render_template(
        "preview.html",
        project=project.to_public_dict(),
        slides=slides,
        images=images,
        image_for_slide=image_for_slide,
        style=style,
        form=form,
        role_labels=ROLE_LABELS,
    )


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
    rendered = renderer.render_carousel(slides, [img for img in image_objs if img], style=style)

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
