"""A prévia (CSS) e o PNG (Pillow) desenham o mesmo sticker — mesmos números.

A caixa branca do editor é feita em CSS e a do arquivo exportado em Pillow. São
duas implementações da MESMA geometria, e já divergiram na prática: a prévia
ficou com as caixas separadas por linha enquanto o PNG saía contínuo, porque o
`line-height` estava só no inline e o "strut" do bloco (herdado do `body`, 1.5)
mandava no passo entre as linhas.

Nada aqui abre um navegador: o teste lê os números declarados no CSS e compara
com as constantes do renderer. É o suficiente para pegar as duas regressões que
aconteceram de verdade — passo maior que a caixa (pilha dividida) e razão
corpo/largura fora da do PNG (quebra de linha diferente da exportada).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.config import Settings
from app.services.slide_renderer import SlideRenderer

CSS_PATH = Path(__file__).resolve().parent.parent / "static" / "css" / "style.css"


@pytest.fixture(scope="module")
def css() -> str:
    return CSS_PATH.read_text(encoding="utf-8")


def _rule(css: str, selector: str) -> str:
    """Corpo do primeiro bloco cujo seletor contém `selector`."""
    for match in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        if selector in match.group(1):
            return match.group(2)
    raise AssertionError(f"seletor não encontrado no CSS: {selector}")


def _decl(body: str, prop: str) -> str:
    """Último valor declarado da propriedade (o que vence na cascata)."""
    found = re.findall(rf"(?<![-\w]){re.escape(prop)}\s*:\s*([^;]+);", body)
    assert found, f"propriedade {prop} ausente em: {body.strip()[:120]}"
    return found[-1].strip()


def _em(value: str) -> float:
    return float(re.sub(r"em$", "", value.strip()))


@pytest.fixture(scope="module")
def renderer():
    return SlideRenderer(Settings.from_env({}))


def test_preview_line_pitch_matches_the_png(css, renderer):
    """O passo entre linhas é o mesmo número nos dois desenhos."""
    box = _rule(css, ".slide-text-box")
    assert float(_decl(box, "line-height")) == pytest.approx(
        renderer._STICKER_LINE_PITCH_RATIO, abs=0.005
    )


def test_the_pitch_is_declared_on_the_block_not_only_on_the_inline(css):
    """Foi assim que a prévia apareceu com uma caixa solta por linha.

    A altura de uma linha é a união do strut do BLOCO com os inlines dentro
    dela. Com `line-height` só no inline, o strut herda o 1.5 do `body`, o passo
    passa a ser maior que a caixa branca e a pilha se divide. A família também
    precisa estar no bloco: strut e inline com métricas diferentes esticam a
    linha mesmo com a line-height certa.
    """
    box = _rule(css, ".slide-text-box")
    assert "line-height" in box, "o passo precisa estar no contêiner, não só no texto"
    assert "font-family" in box, "o strut precisa da mesma fonte do texto"


def test_the_white_box_is_taller_than_the_pitch(css):
    """Caixa > passo é o que faz a pilha ser uma mancha contínua.

    Se a caixa couber no passo, as linhas encostam sem se sobrepor e qualquer
    arredondamento abre um vão — que foi o sintoma relatado.
    """
    text = _rule(css, ".slide-visual-sticker .slide-headline")
    pad_y = _em(_decl(text, "padding").split()[0])
    # Content area de um inline = ascent + descent da fonte (1.3em na TikTok
    # Sans, conferido em ImageFont.getmetrics()).
    box_height = 1.3 + pad_y * 2
    pitch = float(_decl(_rule(css, ".slide-text-box"), "line-height"))
    assert box_height > pitch, (
        f"caixa de {box_height:.3f}em não cobre o passo de {pitch:.3f}em"
    )


def test_the_box_is_painted_per_line(css):
    """`box-decoration-break: clone` é o que dá uma caixa por linha.

    Sem ele o fundo vira um retângulo só, com a largura da linha mais longa, e
    volta a sobrar branco dos lados das linhas curtas.
    """
    text = _rule(css, ".slide-visual-sticker .slide-headline")
    assert _decl(text, "display") == "inline"
    assert _decl(text, "box-decoration-break") == "clone"
    assert _decl(text, "background") == "#fff"


def test_preview_font_ratio_wraps_like_the_png(css, renderer):
    """Mesma razão corpo-da-fonte / largura útil — senão a quebra difere.

    `cqw` mede o content box do contêiner, que é exatamente a largura útil onde
    o PNG quebra a linha.
    """
    box = _rule(css, ".slide-text-box")
    cqw = float(re.search(r"([\d.]+)cqw", _decl(box, "font-size")).group(1))
    useful = int(1080 * renderer._STICKER_TEXT_WIDTH_RATIO)
    assert cqw / 100 == pytest.approx(renderer._STICKER_BASE_SIZE / useful, rel=0.01)


def test_preview_padding_matches_the_png(css, renderer):
    """A folga em volta da linha é a mesma fração do corpo da fonte."""
    text = _rule(css, ".slide-visual-sticker .slide-headline")
    pad_y, pad_x = (_em(v) for v in _decl(text, "padding").split())
    assert pad_x == pytest.approx(renderer._STICKER_PAD_X_RATIO, abs=0.01)
    assert pad_y == pytest.approx(renderer._STICKER_PAD_Y_RATIO, abs=0.01)
    radius = _em(_decl(text, "border-radius"))
    assert radius == pytest.approx(renderer._STICKER_RADIUS_RATIO, abs=0.01)
