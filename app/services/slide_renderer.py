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
from app.services.goviral_assets import GOVIRAL_URL_PREFIX, resolve_asset

logger = logging.getLogger(__name__)

SlideStyle = Literal["sticker", "sticker_outline", "quote", "list", "tutorial", "story"]

# Os dois cortes de legenda nativos do TikTok: caixa branca ("white background")
# e contorno preto ("black outline"). Mesma geometria, tinta diferente — é o que
# permite ao layout sticker servir os dois sem duplicar o posicionamento.
STICKER_STYLES = ("sticker", "sticker_outline")


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
        "sticker_outline": {
            # Black outline: texto branco com contorno preto, sem caixa. O
            # contraste vem do contorno, então a foto também fica limpa.
            "text": (255, 255, 255),
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
        images: list[PinterestImage | None],
        *,
        style: SlideStyle = "quote",
    ) -> list[RenderedSlide]:
        """Renderiza o carrossel.

        Uma lista `images` do mesmo tamanho de `slides` é tratada como já
        alinhada slide a slide (é o que o casting e a galeria da prévia
        produzem, e `None` ali é um slide sem foto). Qualquer outro tamanho cai
        na rotação `i % len`, que é o comportamento de um pool solto.
        """
        if not slides:
            return []
        aligned = len(images) == len(slides)
        rendered: list[RenderedSlide] = []
        for i, slide in enumerate(slides):
            if aligned:
                image = images[i]
            else:
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
        # Nos estilos sticker a foto fica limpa: o contraste vem das caixas
        # brancas ou do contorno preto, então pular o escurecimento.
        if style not in STICKER_STYLES:
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
        if style in STICKER_STYLES:
            # Sticker desenha suas próprias caixas e não usa numeração nem
            # rodapé de atribuição — a atribuição fica na prévia e no Markdown.
            self._draw_sticker_layout(
                draw, headline, body, cta, slide.role,
                pos_x=slide.pos_x, pos_y=slide.pos_y,
                box_positions=slide.box_positions,
                box_scales=slide.box_scales,
                outline=style == "sticker_outline",
            )
            return _encode_lossless_png(canvas)
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
        return _encode_lossless_png(canvas)

    # ---------- layouts ----------

    # Posição vertical do bloco de texto, por papel no roteiro viral — vale
    # para slides de UMA caixa. O hook fica baixo e sozinho (a foto respira em
    # cima); com 2+ caixas quem manda é o espalhamento (_sticker_spread_slots).
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
        box_positions: dict[str, tuple[float, float]] | None = None,
        box_scales: dict[str, float] | None = None,
        outline: bool = False,
    ) -> None:
        """Estilo TikTok: cada bloco vira uma pilha de caixas brancas, uma por
        linha, cada uma do tamanho da própria linha.

        headline e body são blocos separados, e um slide com 2+ caixas sai
        ESPALHADO por padrão: a primeira caixa abre no topo da foto e a última
        fecha no pé — "pergunta em cima, resposta embaixo", o layout dos photo
        posts nativos (ver `_sticker_spread_slots`). Empilhadas uma sob a
        outra, as duas caixas saíam coladas no terço superior e o resto da
        foto ficava vazio. Slides de uma caixa continuam na âncora do papel.

        Dentro de um bloco o texto quebra e cada linha ganha a sua etiqueta;
        as etiquetas se encostam, então a pilha lê como uma mancha branca
        contínua, com a borda acompanhando o comprimento de cada linha.

        Todos os blocos saem no MESMO corpo de fonte: no photo post nativo a
        legenda não muda de tamanho entre "título" e "texto", e dimensionar cada
        bloco por conta própria fazia o corpo do slide sair menor que a headline
        do slide anterior. O tamanho só cai — e cai para todos juntos — quando o
        texto não caberia no canvas.

        `pos_x`/`pos_y` (0..1) são o centro do bloco inteiro, vindos do
        reposicionamento manual na prévia. Ausentes, vale a âncora do papel.
        `box_positions`/`box_scales` ajustam uma caixa isolada: a que tem
        posição própria é desenhada sozinha, fora do empilhamento.
        """
        max_width = int(self._w * self._STICKER_TEXT_WIDTH_RATIO)
        gap = int(self._h * self._STICKER_BLOCK_GAP_RATIO)
        box_positions = box_positions or {}
        box_scales = box_scales or {}

        texts = [("headline", headline), ("body", body), ("cta", cta)]
        sized = self._fit_sticker_blocks(
            draw, texts, max_width=max_width, scales=box_scales, bold_all=outline
        )
        if not sized:
            return

        # Caixa arrastada individualmente sai do fluxo e é desenhada no seu
        # próprio centro; o resto continua empilhado como um bloco só.
        loose = [(k, l, f) for k, l, f in sized if k in box_positions]
        blocks = [(l, f) for k, l, f in sized if k not in box_positions]

        for key, lines, font in loose:
            bx, by = box_positions[key]
            height = self._sticker_block_height(draw, lines, font)
            half_w = self._sticker_block_width(draw, lines, font) // 2
            margin_y = int(self._h * 0.02)
            margin_x = int(self._w * 0.04)
            top = int(self._h * by) - height // 2
            top = max(margin_y, min(top, self._h - height - margin_y))
            cx = int(self._w * bx)
            cx = max(margin_x + half_w, min(cx, self._w - margin_x - half_w))
            self._draw_sticker_block(draw, lines, font, top, cx, outline=outline)

        if not blocks:
            return

        cx = self._w // 2 if pos_x is None else int(self._w * pos_x)
        # A caixa mais larga define o quanto o bloco pode andar para os lados
        # sem cortar texto.
        margin_x = int(self._w * 0.04)
        half_widest = max(self._sticker_block_width(draw, l, f) for l, f in blocks) // 2
        cx = max(margin_x + half_widest, min(cx, self._w - margin_x - half_widest))

        slots = self._sticker_spread_slots(draw, sized, role=role, pos_y=pos_y)
        if slots is not None:
            for key, lines, font in sized:
                if key in box_positions:
                    continue
                self._draw_sticker_block(
                    draw, lines, font, slots[key], cx, outline=outline
                )
            return

        total = sum(self._sticker_block_height(draw, l, f) for l, f in blocks)
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

        y = top
        for lines, font in blocks:
            y = self._draw_sticker_block(draw, lines, font, y, cx, outline=outline) + gap

    # Corpo de fonte único de todas as caixas do sticker, na base de 1080px de
    # largura. Vem do photo post de referência, onde a legenda tem um tamanho só.
    _STICKER_BASE_SIZE = 64
    # Piso do encolhimento automático. Abaixo disso o texto fica ilegível no
    # feed — melhor cortar linha do que continuar reduzindo.
    _STICKER_MIN_SIZE = 38
    # Largura útil do texto, em fração do canvas: a linha corre até PERTO da
    # margem da foto e só então quebra. Era 0.80, que quebrava a frase antes de
    # o espaço acabar e fazia o slide parecer estreito.
    _STICKER_TEXT_WIDTH_RATIO = 0.88
    # Distância entre os topos de duas linhas vizinhas, em fração do corpo da
    # fonte. Medido no photo post de referência (canvas de 1200px, fonte de
    # 56px): as linhas nascem a cada 67px, ou seja 1.196x o corpo. É MENOR que
    # a caixa de uma linha (1.48x), então as caixas se sobrepõem ~0.29x e a
    # pilha sai como uma mancha branca contínua em vez de retângulos soltos.
    _STICKER_LINE_PITCH_RATIO = 1.196
    # Folga da caixa em volta da linha, também em fração do corpo da fonte.
    # Do mesmo photo post: caixa de 711px para uma linha de 659px de tinta
    # (0.45x de cada lado) e 83px de altura sobre uma content area de 73px.
    _STICKER_PAD_X_RATIO = 0.45
    _STICKER_PAD_Y_RATIO = 0.09
    _STICKER_RADIUS_RATIO = 0.22
    # Espessura do contorno preto do estilo "black outline", em fração do corpo
    # da fonte. O Pillow desenha o stroke para FORA do glifo, então 0.12 vira
    # ~8px numa fonte de 64 — o halo encorpado da legenda clássica do TikTok
    # (0.08 saía fino demais perto da referência). A prévia usa o DOBRO em
    # `-webkit-text-stroke`, porque o CSS centra o traço na borda do glifo.
    _STICKER_OUTLINE_RATIO = 0.12
    # Respiro entre caixas (headline → corpo → CTA).
    _STICKER_BLOCK_GAP_RATIO = 0.045
    # Limites do espalhamento vertical dos slides com 2+ caixas: a primeira
    # caixa abre em 12% da altura e a última fecha em 88% — "pergunta em cima,
    # resposta embaixo", como no photo post nativo. A prévia espelha com
    # `justify-content: space-between` e padding vertical de 15% da largura
    # (= 12% da altura no canvas 4:5).
    _STICKER_SPREAD_TOP = 0.12
    _STICKER_SPREAD_BOTTOM = 0.88
    # Fatia da altura do slide que o texto pode ocupar. É o ÚNICO gatilho do
    # encolhimento: enquanto couber na altura, o texto só ganha mais uma linha —
    # é assim que o editor do TikTok se comporta quando o texto cresce.
    _STICKER_MAX_TEXT_RATIO = 0.84

    def _sticker_spread_slots(
        self, draw, sized, *, role: str, pos_y: float | None
    ) -> dict[str, int] | None:
        """Topo de cada caixa no layout espalhado — None quando ele não vale.

        Vale para slides com 2+ caixas de texto, sem arraste do bloco inteiro
        (`pos_y`) e fora do hook, que é uma caixa só ancorada embaixo. A
        primeira caixa abre no topo, a última fecha no pé e o miolo é
        distribuído por igual — a mesma conta do `space-between` da prévia.

        Os slots saem de TODAS as caixas com texto, arrastadas ou não: a caixa
        solta guarda o lugar dela no fluxo, então arrastar uma não move as
        outras. Texto alto demais para espalhar (o respiro entre caixas
        ficaria menor que o gap da pilha) devolve None e cai na pilha de
        sempre, que já sabe encolher e clampar.
        """
        if pos_y is not None or role == "hook" or len(sized) < 2:
            return None
        top_bound = int(self._h * self._STICKER_SPREAD_TOP)
        bottom_bound = int(self._h * self._STICKER_SPREAD_BOTTOM)
        gap = int(self._h * self._STICKER_BLOCK_GAP_RATIO)
        heights = [
            self._sticker_block_height(draw, lines, font)
            for _, lines, font in sized
        ]
        leftover = (bottom_bound - top_bound) - sum(heights)
        if leftover < gap * (len(sized) - 1):
            return None
        spacing = leftover / (len(sized) - 1)
        slots: dict[str, int] = {}
        y = float(top_bound)
        for (key, _, _), height in zip(sized, heights):
            slots[key] = int(round(y))
            y += height + spacing
        return slots

    def _fit_sticker_blocks(
        self,
        draw,
        texts: list[tuple[str, str]],
        *,
        max_width: int,
        scales: dict[str, float] | None = None,
        bold_all: bool = False,
    ) -> list[tuple[str, list[str], Any]]:
        """Quebra as caixas num corpo de fonte COMUM, reduzindo todas juntas.

        Devolve [(chave, linhas, fonte)] só das caixas com texto. O texto corre
        até perto da margem e, quando não cabe mais, ganha uma linha — nenhuma
        linha é descartada. A fonte só cai quando os blocos, somados, não
        caberiam na ALTURA do slide; antes disso o bloco simplesmente cresce
        para baixo, como no editor do TikTok.

        Uma caixa com escala própria em `scales` é dimensionada a partir do
        tamanho comum e não entra na decisão de encolher — o usuário pediu
        aquele tamanho.

        `bold_all` põe TODAS as caixas no corte SemiBold — é o caso do "black
        outline": a legenda clássica do TikTok tem um peso só, e o corpo em
        Medium sob um contorno preto grosso saía fraco, desigual da headline.
        """
        scales = scales or {}
        filled = [(key, text) for key, text in texts if text.strip()]
        if not filled:
            return []

        canvas_scale = self._w / 1080
        size = max(10, int(self._STICKER_BASE_SIZE * canvas_scale))
        floor = max(8, int(self._STICKER_MIN_SIZE * canvas_scale))
        budget = int(self._h * self._STICKER_MAX_TEXT_RATIO)
        gap = int(self._h * self._STICKER_BLOCK_GAP_RATIO)

        while True:
            result = []
            for key, text in filled:
                bold = bold_all or key != "body"
                path = self._bold_path if bold else self._regular_path
                box_size = max(10, int(round(size * scales.get(key, 1.0))))
                font = _font(path, box_size)
                # `max_width` é o limite da CAIXA, não da tinta: a folga lateral
                # sai da mesma largura útil. Medindo só o texto, a etiqueta
                # passava da margem da foto (88% + 2 paddings ≈ 93% do canvas) e
                # a prévia, que limita a caixa, quebrava antes do PNG.
                pad_x, _, _ = self._sticker_padding(font)
                ink_width = max(1, max_width - pad_x * 2)
                result.append((key, _wrap(text, font, ink_width, draw), font))
            heights = [
                self._sticker_block_height(draw, lines, font)
                for key, lines, font in result
                if key not in scales
            ]
            total = sum(heights) + gap * max(0, len(heights) - 1)
            if total <= budget or size <= floor:
                return result
            size -= 2

    def _sticker_line_box_height(self, font) -> int:
        """Altura da caixa de UMA linha: a content area da fonte + a folga.

        `ascent + descent` é a mesma medida que o navegador usa para pintar o
        fundo de um trecho inline, e é CONSTANTE em todas as linhas — medir a
        mancha de tinta linha a linha faria a caixa pular de altura conforme
        houvesse ou não um "g" na linha. O espaço morto que essa métrica embute
        não vira borda sobrando porque o passo entre linhas é menor que a caixa:
        a folga de baixo fica escondida sob a caixa da linha seguinte.
        """
        _, pad_y, _ = self._sticker_padding(font)
        try:
            ascent, descent = font.getmetrics()
            content = int(ascent + descent)
        except (AttributeError, TypeError, ValueError):
            content = 0
        if content <= 0:
            content = int(getattr(font, "size", 30) * 1.3)
        return content + pad_y * 2

    def _sticker_line_pitch(self, font) -> int:
        """Passo entre os topos de duas linhas vizinhas do mesmo bloco."""
        size = getattr(font, "size", 30)
        return max(1, int(round(size * self._STICKER_LINE_PITCH_RATIO)))

    def _sticker_padding(self, font) -> tuple[int, int, int]:
        size = getattr(font, "size", 30)
        pad_x = max(6, int(round(size * self._STICKER_PAD_X_RATIO)))
        pad_y = max(2, int(round(size * self._STICKER_PAD_Y_RATIO)))
        radius = max(6, int(round(size * self._STICKER_RADIUS_RATIO)))
        return pad_x, pad_y, radius

    def _sticker_block_height(self, draw, lines, font) -> int:
        """Altura da pilha: do topo da primeira caixa à base da última."""
        if not lines:
            return 0
        pitch = self._sticker_line_pitch(font)
        return pitch * (len(lines) - 1) + self._sticker_line_box_height(font)

    def _sticker_line_width(self, draw, line, font) -> int:
        """Largura da caixa de UMA linha — ela abraça só a própria linha."""
        pad_x, _, _ = self._sticker_padding(font)
        return int(_ink_width(draw, line, font)) + pad_x * 2

    def _sticker_block_width(self, draw, lines, font) -> int:
        """Largura da linha mais larga do bloco — limita o arraste lateral."""
        if not lines:
            return 0
        return max(self._sticker_line_width(draw, line, font) for line in lines)

    def _draw_sticker_block(
        self, draw, lines, font, top: int, cx: int | None = None, *, outline: bool = False
    ) -> int:
        """Desenha UMA caixa branca arredondada POR LINHA, empilhadas.

        É o que o photo post nativo faz (ver a referência): cada linha ganha uma
        etiqueta do tamanho da própria linha, e as etiquetas se encostam. Uma
        caixa só para o bloco inteiro dava a largura da linha MAIS LONGA a todas
        as outras — nas linhas curtas sobrava um vão branco de cada lado, que é
        exatamente o "espaço sobrando" que não existe no original.

        As caixas se sobrepõem (o passo entre linhas é menor que a altura de uma
        caixa), então a pilha sai como uma mancha branca contínua: nada de
        listras da foto aparecendo entre uma linha e outra.

        `outline=True` é o segundo corte de legenda do TikTok ("black outline"):
        nenhuma caixa — texto branco com contorno preto, na MESMA geometria. As
        duas passadas continuam (contorno de todas as linhas primeiro, letras
        depois): o stroke cresce para fora do glifo e, desenhado linha a linha,
        cobriria o rabo dos "g" da linha de cima, igual às etiquetas.

        Devolve o y do rodapé da última caixa.
        """
        if not lines:
            return top
        _, pad_y, radius = self._sticker_padding(font)
        pitch = self._sticker_line_pitch(font)
        box_h = self._sticker_line_box_height(font)
        if cx is None:
            cx = self._w // 2

        # Duas passadas: TODAS as caixas (ou contornos) primeiro, o texto
        # depois. Desenhar caixa+texto por linha faria a caixa seguinte cobrir
        # o rabo dos "g" e "p" da linha anterior, já que elas se sobrepõem.
        stroke = max(2, int(round(getattr(font, "size", 30) * self._STICKER_OUTLINE_RATIO)))
        if not outline:
            for i, line in enumerate(lines):
                # Largura pela tinta, não pelo avanço: o avanço inclui a folga
                # lateral do último glifo e deixava um vão dentro da caixa.
                box_w = self._sticker_line_width(draw, line, font)
                x0 = cx - box_w // 2
                y0 = top + pitch * i
                draw.rounded_rectangle(
                    [x0, y0, x0 + box_w, y0 + box_h],
                    radius=radius,
                    fill=(255, 255, 255),
                )
        for i, line in enumerate(lines):
            ink_w = _ink_width(draw, line, font)
            ink_left = _ink_left(draw, line, font)
            # Âncora "la": o y passado é o topo do ascender, que é onde a
            # content area da linha começa — logo abaixo da folga da caixa.
            pos = (cx - int(ink_w) // 2 - ink_left, top + pitch * i + pad_y)
            if outline:
                draw.text(pos, line, font=font, fill=(0, 0, 0),
                          stroke_width=stroke, stroke_fill=(0, 0, 0))
            else:
                draw.text(pos, line, font=font, fill=(17, 17, 17))
        if outline:
            for i, line in enumerate(lines):
                ink_w = _ink_width(draw, line, font)
                ink_left = _ink_left(draw, line, font)
                draw.text(
                    (cx - int(ink_w) // 2 - ink_left, top + pitch * i + pad_y),
                    line,
                    font=font,
                    fill=(255, 255, 255),
                )
        return top + pitch * (len(lines) - 1) + box_h

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
        # LANCZOS + reducing_gap preserva mais detalhe quando uma origem grande
        # precisa cair para os 1080x1350 finais. A conversão para RGB também
        # normaliza JPEG CMYK/PNG paletizado antes de colar no canvas sRGB.
        return img.convert("RGB").resize(
            (target_w, target_h),
            Image.Resampling.LANCZOS,
            reducing_gap=3.0,
        )

    def _fetch_image(self, url: str):
        from PIL import Image, ImageOps

        def decoded(source):
            with Image.open(source) as opened:
                opened.load()
                # Fotos de celular costumam guardar a rotação no EXIF. Se o
                # EXIF for descartado sem aplicar a rotação, o cover recorta a
                # orientação errada e desperdiça resolução útil.
                return ImageOps.exif_transpose(opened).convert("RGB")

        if not url:
            return None
        # Print do GoViral app: a URL é relativa (servida pelo Flask) e o
        # arquivo está no disco — um requests.get aqui não teria host.
        if url.startswith(GOVIRAL_URL_PREFIX):
            path = resolve_asset(url.rsplit("/", 1)[-1])
            if not path:
                return None
            try:
                return decoded(path)
            except Exception as exc:
                logger.warning("Não foi possível abrir asset local: %s", type(exc).__name__)
                return None
        if url.startswith("data:"):
            if "svg" in url.lower():
                # SVG não é suportado por Pillow — desenhar um gradiente no lugar
                return self._gradient_image(self._w, self._h)
            try:
                import base64
                header, b64 = url.split(",", 1)
                return decoded(io.BytesIO(base64.b64decode(b64)))
            except Exception:
                return None
        try:
            response = requests.get(
                url,
                timeout=10,
                headers={
                    # Não anunciar AVIF/WebP aqui: alguns CDNs escolheriam uma
                    # variante com perdas mesmo quando a URL aponta para a
                    # origem grande. Pinterest/Unsplash já entregam JPEG/PNG.
                    "Accept": "image/png,image/jpeg",
                    "User-Agent": "ViralPostStudio/1.0",
                },
            )
            response.raise_for_status()
            return decoded(io.BytesIO(response.content))
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


def _encode_lossless_png(canvas) -> bytes:
    """Serializa o canvas sem uma etapa JPEG/WebP ou redução de dimensão.

    PNG é lossless; `optimize`/`compress_level` só alteram o tamanho do
    arquivo, não os pixels. Deixar a política num helper único evita que um
    estilo futuro reintroduza uma conversão com perdas por acidente.
    """
    buffer = io.BytesIO()
    canvas.save(
        buffer,
        format="PNG",
        optimize=True,
        compress_level=9,
        dpi=(72, 72),
    )
    return buffer.getvalue()


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
    """Largura de avanço do texto — usada para decidir a quebra de linha."""
    try:
        return draw.textlength(text, font=font)
    except (AttributeError, TypeError):
        try:
            bbox = draw.textbbox((0, 0), text, font=font)
            return bbox[2] - bbox[0]
        except Exception:
            return len(text) * getattr(font, "size", 30) * 0.5


def _ink_box(draw, text: str, font) -> tuple[float, float, float, float] | None:
    try:
        return draw.textbbox((0, 0), text, font=font)
    except (AttributeError, TypeError, Exception):
        return None


def _ink_width(draw, text: str, font) -> float:
    """Largura só da tinta — é o que faz a caixa branca abraçar o texto.

    O avanço (`textlength`) inclui a folga lateral que a fonte reserva depois
    do último glifo; dimensionar a caixa por ele deixa uma sobra visível à
    direita, e a caixa deixa de parecer colada na frase.
    """
    box = _ink_box(draw, text, font)
    if box is None:
        return _text_width(draw, text, font)
    return max(0.0, box[2] - box[0])


def _ink_left(draw, text: str, font) -> float:
    """Folga à esquerda do primeiro glifo, descontada ao desenhar."""
    box = _ink_box(draw, text, font)
    return box[0] if box else 0.0


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


__all__ = ["SlideRenderer", "RenderedSlide", "SlideStyle", "STICKER_STYLES"]
