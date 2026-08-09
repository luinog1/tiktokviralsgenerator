"""SlideRenderer — compõe o carrossel visual no estilo TikTok photo.

Estilo principal ('sticker'): texto preto em caixas brancas arredondadas, uma
por linha, sobre a foto sem escurecer — o formato de legenda nativo do TikTok.
Estilos legados: 'quote', 'list', 'tutorial', 'story' (texto branco sobre
gradiente escuro).
"""

from __future__ import annotations

import io
import logging
import math
import os
import re
import textwrap
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Literal

import requests

from app.config import Settings
from app.adapters.pinterest_client import PinterestImage
from app.adapters.text_composer import SlideContent

logger = logging.getLogger(__name__)

SlideStyle = Literal["sticker", "quote", "list", "tutorial", "story"]


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
        "sticker": {
            # Sticker não escurece a foto: o contraste vem da caixa branca.
            "text": (17, 17, 17),
            "accent": (255, 255, 255),
            "overlay_top": (0, 0, 0, 0),
            "overlay_bottom": (0, 0, 0, 0),
        },
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
        self._bold_path, self._regular_path = _resolve_font_paths()
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

        # 2. Overlay para legibilidade.
        # No estilo sticker a foto fica limpa: o contraste vem das caixas
        # brancas, então pular o escurecimento.
        if style != "sticker":
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
        if style == "sticker":
            # Sticker desenha suas próprias caixas e não usa numeração nem
            # rodapé de atribuição — a atribuição fica na prévia e no Markdown.
            self._draw_sticker_layout(
                draw, headline, body, cta, slide.role,
                pos_x=slide.pos_x, pos_y=slide.pos_y,
            )
            buffer = io.BytesIO()
            canvas.save(buffer, format="PNG", optimize=True)
            return buffer.getvalue()
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

    # Posição vertical do bloco de texto, por papel no roteiro viral.
    # O hook fica baixo e sozinho (a foto respira em cima); os slides de
    # desenvolvimento usam dois blocos separados, começando no terço superior.
    _STICKER_ANCHORS: dict[str, float] = {
        "hook": 0.60,
        "problem": 0.13,
        "agitation": 0.15,
        "value": 0.18,
        "proof": 0.16,
        "cta": 0.38,
    }

    def _draw_sticker_layout(
        self,
        draw,
        headline,
        body,
        cta,
        role: str = "value",
        *,
        pos_x: float | None = None,
        pos_y: float | None = None,
    ) -> None:
        """Estilo TikTok: cada linha vira uma caixa branca arredondada.

        headline e body são blocos separados, com respiro entre eles — é assim
        que o texto aparece nos photo posts nativos do TikTok.

        `pos_x`/`pos_y` (0..1) são o centro do bloco, vindos do
        reposicionamento manual na prévia. Ausentes, vale a âncora do papel.
        """
        max_width = int(self._w * 0.80)
        gap = int(self._h * 0.045)

        headline_font, headline_lines = self._fit_sticker_font(
            draw, headline, max_width=max_width, base=68, min_size=40, max_lines=4
        )
        body_font, body_lines = self._fit_sticker_font(
            draw, body, max_width=max_width, base=54, min_size=32, max_lines=5, bold=False
        )
        cta_font, cta_lines = self._fit_sticker_font(
            draw, cta, max_width=max_width, base=52, min_size=32, max_lines=2
        )

        blocks = [
            (headline_lines, headline_font),
            (body_lines, body_font),
            (cta_lines, cta_font),
        ]
        blocks = [(lines, font) for lines, font in blocks if lines]
        if not blocks:
            return

        total = sum(self._sticker_block_height(l, f) for l, f in blocks)
        total += gap * (len(blocks) - 1)

        anchor = self._STICKER_ANCHORS.get(role, 0.18)
        if pos_y is not None:
            # Arrastado na prévia: o valor guardado é o centro do bloco.
            top = int(self._h * pos_y) - total // 2
        elif role == "hook":
            # Ancorado pela base: o hook fecha perto do rodapé.
            top = int(self._h * 0.86) - total
        elif role == "cta":
            top = (self._h - total) // 2
        else:
            top = int(self._h * anchor)

        # Nunca deixar o texto sangrar para fora do canvas.
        margin = int(self._h * 0.06)
        top = max(margin, min(top, self._h - total - margin))

        cx = self._w // 2 if pos_x is None else int(self._w * pos_x)
        # O mesmo cuidado no eixo X: a caixa mais larga define o quanto o
        # bloco pode andar para os lados sem cortar texto.
        margin_x = int(self._w * 0.04)
        half_widest = max(self._sticker_block_width(draw, l, f) for l, f in blocks) // 2
        cx = max(margin_x + half_widest, min(cx, self._w - margin_x - half_widest))

        y = top
        for lines, font in blocks:
            y = self._draw_sticker_block(draw, lines, font, y, cx) + gap

    def _fit_sticker_font(
        self,
        draw,
        text: str,
        *,
        max_width: int,
        base: int,
        min_size: int,
        max_lines: int,
        bold: bool = True,
    ):
        """Reduz o corpo da fonte até o texto caber em `max_lines` linhas."""
        if not text.strip():
            return None, []
        path = self._bold_path if bold else self._regular_path
        scale = self._w / 1080
        size = max(10, int(base * scale))
        floor = max(8, int(min_size * scale))
        font = _font(path, size)
        lines = _wrap(text, font, max_width, draw)
        while len(lines) > max_lines and size > floor:
            size -= 2
            font = _font(path, size)
            lines = _wrap(text, font, max_width, draw)
        return font, lines[:max_lines]

    def _sticker_line_height(self, font) -> int:
        try:
            ascent, descent = font.getmetrics()
            return ascent + descent
        except AttributeError:  # bitmap default font
            return int(getattr(font, "size", 30) * 1.2)

    def _sticker_padding(self, font) -> tuple[int, int, int]:
        size = getattr(font, "size", 30)
        pad_x = max(8, int(size * 0.34))
        pad_y = max(3, int(size * 0.13))
        radius = max(6, int(size * 0.24))
        return pad_x, pad_y, radius

    def _sticker_block_height(self, lines, font) -> int:
        if not lines:
            return 0
        _, pad_y, _ = self._sticker_padding(font)
        box_h = self._sticker_line_height(font) + pad_y * 2
        # -2px por linha: as caixas se encostam, sem fresta entre elas.
        return box_h * len(lines) - 2 * (len(lines) - 1)

    def _sticker_block_width(self, draw, lines, font) -> int:
        """Largura da caixa mais larga do bloco — limita o arraste lateral."""
        if not lines:
            return 0
        pad_x, _, _ = self._sticker_padding(font)
        widest = max(_text_width(draw, line, font) for line in lines)
        return int(widest) + pad_x * 2

    def _draw_sticker_block(self, draw, lines, font, top: int, cx: int | None = None) -> int:
        """Desenha as caixas brancas centralizadas em `cx`. Devolve o y do rodapé."""
        pad_x, pad_y, radius = self._sticker_padding(font)
        line_h = self._sticker_line_height(font)
        box_h = line_h + pad_y * 2
        if cx is None:
            cx = self._w // 2
        y = top
        for line in lines:
            text_w = _text_width(draw, line, font)
            box_w = int(text_w) + pad_x * 2
            x0 = cx - box_w // 2
            draw.rounded_rectangle(
                [x0, y, x0 + box_w, y + box_h],
                radius=radius,
                fill=(255, 255, 255),
            )
            draw.text((x0 + pad_x, y + pad_y), line, font=font, fill=(17, 17, 17))
            y += box_h - 2
        return y + 2

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
        bold_path, regular_path = self._bold_path, self._regular_path
        # Tamanhos proporcionais à largura do canvas (base 1080px) para que
        # SLIDE_WIDTH/SLIDE_HEIGHT customizados não quebrem o layout.
        scale = self._w / 1080

        def _px(size: int) -> int:
            return max(10, int(round(size * scale)))

        return {
            "headline_big": _font(bold_path, _px(78)),
            "headline": _font(bold_path, _px(58)),
            "body": _font(regular_path, _px(38)),
            "cta": _font(bold_path, _px(36)),
            "tag": _font(bold_path, _px(26)),
            "number": _font(bold_path, _px(56)),
            "quote_mark": _font(bold_path, _px(140)),
            "meta": _font(regular_path, _px(22)),
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


# Ordem de preferência de fontes. A primeira que existir no sistema vence.
# `static/fonts/` vem primeiro: basta soltar um .ttf lá (ex.: Poppins) para
# trocar a tipografia de todos os slides, sem mexer no código.
_BUNDLED_FONT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "static",
    "fonts",
)

_BOLD_CANDIDATES = (
    os.path.join(_BUNDLED_FONT_DIR, "sticker-bold.ttf"),
    # Linux (Docker/Render) — instaladas via apt no Dockerfile
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    # Windows (dev local)
    "C:/Windows/Fonts/segoeuib.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    # macOS
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
)

_REGULAR_CANDIDATES = (
    os.path.join(_BUNDLED_FONT_DIR, "sticker-regular.ttf"),
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    "C:/Windows/Fonts/segoeui.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/Library/Fonts/Arial.ttf",
)


def _resolve_font_paths() -> tuple[str | None, str | None]:
    """Descobre as fontes disponíveis. SLIDE_FONT_BOLD/REGULAR têm prioridade."""
    bold = os.environ.get("SLIDE_FONT_BOLD", "").strip() or None
    regular = os.environ.get("SLIDE_FONT_REGULAR", "").strip() or None
    if not bold or not _file_exists(bold):
        bold = next((p for p in _BOLD_CANDIDATES if _file_exists(p)), None)
    if not regular or not _file_exists(regular):
        regular = next((p for p in _REGULAR_CANDIDATES if _file_exists(p)), None)
    if bold is None and regular is None:
        # load_default() é bitmap e ignora o tamanho — os slides sairiam com
        # texto minúsculo. Avisar alto para não virar "bug silencioso".
        logger.warning(
            "Nenhuma fonte TrueType encontrada — os slides vão usar a fonte "
            "bitmap padrão do Pillow. Instale fonts-liberation/fonts-dejavu "
            "ou aponte SLIDE_FONT_BOLD para um .ttf."
        )
    return bold or regular, regular or bold


@lru_cache(maxsize=256)
def _font(path: str | None, size: int):
    """Carrega (com cache) uma fonte TrueType no tamanho pedido."""
    from PIL import ImageFont

    if path:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            logger.warning("Falha ao carregar fonte %s — usando padrão.", path)
    return ImageFont.load_default()


_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

# As fontes do sistema (Liberation, DejaVu, Segoe UI) não têm glifos de emoji
# colorido — o Pillow desenharia um retângulo vazio (tofu) no lugar. Remover
# antes de renderizar. O emoji continua intacto na legenda e no Markdown.
_EMOJI_RE = re.compile(
    "["
    "\U0001F000-\U0001FAFF"  # pictogramas, emoticons, símbolos suplementares
    "\U00002190-\U000021FF"  # setas
    "\U00002300-\U000027BF"  # técnicos, dingbats
    "\U00002B00-\U00002BFF"  # setas/símbolos diversos
    "\U0000FE00-\U0000FE0F"  # seletores de variação
    "\U0001F1E6-\U0001F1FF"  # bandeiras
    "\U000024C2-\U0001F251"
    "\U0000200D"             # zero-width joiner
    "]+",
    flags=re.UNICODE,
)


def _safe_text(value: str) -> str:
    text = _CONTROL_RE.sub("", str(value))
    text = _EMOJI_RE.sub("", text)
    # A remoção pode deixar espaços duplos ou sobrando nas pontas.
    return re.sub(r"\s{2,}", " ", text).strip()


def _text_width(draw, text: str, font) -> float:
    """Largura de avanço do texto — usada para dimensionar a caixa branca."""
    try:
        return draw.textlength(text, font=font)
    except (AttributeError, TypeError):
        try:
            bbox = draw.textbbox((0, 0), text, font=font)
            return bbox[2] - bbox[0]
        except Exception:
            return len(text) * getattr(font, "size", 30) * 0.5


def _wrap(text: str, font, max_width: int, draw) -> list[str]:
    if not text:
        return []
    words = text.split()
    if not words:
        return []
    lines: list[str] = []
    current = ""
    for word in words:
        # Palavra sozinha maior que a linha (URL, hashtag longa): quebrar no
        # meio, senão a caixa branca sairia mais larga que o slide.
        if _text_width(draw, word, font) > max_width:
            if current:
                lines.append(current)
                current = ""
            lines.extend(_break_long_word(word, font, max_width, draw))
            current = lines.pop() if lines else ""
            continue
        candidate = f"{current} {word}".strip()
        if _text_width(draw, candidate, font) > max_width and current:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def _break_long_word(word: str, font, max_width: int, draw) -> list[str]:
    """Fatia uma palavra indivisível em pedaços que caibam na largura."""
    pieces: list[str] = []
    chunk = ""
    for char in word:
        if chunk and _text_width(draw, chunk + char, font) > max_width:
            pieces.append(chunk)
            chunk = char
        else:
            chunk += char
    if chunk:
        pieces.append(chunk)
    return pieces


def _file_exists(path: str) -> bool:
    import os
    return os.path.isfile(path)


__all__ = ["SlideRenderer", "RenderedSlide", "SlideStyle"]
