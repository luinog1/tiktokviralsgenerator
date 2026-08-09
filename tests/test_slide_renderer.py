"""Testes do SlideRenderer — estilo sticker, fontes e quebra de linha."""

from __future__ import annotations

import io

import pytest
from PIL import Image

from app.adapters.text_composer import SlideContent
from app.config import Settings
from app.services.slide_renderer import (
    SlideRenderer,
    _break_long_word,
    _resolve_font_paths,
    _safe_text,
    _wrap,
)


@pytest.fixture
def renderer():
    return SlideRenderer(Settings.from_env({}))


def _open(png_bytes: bytes) -> Image.Image:
    return Image.open(io.BytesIO(png_bytes))


# ---------- Fontes ----------


def test_resolves_a_truetype_font():
    """Sem fonte TrueType o Pillow cai no bitmap padrão e ignora o tamanho —
    os slides sairiam com texto minúsculo."""
    bold, regular = _resolve_font_paths()
    assert bold, "nenhuma fonte bold encontrada no sistema"
    assert regular, "nenhuma fonte regular encontrada no sistema"


def test_bundled_tiktok_sans_wins_over_system_fonts(monkeypatch):
    """A tipografia é o que aproxima o slide do photo post do TikTok.

    Se os .ttf empacotados saírem do repo (ou do build Docker), a resolução cai
    numa fonte do sistema — Liberation Sans no Linux — e o render volta a
    destoar. Este teste falha antes de o visual regredir.
    """
    from PIL import ImageFont

    monkeypatch.delenv("SLIDE_FONT_BOLD", raising=False)
    monkeypatch.delenv("SLIDE_FONT_REGULAR", raising=False)

    bold, regular = _resolve_font_paths()
    assert ImageFont.truetype(bold, 40).getname() == ("TikTok Sans", "SemiBold")
    assert ImageFont.truetype(regular, 40).getname() == ("TikTok Sans", "Medium")


def test_bundled_fonts_are_static_instances():
    """O Google Fonts publica TikTok Sans só como variável, com default Light 300.

    Se alguém trocar os arquivos pelo .ttf variável cru, o Pillow carrega a
    instância default e os slides saem finos demais — sem erro nenhum.
    """
    from PIL import ImageFont

    bold, regular = _resolve_font_paths()
    for path in (bold, regular):
        font = ImageFont.truetype(path, 40)
        with pytest.raises(OSError):
            font.get_variation_axes()

    # E os dois cortes precisam ser realmente diferentes: instanciar os dois no
    # mesmo peso passaria nas checagens de nome acima sem mudar o desenho.
    text = "there were weeks i was posting"
    assert ImageFont.truetype(bold, 54).getlength(text) > ImageFont.truetype(
        regular, 54
    ).getlength(text)


def test_fonts_respect_requested_size(renderer):
    """Confirma que a fonte carregada é escalável (não a bitmap padrão)."""
    from PIL import ImageDraw

    draw = ImageDraw.Draw(Image.new("RGB", (1080, 1350)))
    font, lines = renderer._fit_sticker_font(
        draw, "texto de teste", max_width=800, base=40, min_size=20, max_lines=3
    )
    assert lines == ["texto de teste"]
    assert font.size >= 20


def test_fit_font_shrinks_until_it_fits(renderer):
    """Texto longo deve reduzir o corpo da fonte em vez de estourar as linhas."""
    from PIL import ImageDraw

    draw = ImageDraw.Draw(Image.new("RGB", (1080, 1350)))
    long_text = "uma frase bem comprida que precisa encolher para caber " * 3
    font, lines = renderer._fit_sticker_font(
        draw, long_text, max_width=800, base=68, min_size=30, max_lines=4
    )
    assert len(lines) <= 4
    assert font.size < int(68 * (renderer._w / 1080))


# ---------- Estilo sticker ----------


def test_sticker_renders_expected_dimensions(renderer):
    slide = SlideContent(headline="teste de slide", role="hook", order=0)
    out = renderer.render_single(slide, None, style="sticker", index=0)
    img = _open(out.png_bytes)
    assert img.size == (1080, 1350)


def test_sticker_draws_white_boxes(renderer):
    """A marca do estilo: caixas brancas puras atrás do texto."""
    slide = SlideContent(headline="caixa branca aqui", role="hook", order=0)
    out = renderer.render_single(slide, None, style="sticker", index=0)
    colors = _open(out.png_bytes).convert("RGB").getcolors(maxcolors=1_000_000)
    white_pixels = sum(count for count, color in colors if color == (255, 255, 255))
    assert white_pixels > 5000, "nenhuma caixa branca significativa foi desenhada"


def test_sticker_does_not_darken_the_photo(renderer):
    """Diferente dos estilos legados, sticker não aplica overlay preto."""
    slide = SlideContent(headline="oi", role="value", order=0)
    sticker = _open(renderer.render_single(slide, None, style="sticker").png_bytes)
    quote = _open(renderer.render_single(slide, None, style="quote").png_bytes)
    # Canto superior esquerdo: sticker preserva o fundo, quote escurece.
    assert sticker.convert("RGB").getpixel((5, 5)) != (0, 0, 0)
    assert sum(quote.convert("RGB").getpixel((5, 5))) <= sum(
        sticker.convert("RGB").getpixel((5, 5))
    )


@pytest.mark.parametrize(
    "role", ["hook", "problem", "agitation", "value", "proof", "cta"]
)
def test_sticker_renders_every_role(renderer, role):
    slide = SlideContent(
        headline="uma headline de tamanho realista para o slide",
        body="um corpo de texto com algumas palavras a mais para forçar quebra",
        call_to_action="salva esse post" if role == "cta" else "",
        role=role,
        order=0,
    )
    out = renderer.render_single(slide, None, style="sticker", index=0)
    assert _open(out.png_bytes).size == (1080, 1350)


def test_hook_sits_lower_than_value(renderer):
    """O hook fecha embaixo; slides de valor começam no topo."""
    text = "mesma frase nos dois slides para comparar a posição"

    def first_white_row(role: str) -> int:
        png = renderer.render_single(
            SlideContent(headline=text, role=role), None, style="sticker"
        ).png_bytes
        img = _open(png).convert("RGB")
        for y in range(img.height):
            if any(img.getpixel((x, y)) == (255, 255, 255) for x in range(0, img.width, 12)):
                return y
        return img.height

    assert first_white_row("hook") > first_white_row("value")


def test_empty_slide_does_not_crash(renderer):
    out = renderer.render_single(
        SlideContent(headline="", body="", call_to_action="", role="value"),
        None,
        style="sticker",
    )
    assert _open(out.png_bytes).size == (1080, 1350)


# ---------- Quebra de linha ----------


def test_long_word_is_broken_to_fit():
    """Uma URL sem espaços não pode gerar caixa mais larga que o slide."""
    from PIL import ImageDraw, ImageFont

    draw = ImageDraw.Draw(Image.new("RGB", (1080, 1350)))
    bold, _ = _resolve_font_paths()
    font = ImageFont.truetype(bold, 60)
    word = "https://exemplo.com/" + "a" * 120
    pieces = _break_long_word(word, font, 800, draw)
    assert len(pieces) > 1
    for piece in pieces:
        assert draw.textlength(piece, font=font) <= 800


def test_wrap_keeps_every_line_within_max_width():
    from PIL import ImageDraw, ImageFont

    draw = ImageDraw.Draw(Image.new("RGB", (1080, 1350)))
    bold, _ = _resolve_font_paths()
    font = ImageFont.truetype(bold, 58)
    text = "consistência constrói confiança e não o contrário, sempre https://link-enorme-sem-espacos-nenhum-aqui.com"
    for line in _wrap(text, font, 820, draw):
        assert draw.textlength(line, font=font) <= 820


def test_wrap_preserves_all_words():
    from PIL import ImageDraw, ImageFont

    draw = ImageDraw.Draw(Image.new("RGB", (1080, 1350)))
    bold, _ = _resolve_font_paths()
    font = ImageFont.truetype(bold, 58)
    text = "cada palavra precisa sobreviver a quebra de linha sem sumir"
    assert " ".join(_wrap(text, font, 700, draw)).split() == text.split()


# ---------- Sanitização de texto ----------


def test_emoji_is_stripped_before_rendering():
    """Fontes do sistema não têm glifo de emoji — sairia um retângulo vazio."""
    assert _safe_text("salva esse post 🤍") == "salva esse post"
    assert _safe_text("comenta aqui 👇🏽 agora") == "comenta aqui agora"
    assert _safe_text("antes 🔖 depois") == "antes depois"


def test_safe_text_keeps_accents_and_punctuation():
    """Só emoji e caracteres de controle saem — o texto real fica intacto."""
    assert _safe_text("consistência: não é sorte, é constância!") == (
        "consistência: não é sorte, é constância!"
    )


def test_safe_text_strips_control_characters():
    assert _safe_text("linha\x00com\x07controle") == "linhacomcontrole"

