"""O painel do goviral colado inteiro — hook + scripts viram as imagens.

O texto usado aqui é o painel real (Hook, Script N, Position N, Paragraph 1/2),
com o cabeçalho da página que vem junto no Ctrl+A: é ele que o parser precisa
descartar sem ajuda de uma lista de textos de interface.
"""

from __future__ import annotations

from app.adapters.goviral_parser import (
    goviral_blocks,
    is_goviral_paste,
    parse_goviral,
)
from app.adapters.script_parser import compose_from_blocks

# O painel como o Ctrl+A/Ctrl+C entrega: cabeçalho, saudação e "Sign Out" antes
# do rótulo Hook, e o rótulo de cada parágrafo numa linha própria.
DASHBOARD = """V
Social Media Content
Welcome, luinog_76469
Sign Out
Content Dashboard
Last updated: 6/25/2026, 2:35:03 PM
New Content
Hook
i regret posting consistently and here is why i would never do it again...
Scripts
Script 1
Position 1
Paragraph 1:
i was consistent, but i was still guessing.
Paragraph 2:
i posted every day with no plan, no clear promise, and no repeatable format.
Script 2
Position 2
Paragraph 1:
the quiet phase fooled me into panic changes.
Paragraph 2:
when growth stayed slow, i switched topics and styles instead of stacking signals.
Script 3
Position 3
Paragraph 1:
my real mistake was posting blind.
Paragraph 2:
i hit post before my hook was clear and before the payoff matched the promise.
"""

def test_panel_becomes_one_block_per_image():
    blocks = goviral_blocks(DASHBOARD)

    # Hook + 3 scripts = 4 imagens. O nº de imagens é do painel, não de um
    # seletor: é isso que a ferramenta automatiza.
    assert len(blocks) == 4
    assert is_goviral_paste(DASHBOARD) is True


def test_hook_is_the_first_image_and_one_line():
    blocks = goviral_blocks(DASHBOARD)

    assert blocks[0] == (
        "i regret posting consistently and here is why i would never do it again..."
    )
    # A imagem 1 é uma caixa só — nada de linha em branco abrindo uma segunda.
    assert "\n" not in blocks[0]


def test_the_two_paragraphs_become_the_two_boxes():
    blocks = goviral_blocks(DASHBOARD)

    assert blocks[1] == (
        "i was consistent, but i was still guessing."
        "\n\n"
        "i posted every day with no plan, no clear promise, and no repeatable format."
    )


def test_page_chrome_before_the_hook_is_dropped():
    """Tudo antes do rótulo Hook é preâmbulo — inclusive o que não está numa
    lista de textos conhecidos, que é o ponto de descartar por posição."""
    joined = "\n".join(goviral_blocks(DASHBOARD))

    for chrome in (
        "Content Dashboard",
        "Last updated",
        "Welcome",
        "Sign Out",
        "Social Media Content",
    ):
        assert chrome not in joined


def test_labels_never_reach_the_slide():
    joined = "\n".join(goviral_blocks(DASHBOARD))

    for label in ("Hook", "Script 1", "Position 1", "Paragraph 1", "Paragraph 2"):
        assert label not in joined


def test_paragraph_text_on_the_same_line_as_the_label():
    """Copiar caixa por caixa (o botão de copiar do painel) gruda o texto no
    rótulo. As duas formas são o mesmo painel."""
    blocks = goviral_blocks(
        "Hook: a frase que para o scroll\n"
        "Script 1\n"
        "Paragraph 1: a caixa de cima\n"
        "Paragraph 2: a caixa de baixo\n"
    )

    assert blocks == [
        "a frase que para o scroll",
        "a caixa de cima\n\na caixa de baixo",
    ]


def test_both_labels_can_come_before_both_texts():
    """O painel mostra os parágrafos em duas colunas, e o clipboard pode trazer
    os dois rótulos antes dos dois textos. A ordem dos textos é o que decide a
    caixa — o rótulo sozinho não carrega texto para atribuir."""
    blocks = goviral_blocks(
        "Hook\n"
        "a frase\n"
        "Script 1\n"
        "Paragraph 1:\n"
        "Paragraph 2:\n"
        "a caixa de cima\n"
        "a caixa de baixo\n"
    )

    assert blocks[1] == "a caixa de cima\n\na caixa de baixo"


def test_position_decides_the_order_when_the_panel_brings_it():
    """"Position" é o campo com que o painel diz a posição no carrossel; script
    fora de ordem no texto colado não muda a ordem das imagens."""
    blocks = goviral_blocks(
        "Hook\n"
        "a frase\n"
        "Script 2\n"
        "Position 2\n"
        "Paragraph 1: segunda imagem de script\n"
        "Script 1\n"
        "Position 1\n"
        "Paragraph 1: primeira imagem de script\n"
    )

    assert blocks[1] == "primeira imagem de script"
    assert blocks[2] == "segunda imagem de script"


def test_script_number_orders_when_there_is_no_position():
    blocks = goviral_blocks(
        "Hook\n"
        "a frase\n"
        "Script 3: terceiro\n"
        "Script 2: segundo\n"
    )

    assert blocks[1:] == ["segundo", "terceiro"]


def test_panel_without_script_headers_still_splits_by_paragraph_one():
    """Painel copiado sem os cabeçalhos "Script N": o parágrafo 1 é quem abre a
    imagem, porque a numeração dos parágrafos reinicia em cada script."""
    blocks = goviral_blocks(
        "Hook\n"
        "a frase\n"
        "Paragraph 1: primeira de cima\n"
        "Paragraph 2: primeira de baixo\n"
        "Paragraph 1: segunda de cima\n"
        "Paragraph 2: segunda de baixo\n"
    )

    assert blocks == [
        "a frase",
        "primeira de cima\n\nprimeira de baixo",
        "segunda de cima\n\nsegunda de baixo",
    ]


def test_third_paragraph_goes_to_the_bottom_box_not_a_new_image():
    """O painel mostra duas caixas por script. Um parágrafo a mais entra na
    caixa de baixo: virar imagem nova mudaria o nº de fotos sem pedido."""
    blocks = goviral_blocks(
        "Hook\n"
        "a frase\n"
        "Script 1\n"
        "Paragraph 1: caixa de cima\n"
        "Paragraph 2: caixa de baixo\n"
        "Paragraph 3: sobra\n"
    )

    assert len(blocks) == 2
    assert blocks[1] == "caixa de cima\n\ncaixa de baixo sobra"


def test_a_paragraph_split_across_lines_stays_in_its_box():
    """O clipboard pode quebrar um parágrafo em várias linhas; a continuação
    fica na mesma caixa em vez de vazar para a de baixo."""
    blocks = goviral_blocks(
        "Hook\n"
        "a frase\n"
        "Script 1\n"
        "Paragraph 1:\n"
        "a caixa de cima\n"
        "que continua na linha seguinte\n"
        "Paragraph 2: a caixa de baixo\n"
    )

    assert blocks[1] == (
        "a caixa de cima que continua na linha seguinte\n\na caixa de baixo"
    )


def test_hook_mentioned_mid_text_does_not_open_a_section():
    """"my hook was clear" dentro de um parágrafo não é o rótulo Hook — o
    rótulo só vale quando a linha É o rótulo (com ou sem texto após ':')."""
    blocks = goviral_blocks(
        "Hook\n"
        "a frase\n"
        "Script 1\n"
        "Paragraph 1: i hit post before my hook was clear\n"
        "hook that stops the scroll is rare\n"
    )

    assert len(blocks) == 2
    assert blocks[1] == (
        "i hit post before my hook was clear hook that stops the scroll is rare"
    )


def test_multiline_hook_is_still_one_phrase():
    blocks = goviral_blocks(
        "Hook\n"
        "a primeira linha da frase\n"
        "e a segunda\n"
        "Script 1: um script\n"
    )

    assert blocks[0] == "a primeira linha da frase e a segunda"


# ------------------------- o contrato do reconhecimento: pela metade não conta
def test_text_with_imagem_labels_is_not_a_panel():
    """O formato `Imagem N:` já tem dono (`labeled_blocks`) — o parser do painel
    não pode responder por ele."""
    assert goviral_blocks(
        "Imagem 1: ninguém acorda às 5h\n\nImagem 2: acorda porque dormiu às 21h"
    ) == []


def test_running_text_is_not_a_panel():
    assert is_goviral_paste("um texto corrido que fala de hook e de scripts") is False
    assert goviral_blocks("") == []


def test_hook_without_any_script_is_not_recognized():
    assert goviral_blocks("Hook\numa frase boa\n") == []


def test_scripts_without_the_hook_label_are_not_recognized():
    assert goviral_blocks("Script 1\nParagraph 1: texto\n") == []


def test_hook_label_without_text_is_not_recognized():
    """Rótulo Hook vazio: melhor recusar o painel inteiro do que gerar um
    carrossel cuja imagem 1 recebeu um texto adivinhado."""
    assert goviral_blocks("Hook\nScript 1\nParagraph 1: texto\n") == []


def test_scripts_with_only_empty_boxes_are_not_recognized():
    assert goviral_blocks("Hook\na frase\nScript 1\nParagraph 1:\n") == []


# --------------------------- a saída alimenta o fluxo que já existe, sem tradução
def test_blocks_feed_compose_from_blocks_as_written():
    blocks = goviral_blocks(DASHBOARD)
    carousel = compose_from_blocks(blocks, slides_count=len(blocks))

    assert carousel.provider == "manual"
    assert carousel.slides[0].role == "hook"
    assert carousel.slides[0].headline == (
        "i regret posting consistently and here is why i would never do it again..."
    )
    # A imagem 1 é uma caixa só.
    assert carousel.slides[0].body == ""
    assert carousel.slides[0].call_to_action == ""
    # Paragraph 1 → caixa de cima, Paragraph 2 → caixa de baixo.
    assert carousel.slides[1].headline == "i was consistent, but i was still guessing."
    assert carousel.slides[1].body.startswith("i posted every day with no plan")
    assert len(carousel.slides) == 4
