"""SlideRenderer — compõe o carrossel visual no estilo TikTok photo.

Cada slide = imagem de fundo + overlay de gradiente + texto (headline + body + CTA).
Layouts suportados: 'quote' (texto centralizado), 'list' (texto à esquerda),
'tutorial' (headline no topo, body central, CTA no rodapé), 'story' (overlay forte).
"""

from __future__ import annotations

import io
import logging
import math
import re
import textwrap
from dataclasses import dataclass
from typing import Any, Literal

import requests

from app.config import Settings
from app.adapters.pinterest_client import PinterestImage
from app.adapters.text_composer import SlideContent

logger = logging.getLogger(__name__)

SlideStyle = Literal["quote", "list", "tutorial", "story"]


@dataclass
class RenderedSlide:
    """Bytes PNG de um slide + metadados."""

    slide_index: int
    png_bytes: bytes
    headline: str
    body: str
    call_to_action: str
    image_id: str
    image_source_url: str
    attribution_text: str

    @property
    def filename(self) -> str:
        return f"slide_{self.slide_index + 1:02d}.png"


class SlideRenderer:
    """Renderiza carrossel TikTok-style a partir de slides + imagens."""

    # Cores por estilo — paletas sociais, alto contraste para legibilidade
    _PALETTES: dict[str, dict[str, tuple[int, int, int]]] = {
        "quote": {
            "text": (255, 255, 255),
            "accent": (255, 230, 109),  # amarelo
            "overlay_top": (0, 0, 0, 0),
            "overlay_bottom": (0, 0, 0, 200),
        },
        "list": {
            "text": (255, 255, 255),
            "accent": (78, 205, 196),  # verde-água
            "overlay_top": (0, 0, 0,140),
            "overlay_bottom": (0, 0, 0, 220),
        },
        "tutorial": {
            "text": (255, 255, 255),
            "accent": (255, 107, 107),  # coral
            "overlay_top": (0,0,0,180),
            "overlay_bottom": (0,0,0,160),
        },
        "story": {
            "text": (255, 255, 255),
            "accent": (255, 211, 165),
            "overlay_top": (0,0,0,160),
            "overlay_bottom": (0, 0, 0, 200),
        },
    }

    def __init__(self, settings: Settings):
        self._settings = settings
        self._w = settings.slide_width
        self._h = settings.slide_height
        self._fonts = self._load_fonts()

    # ---------- API pública ----------

    def render_carousel(
        self,
        slides: list[SlideContent],
        images: list[PinterestImage],
        *,
        style: SlideStyle = "quote",
    ) -> list[RenderedSlide]:
        if not slides:
            return []
        rendered: list[RenderedSlide] = []
        for i, slide in enumerate(slides):
            image = images[i % len(images)] if images else None
            png_bytes = self._compose_one(slide, image, style)
            rendered.append(
                RenderedSlide(
                    slide_index=i,
                    png_bytes=png_bytes,
                    headline=slide.headline,
                    body=slide.body,
                    call_to_action=slide.call_to_action,
                    image_id=image.image_id if image else "",
                    image_source_url=image.source_url if image else "",
                    attribution_text=image.attribution_text if image else "",
                )
            )
        return rendered

    def render_single(
        self,
        slide: SlideContent,
        image: PinterestImage | None,
        *,
        style: SlideStyle = "quote",
        index: int = 0,
    ) -> RenderedSlide:
        png_bytes = self._compose_one(slide, image, style)
        return RenderedSlide(
            slide_index=index,
            png_bytes=png_bytes,
            headline=slide.headline,
            body=slide.body,
            call_to_action=slide.call_to_action,
            image_id=image.image_id if image else "",
            image_source_url=image.source_url if image else "",
            attribution_text=image.attribution_text if image else "",
        )

    # ---------- composição ----------

    def _compose_one(
        self,
        slide: SlideContent,
        image: PinterestImage | None,
        style: SlideStyle,
    ) -> bytes:
        from PIL import Image, ImageDraw, ImageFilter, ImageFont

        canvas = Image.new("RGB", (self._w, self._h), color=(15, 14, 23))
        draw = ImageDraw.Draw(canvas)
        palette = self._PALETTES.get(style, self._PALETTES["quote"])

        # 1. Fundo: imagem ou gradiente
        bg_image = self._fetch_image(image.image_url) if image else None
        if bg_image is not None:
            bg_image = self._cover_fit(bg_image, self._w, self._h)
            canvas.paste(bg_image, (0, 0))
        else:
            # Gradiente padrão caso não haja imagem
            self._draw_gradient(draw, self._w, self._h, palette)

        # 2. Overlay para legibilidade
        overlay = Image.new("RGBA", (self._w, self._h), (0, 0, 0, 0))
        overlay_draw = ImageDraw.Draw(overlay)
        # Gradient overlay: topo + base
        self._draw_alpha_gradient(
            overlay_draw, self._w, self._h,
            top_color=palette["overlay_top"],
            bottom_color=palette["overlay_bottom"],
        )
        canvas = Image.alpha_composite(canvas.convert("RGBA"), overlay).convert("RGB")
        draw = ImageDraw.Draw(canvas)

        # 3. Texto
        fonts = self._fonts
        text_color = palette["text"]
        accent_color = palette["accent"]

        headline = _safe_text(slide.headline or "")
        body = _safe_text(slide.body or "")
        cta = _safe_text(slide.call_to_action or "")

        # Layout por estilo
        if style == "list":
            self._draw_list_layout(draw, headline, body, cta, fonts, text_color, accent_color)
        elif style == "tutorial":
            self._draw_tutorial_layout(draw, headline, body, cta, fonts, text_color, accent_color)
        elif style == "story":
            self._draw_story_layout(draw, headline, body, cta, fonts, text_color, accent_color)
        else:  # quote
            self._draw_quote_layout(draw, headline, body, cta, fonts, text_color, accent_color)

        # 4. Atribuição (rodapé inferior) + número do slide
        attribution = (image.attribution_text if image else "") or ""
        if attribution:
            self._draw_text_with_shadow(
                draw,
                f"Fonte: {attribution}",
                pos=(40, self._h - 70),
                font=fonts["meta"],
                fill=(220, 220, 220),
            )
        # Numeração de slide (canto superior direito)
        self._draw_text_with_shadow(
            draw,
            f"{slide.order + 1:02d}",
            pos=(self._w - 110, 40),
            font=fonts["number"],
            fill=accent_color,
        )

        # 5. Exportar PNG
        buffer = io.BytesIO()
        canvas.save(buffer, format="PNG", optimize=True)
        return buffer.getvalue()

    # ---------- layouts ----------

    def _draw_quote_layout(self, draw, headline, body, cta, fonts, text_color, accent):
        from PIL import ImageDraw
        # Citação: aspas decorativas no topo, headline grande centralizada, body abaixo
        cx = self._w // 2
        y = int(self._h * 0.28)

        # Aspas decorativas
        self._draw_text_with_shadow(
            draw, "\u201C", pos=(cx - 30, y - 90), font=fonts["quote_mark"], fill=accent
        )

        # Headline (até 3 linhas, grande)
        for line in _wrap(headline, fonts["headline_big"], self._w - 120, draw)[:3]:
            self._draw_text_centered(draw, line, y, fonts["headline_big"], text_color)
            y += self._line_height(fonts["headline_big"])

        y += 30
        # Body (até 5 linhas, menor)
        for line in _wrap(body, fonts["body"], self._w - 180, draw)[:5]:
            self._draw_text_centered(draw, line, y, fonts["body"], (230, 230, 230))
            y += self._line_height(fonts["body"])

        # CTA no rodapé
        if cta:
            self._draw_text_centered(
                draw, cta, self._h - 130, fonts["cta"], accent
            )

    def _draw_list_layout(self, draw, headline, body, cta, fonts, text_color, accent):
        # Headline alinhada à esquerda, no topo
        x = 60
        y = 90
        # Barra de destaque
        draw.rectangle([x, y, x + 6, y + self._line_height(fonts["headline"])], fill=accent)

        for i, line in enumerate(_wrap(headline, fonts["headline"], self._w - 160, draw)[:3]):
            self._draw_text_with_shadow(
                draw, line, pos=(x + 20, y), font=fonts["headline"], fill=text_color
            )
            y += self._line_height(fonts["headline"]) + 6

        y += 50
        # Body com bullet • em cada parágrafo
        bullets = [b.strip() for b in re.split(r"\n+|\.\s+", body) if b.strip()][:6]
        for bullet in bullets:
            if len(bullet) < 3:
                continue
            # Bullet marker
            draw.ellipse([x, y + 18, x + 14, y + 32], fill=accent)
            for j, line in enumerate(_wrap(bullet, fonts["body"], self._w - 200, draw)[:3]):
                self._draw_text_with_shadow(
                    draw, line, pos=(x + 30, y), font=fonts["body"], fill=text_color
                )
                y += self._line_height(fonts["body"]) + 2
            y += 12

        if cta:
            self._draw_text_centered(draw, cta, self._h - 130, fonts["cta"], accent)

    def _draw_tutorial_layout(self, draw, headline, body, cta, fonts, text_color, accent):
        # Headline topo com fundo colorido
        x = 60
        y = 80
        # Tag "PASSO A PASSO"
        self._draw_text_with_shadow(
            draw, "PASSO A PASSO", pos=(x, y), font=fonts["tag"], fill=accent
        )
        y += self._line_height(fonts["tag"]) + 10

        for line in _wrap(headline, fonts["headline"], self._w - 120, draw)[:3]:
            self._draw_text_with_shadow(
                draw, line, pos=(x, y), font=fonts["headline"], fill=text_color
            )
            y += self._line_height(fonts["headline"]) + 4

        y += 60
        # Body central, em caixa
        body_lines = _wrap(body, fonts["body"], self._w - 160, draw)[:7]
        for line in body_lines:
            self._draw_text_with_shadow(
                draw, line, pos=(x, y), font=fonts["body"], fill=(240, 240, 240)
            )
            y += self._line_height(fonts["body"]) + 2

        # CTA caixa no rodapé
        if cta:
            box_y = self._h - 160
            draw.rounded_rectangle(
                [x, box_y, self._w - 60, box_y + 70], radius=12, fill=accent
            )
            self._draw_text_centered(
                draw, cta, box_y + 22, fonts["cta"], (15, 14, 23)
            )

    def _draw_story_layout(self, draw, headline, body, cta, fonts, text_color, accent):
        # Story: headline grande no topo, body centralizado verticalmente, CTA inferior
        x = 60
        cx = self._w // 2
        y = 100
        # Tag de story
        self._draw_text_with_shadow(
            draw, "HISTÓRIA", pos=(x, y), font=fonts["tag"], fill=accent
        )
        y += self._line_height(fonts["tag"]) + 30

        for line in _wrap(headline, fonts["headline_big"], self._w - 120, draw)[:3]:
            self._draw_text_with_shadow(
                draw, line, pos=(x, y), font=fonts["headline_big"], fill=text_color
            )
            y += self._line_height(fonts["headline_big"]) + 6

        y = int(self._h * 0.55)
        for line in _wrap(body, fonts["body"], self._w - 120, draw)[:6]:
            self._draw_text_with_shadow(
                draw, line, pos=(x, y), font=fonts["body"], fill=(235, 235, 235)
            )
            y += self._line_height(fonts["body"]) + 2

        if cta:
            self._draw_text_centered(draw, cta, self._h - 130, fonts["cta"], accent)

    # ---------- utilidades ----------

    def _load_fonts(self) -> dict[str, Any]:
        from PIL import ImageFont
        font_paths = [
            ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "bold"),
            ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "regular"),
            ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf", "italic"),
        ]
        # Tentar fontes mais pesadas se disponíveis
        try_paths = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        ]
        bold_path = next((p for p in try_paths if _file_exists(p)), None)

        regular_paths = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
        ]
        regular_path = next((p for p in regular_paths if _file_exists(p)), None)

        def _try(path: str | None, size: int):
            if not path:
                return ImageFont.load_default()
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                return ImageFont.load_default()

        return {
            "headline_big": _try(bold_path, 78),
            "headline": _try(bold_path, 58),
            "body": _try(regular_path, 38),
            "cta": _try(bold_path, 36),
            "tag": _try(bold_path, 26),
            "number": _try(bold_path, 56),
            "quote_mark": _try(bold_path, 140),
            "meta": _try(regular_path, 22),
        }

    def _line_height(self, font) -> int:
        try:
            return int(font.size * 1.2)
        except AttributeError:
            return 50

    def _draw_text_with_shadow(self, draw, text, pos, font, fill, shadow_offset=(2, 2)):
        sx, sy = pos
        ox, oy = shadow_offset
        draw.text((sx + ox, sy + oy), text, font=font, fill=(0, 0, 0))
        draw.text((sx, sy), text, font=font, fill=fill)

    def _draw_text_centered(self, draw, text, y, font, fill):
        try:
            bbox = draw.textbbox((0, 0), text, font=font)
            w = bbox[2] - bbox[0]
        except Exception:
            w = len(text) * (font.size if hasattr(font, "size") else 30) * 0.5
        x = max(40, (self._w - w) // 2)
        self._draw_text_with_shadow(draw, text, pos=(x, y), font=font, fill=fill)

    def _draw_gradient(self, draw, w, h, palette):
        from PIL import Image
        # Gradiente vertical simples como fallback
        top = (40, 38, 60)
        bottom = (15, 14, 23)
        for y in range(h):
            ratio = y / max(1, h - 1)
            r = int(top[0] + (bottom[0] - top[0]) * ratio)
            g = int(top[1] + (bottom[1] - top[1]) * ratio)
            b = int(top[2] + (bottom[2] - top[2]) * ratio)
            draw.line([(0, y), (w, y)], fill=(r, g, b))

    def _draw_alpha_gradient(self, draw, w, h, top_color, bottom_color):
        # top_color e bottom_color são RGBA tuples
        for y in range(h):
            ratio = y / max(1, h - 1)
            # topo meio transparente, base bem opaca
            top_a = top_color[3]
            bot_a = bottom_color[3]
            alpha = int(top_a + (bot_a - top_a) * ratio)
            # Cor preta + alpha variável
            draw.line([(0, y), (w, y)], fill=(0, 0, 0, alpha))

    def _cover_fit(self, img, target_w, target_h):
        """Redimensiona e recorta para preencher o target (cover)."""
        from PIL import Image
        src_w, src_h = img.size
        target_ratio = target_w / target_h
        src_ratio = src_w / src_h
        if src_ratio > target_ratio:
            # Imagem mais larga — recortar laterais
            new_h = src_h
            new_w = int(src_h * target_ratio)
            left = (src_w - new_w) // 2
            img = img.crop((left, 0, left + new_w, new_h))
        else:
            new_w = src_w
            new_h = int(src_w / target_ratio)
            top = (src_h - new_h) // 2
            img = img.crop((0, top, new_w, top + new_h))
        return img.resize((target_w, target_h), Image.LANCZOS)

    def _fetch_image(self, url: str):
        from PIL import Image
        if not url:
            return None
        if url.startswith("data:"):
            if "svg" in url.lower():
                # SVG não é suportado por Pillow — desenhar um gradiente no lugar
                return self._gradient_image(self._w, self._h)
            try:
                import base64
                header, b64 = url.split(",", 1)
                return Image.open(io.BytesIO(base64.b64decode(b64)))
            except Exception:
                return None
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            return Image.open(io.BytesIO(response.content))
        except Exception as exc:
            logger.warning("Não foi possível baixar imagem: %s", type(exc).__name__)
            return None

    def _gradient_image(self, w, h):
        from PIL import Image, ImageDraw
        img = Image.new("RGB", (w, h), (40, 38, 60))
        draw = ImageDraw.Draw(img)
        self._draw_gradient(draw, w, h, {})
        return img


# ---------- helpers de módulo ----------


def _safe_text(value: str) -> str:
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", str(value))


def _wrap(text: str, font, max_width: int, draw) -> list[str]:
    if not text:
        return []
    # textwrap para quebrar por palavras; depois medir para caber
    words = text.split()
    if not words:
        return []
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        try:
            bbox = draw.textbbox((0, 0), candidate, font=font)
            w = bbox[2] - bbox[0]
        except Exception:
            w = len(candidate) * (getattr(font, "size", 30) * 0.5)
        if w > max_width and current:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def _file_exists(path: str) -> bool:
    import os
    return os.path.isfile(path)


__all__ = ["SlideRenderer", "RenderedSlide", "SlideStyle"]
