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
    _ink_width,
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
    sized = renderer._fit_sticker_blocks(
        draw, [("headline", "texto de teste")], max_width=800
    )
    assert [lines for _, lines, _ in sized] == [["texto de teste"]]
    assert sized[0][2].size >= 20


def test_fit_font_shrinks_only_when_the_height_runs_out(renderer):
    """A fonte cai quando o bloco não caberia na ALTURA — não por contar linhas.

    Enquanto sobra altura o texto só ganha mais uma linha, como no editor do
    TikTok. Um teto fixo de linhas encolhia a fonte com o slide ainda vazio.
    """
    from PIL import ImageDraw

    draw = ImageDraw.Draw(Image.new("RGB", (1080, 1350)))
    base = int(renderer._STICKER_BASE_SIZE * (renderer._w / 1080))

    # Mais linhas do que o antigo teto de 4, e ainda com altura sobrando:
    # o corpo da fonte tem de ficar intacto.
    medium = "uma frase de tamanho realista para um slide de carrossel " * 3
    _, lines, font = renderer._fit_sticker_blocks(
        draw, [("headline", medium)], max_width=950
    )[0]
    assert len(lines) > 4, "o texto precisa quebrar em várias linhas neste teste"
    assert font.size == base

    # Texto que passaria da altura útil: aí sim a fonte cai.
    huge = "uma frase bem comprida que precisa encolher para caber " * 12
    _, _, font_big = renderer._fit_sticker_blocks(
        draw, [("headline", huge)], max_width=950
    )[0]
    assert font_big.size < base


def test_no_line_is_dropped_when_the_text_grows(renderer):
    """O texto cresce para baixo; nenhuma palavra é descartada no caminho."""
    from PIL import ImageDraw

    draw = ImageDraw.Draw(Image.new("RGB", (1080, 1350)))
    text = "cada palavra precisa sobreviver mesmo quando o texto fica comprido " * 3
    _, lines, _ = renderer._fit_sticker_blocks(
        draw, [("body", text)], max_width=950
    )[0]
    assert " ".join(lines).split() == text.split()


def test_every_box_shares_the_same_font_size(renderer):
    """No photo post do TikTok a legenda tem UM tamanho.

    Antes cada bloco era dimensionado por conta própria (68/54/52 e pisos
    diferentes), então o corpo do slide saía menor que a headline e o mesmo
    texto mudava de tamanho conforme o campo em que fosse colado.
    """
    from PIL import ImageDraw

    draw = ImageDraw.Draw(Image.new("RGB", (1080, 1350)))
    sized = renderer._fit_sticker_blocks(
        draw,
        [
            ("headline", "if your views are down, don't panic."),
            ("body", "growth isn't linear. don't let one bad day make you forget."),
            ("cta", "salva esse post"),
        ],
        max_width=800,
    )
    sizes = {font.size for _, _, font in sized}
    assert len(sizes) == 1, f"tamanhos divergentes entre as caixas: {sizes}"


def test_overflow_shrinks_all_boxes_together(renderer):
    """Se uma caixa estoura, TODAS reduzem — senão a igualdade se quebra."""
    from PIL import ImageDraw

    draw = ImageDraw.Draw(Image.new("RGB", (1080, 1350)))
    overflowing = "palavra " * 120
    sized = renderer._fit_sticker_blocks(
        draw,
        [("headline", "curto"), ("body", overflowing)],
        max_width=800,
    )
    sizes = {font.size for _, _, font in sized}
    assert len(sizes) == 1
    assert sizes.pop() < int(renderer._STICKER_BASE_SIZE * (renderer._w / 1080))


def test_box_scale_multiplies_only_that_box(renderer):
    """O resize do editor vale para a caixa pedida, não para o slide todo."""
    from PIL import ImageDraw

    draw = ImageDraw.Draw(Image.new("RGB", (1080, 1350)))
    texts = [("headline", "uma frase"), ("body", "outra frase")]
    plain = dict(
        (key, font.size)
        for key, _, font in renderer._fit_sticker_blocks(draw, texts, max_width=800)
    )
    scaled = dict(
        (key, font.size)
        for key, _, font in renderer._fit_sticker_blocks(
            draw, texts, max_width=800, scales={"headline": 1.5}
        )
    )
    assert scaled["headline"] > plain["headline"]
    assert scaled["body"] == plain["body"]


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


def _white_box_bounds(renderer, slide) -> tuple[int, int, int, int]:
    """(top, bottom, left, right) das caixas brancas no PNG renderizado."""
    img = _open(renderer.render_single(slide, None, style="sticker").png_bytes).convert("RGB")
    rows, cols = [], []
    for y in range(0, img.height, 4):
        for x in range(0, img.width, 4):
            if img.getpixel((x, y)) == (255, 255, 255):
                rows.append(y)
                cols.append(x)
    assert rows, "nenhuma caixa branca encontrada no slide"
    return min(rows), max(rows), min(cols), max(cols)


def test_explicit_position_overrides_role_anchor(renderer):
    """O arraste na prévia tem que aparecer no PNG, não só na tela."""
    text = "mesma frase para comparar a posição"
    default_top, _, _, _ = _white_box_bounds(
        renderer, SlideContent(headline=text, role="value")
    )
    moved_top, moved_bottom, _, _ = _white_box_bounds(
        renderer, SlideContent(headline=text, role="value", pos_x=0.5, pos_y=0.75)
    )
    assert moved_top > default_top
    # pos_y é o CENTRO do bloco: o meio das caixas fica perto de 75% da altura.
    center = (moved_top + moved_bottom) / 2
    assert abs(center - 1350 * 0.75) < 40


def test_explicit_position_moves_block_horizontally(renderer):
    slide = SlideContent(headline="curto", role="value")
    _, _, left_default, right_default = _white_box_bounds(renderer, slide)
    slide_left = SlideContent(headline="curto", role="value", pos_x=0.2, pos_y=0.5)
    _, _, left_moved, right_moved = _white_box_bounds(renderer, slide_left)
    assert left_moved < left_default
    assert right_moved < right_default


def test_position_is_clamped_inside_the_canvas(renderer):
    """Arrastar para fora não pode cortar a caixa branca."""
    slide = SlideContent(
        headline="uma headline comprida o suficiente para ocupar duas linhas aqui",
        role="value",
        pos_x=1.5,
        pos_y=-0.4,
    )
    top, bottom, left, right = _white_box_bounds(renderer, slide)
    assert top >= 0 and left >= 0
    assert bottom < 1350 and right < 1080


def test_slide_without_position_keeps_role_anchor(renderer):
    """Compatibilidade: slides antigos (sem pos_x/pos_y) não mudam de lugar."""
    text = "hook ancorado embaixo como sempre"
    hook_top, _, _, _ = _white_box_bounds(renderer, SlideContent(headline=text, role="hook"))
    value_top, _, _, _ = _white_box_bounds(renderer, SlideContent(headline=text, role="value"))
    assert hook_top > value_top


# ---------- Caixas independentes ----------


def test_box_position_moves_only_that_box(renderer):
    """Cada caixa arrasta sozinha — era o que o stack único impedia.

    Com a headline fixada no topo e o corpo no rodapé, as caixas brancas
    precisam ocupar as duas pontas do slide, não um bloco só no meio.
    """
    slide = SlideContent(
        headline="pergunta no topo",
        body="resposta embaixo",
        role="value",
        box_positions={"headline": (0.5, 0.15), "body": (0.5, 0.85)},
    )
    top, bottom, _, _ = _white_box_bounds(renderer, slide)
    assert top < 1350 * 0.25
    assert bottom > 1350 * 0.75


def test_loose_box_does_not_drag_the_others(renderer):
    """Mover uma caixa não pode reposicionar a que ficou no empilhamento."""
    stacked = SlideContent(headline="fica", body="vai embora", role="value")
    base_top, _, _, _ = _white_box_bounds(renderer, stacked)
    moved = SlideContent(
        headline="fica",
        body="vai embora",
        role="value",
        box_positions={"body": (0.5, 0.9)},
    )
    moved_top, _, _, _ = _white_box_bounds(renderer, moved)
    assert moved_top == base_top


def test_box_position_is_clamped_inside_the_canvas(renderer):
    slide = SlideContent(
        headline="uma headline comprida o suficiente para ocupar duas linhas aqui",
        role="value",
        box_positions={"headline": (2.0, -1.0)},
    )
    top, bottom, left, right = _white_box_bounds(renderer, slide)
    assert top >= 0 and left >= 0
    assert bottom < 1350 and right < 1080


def test_box_scale_changes_the_rendered_box(renderer):
    """O resize do editor precisa chegar ao PNG, não só à tela.

    A medida é a ALTURA: com escala maior o texto pode reagrupar em mais
    linhas e sair mais estreito, mas nunca mais baixo.
    """
    text = "curto"
    top_plain, bottom_plain, left_plain, right_plain = _white_box_bounds(
        renderer, SlideContent(headline=text, role="value")
    )
    top_big, bottom_big, left_big, right_big = _white_box_bounds(
        renderer, SlideContent(headline=text, role="value", box_scales={"headline": 1.6})
    )
    assert (bottom_big - top_big) > (bottom_plain - top_plain)
    assert (right_big - left_big) > (right_plain - left_plain)


# ---------- Uma caixa por linha, colada na linha ----------


def _white_row_runs(img, x_step: int = 4) -> list[tuple[int, int]]:
    """Faixas verticais contínuas de branco — uma por BLOCO desenhado."""
    runs, start = [], None
    for y in range(img.height):
        white = any(
            img.getpixel((x, y)) == (255, 255, 255)
            for x in range(0, img.width, x_step)
        )
        if white and start is None:
            start = y
        elif not white and start is not None:
            runs.append((start, y - 1))
            start = None
    if start is not None:
        runs.append((start, img.height - 1))
    return runs


def _line_box_widths(renderer, text: str, key: str = "headline"):
    """Largura da caixa branca de CADA linha (+ linhas, fonte e draw) no PNG.

    As caixas de linhas vizinhas se sobrepõem, então uma linha só aparece
    sozinha na última fatia antes de a próxima começar — é onde a amostra é
    tirada.
    """
    from PIL import ImageDraw

    slide = SlideContent(**{key: text}, role="value")
    img = _open(
        renderer.render_single(slide, None, style="sticker").png_bytes
    ).convert("RGB")
    draw = ImageDraw.Draw(img)
    _, lines, font = renderer._fit_sticker_blocks(
        draw, [(key, text)], max_width=int(1080 * renderer._STICKER_TEXT_WIDTH_RATIO)
    )[0]
    pitch = renderer._sticker_line_pitch(font)
    top = _white_row_runs(img, x_step=1)[0][0]

    widths = []
    for i in range(len(lines)):
        y = top + pitch * (i + 1) - 2
        xs = [x for x in range(img.width) if img.getpixel((x, y)) == (255, 255, 255)]
        assert xs, f"linha {i} sem caixa branca na altura {y}"
        widths.append(xs[-1] - xs[0])
    return widths, lines, font, draw


def test_each_line_gets_a_box_of_its_own_width(renderer):
    """A caixa acompanha a linha — é o que a referência do TikTok mostra.

    Uma caixa só para o bloco inteiro dava a largura da linha MAIS LONGA a
    todas as outras: nas linhas curtas sobrava um vão branco de cada lado, o
    "espaço sobrando" que o photo post nativo não tem.
    """
    text = "things i wish someone told me before i started posting..."
    widths, lines, font, draw = _line_box_widths(renderer, text)
    assert len(lines) > 1, "o texto precisa quebrar para este teste valer"

    for width, line in zip(widths, lines):
        expected = renderer._sticker_line_width(draw, line, font)
        # ±6px: a borda arredondada come alguns pixels nas pontas da amostra.
        assert abs(width - expected) < 6, (
            f"caixa de {width}px para a linha {line!r} (esperado {expected}px)"
        )

    # E a linha curta tem mesmo uma caixa menor — o sintoma que o usuário viu.
    assert min(widths) < max(widths) * 0.9


def test_lines_form_one_continuous_white_band(renderer):
    """As caixas se encostam: nada da foto aparece entre uma linha e outra.

    Caixas por linha com folga entre elas viravam retângulos soltos, com uma
    listra da foto no meio da frase.
    """
    text = (
        "there were weeks i was posting every single day, trying different "
        "trends, switching hooks, adding text, all of it and still barely "
        "getting views."
    )
    slide = SlideContent(headline=text, role="value")
    img = _open(renderer.render_single(slide, None, style="sticker").png_bytes).convert("RGB")

    from PIL import ImageDraw

    draw = ImageDraw.Draw(img)
    _, lines, _ = renderer._fit_sticker_blocks(
        draw, [("headline", text)], max_width=int(1080 * renderer._STICKER_TEXT_WIDTH_RATIO)
    )[0]
    assert len(lines) > 1, "o texto precisa quebrar para este teste valer"
    assert len(_white_row_runs(img)) == 1


def test_no_line_is_covered_by_the_next_box(renderer):
    """As caixas se sobrepõem — o texto não pode ser desenhado antes delas.

    Desenhando caixa+texto linha a linha, a caixa da linha seguinte cobria o
    rabo dos "g"/"p" da linha anterior.
    """
    text = "paging paging paging longa o suficiente para quebrar em duas linhas"
    slide = SlideContent(headline=text, role="value")
    img = _open(renderer.render_single(slide, None, style="sticker").png_bytes).convert("RGB")

    from PIL import ImageDraw

    draw = ImageDraw.Draw(img)
    _, lines, font = renderer._fit_sticker_blocks(
        draw, [("headline", text)], max_width=int(1080 * renderer._STICKER_TEXT_WIDTH_RATIO)
    )[0]
    assert len(lines) > 1, "o texto precisa quebrar para este teste valer"

    pitch = renderer._sticker_line_pitch(font)
    top = _white_row_runs(img, x_step=1)[0][0]
    # A tinta da primeira linha tem de sobreviver até onde os descendentes vão,
    # ou seja, além do topo da caixa da segunda linha.
    ink_rows = [
        y for y in range(top, top + pitch * 2)
        if any(sum(img.getpixel((x, y))) < 200 for x in range(img.width))
    ]
    assert max(ink_rows) > top + pitch, "os descendentes da 1ª linha foram cobertos"


def test_each_block_keeps_its_own_box(renderer):
    """Caixa única por bloco, não uma caixa só para o slide inteiro.

    A independência das caixas é o que permite arrastar e redimensionar cada
    uma; fundi-las resolveria o serrilhado e quebraria o editor.
    """
    slide = SlideContent(
        headline="uma headline que ocupa mais de uma linha neste slide de teste",
        body="um corpo de texto separado, também com mais de uma linha para valer",
        role="value",
    )
    img = _open(renderer.render_single(slide, None, style="sticker").png_bytes).convert("RGB")
    assert len(_white_row_runs(img)) == 2


def test_box_width_follows_the_longest_line(renderer):
    """A caixa abraça a linha mais longa — sem sobra em relação à tinta."""
    from PIL import ImageDraw

    text = "uma frase comprida o bastante para quebrar em duas linhas aqui"
    slide = SlideContent(headline=text, role="value")
    _, _, box_left, box_right = _white_box_bounds(renderer, slide)

    img = _open(renderer.render_single(slide, None, style="sticker").png_bytes).convert("RGB")
    draw = ImageDraw.Draw(img)
    _, lines, font = renderer._fit_sticker_blocks(
        draw, [("headline", text)], max_width=int(1080 * renderer._STICKER_TEXT_WIDTH_RATIO)
    )[0]
    widest = max(_ink_width(draw, line, font) for line in lines)
    pad_x = renderer._sticker_padding(font)[0]
    # ±8px: a amostragem do _white_box_bounds anda de 4 em 4 px.
    assert abs((box_right - box_left) - (widest + pad_x * 2)) < 8


def test_text_runs_close_to_the_photo_margin(renderer):
    """A linha só quebra perto da margem — antes ela quebrava cedo demais."""
    text = "uma frase longa que deveria ocupar a largura útil do slide inteiro"
    slide = SlideContent(headline=text, role="value")
    _, _, left, right = _white_box_bounds(renderer, slide)
    assert (right - left) > 1080 * 0.75


def test_the_box_never_passes_the_useful_width(renderer):
    """O limite de 88% é da CAIXA, não da tinta.

    Medindo só o texto, a etiqueta saía com 88% + dois paddings (~93% do
    canvas) e passava da margem da foto — e a prévia, onde o limite é da caixa,
    quebrava a linha antes do PNG.
    """
    from PIL import ImageDraw

    draw = ImageDraw.Draw(Image.new("RGB", (1080, 1350)))
    max_width = int(1080 * renderer._STICKER_TEXT_WIDTH_RATIO)
    textos = [
        "things i wish someone told me before i started posting...",
        "there were weeks i was posting every single day, trying different "
        "trends, switching hooks, adding text, all of it and still barely "
        "getting views.",
        "ninguém acorda às 5h por disciplina, acorda porque dormiu às 21h",
    ]
    for texto in textos:
        _, lines, font = renderer._fit_sticker_blocks(
            draw, [("headline", texto)], max_width=max_width
        )[0]
        widest = max(renderer._sticker_line_width(draw, line, font) for line in lines)
        assert widest <= max_width, (
            f"caixa de {widest}px passa da largura útil ({max_width}px): {texto!r}"
        )


# ---------- Caixa colada no texto ----------


def test_box_hugs_the_text_without_leftover_space(renderer):
    """A caixa branca é uma etiqueta na frase, não um bloco com sobra.

    Mede a folga entre a borda da caixa e a tinta do texto: com a caixa
    dimensionada pela métrica da fonte (ascent+descent) sobravam ~35% do corpo
    da fonte em cima e embaixo, e o slide não parecia o photo post nativo.
    """
    from PIL import ImageDraw

    slide = SlideContent(headline="Altura", role="value")
    img = _open(renderer.render_single(slide, None, style="sticker").png_bytes).convert("RGB")

    box_top, box_bottom, box_left, box_right = _white_box_bounds(renderer, slide)
    # Linhas/colunas onde existe tinta preta (o texto).
    ink_rows = [
        y for y in range(box_top, box_bottom + 1)
        if any(sum(img.getpixel((x, y))) < 200 for x in range(box_left, box_right + 1))
    ]
    ink_cols = [
        x for x in range(box_left, box_right + 1)
        if any(sum(img.getpixel((x, y))) < 200 for y in range(box_top, box_bottom + 1))
    ]
    assert ink_rows and ink_cols, "nenhum texto preto dentro da caixa"

    draw = ImageDraw.Draw(img)
    sized = renderer._fit_sticker_blocks(draw, [("headline", "Altura")], max_width=800)
    size = sized[0][2].size
    # A folga é o padding pedido (±4px de amostragem), não o vão da métrica.
    assert (ink_rows[0] - box_top) < size * 0.30
    assert (box_bottom - ink_rows[-1]) < size * 0.30
    assert (ink_cols[0] - box_left) < size * 0.42
    assert (box_right - ink_cols[-1]) < size * 0.42


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

