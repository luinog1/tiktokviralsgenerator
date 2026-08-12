"""Testes do modo manual: um bloco de roteiro por imagem do carrossel."""

from __future__ import annotations

import pytest

from app.adapters.script_parser import (
    blocks_from_slides,
    compose_from_blocks,
    labeled_blocks,
    parse_manual_script,
    split_blocks,
)


def test_blocks_keep_the_order_they_were_written():
    carousel = compose_from_blocks([
        "Ninguém acorda às 5h por disciplina",
        "Acorda porque dormiu às 21h",
        "Comece pela hora de dormir",
    ])

    assert [s.headline for s in carousel.slides] == [
        "Ninguém acorda às 5h por disciplina",
        "Acorda porque dormiu às 21h",
        "Comece pela hora de dormir",
    ]
    assert [s.order for s in carousel.slides] == [0, 1, 2]
    assert carousel.provider == "manual"


def test_first_block_is_always_the_hook():
    carousel = compose_from_blocks(["Bloco um", "Bloco dois", "Bloco três"])

    assert carousel.slides[0].role == "hook"
    assert carousel.slides[-1].role == "cta"


def test_six_blocks_get_the_canonical_viral_roles():
    carousel = compose_from_blocks([f"Bloco {i}" for i in range(1, 7)])

    roles = [s.role for s in carousel.slides]
    assert len(roles) == 6
    assert roles[0] == "hook"
    assert roles[-1] == "cta"


def test_text_is_kept_verbatim_no_invented_cta():
    """Modo manual não inventa texto: o que foi escrito é o que vai pro PNG."""
    carousel = compose_from_blocks(["Só isso", "E mais isso"])

    assert carousel.slides[0].headline == "Só isso"
    assert carousel.slides[0].body == ""
    assert all(s.call_to_action == "" for s in carousel.slides)


def test_first_line_is_headline_and_rest_is_body():
    carousel = compose_from_blocks([
        "o hook",
        "A headline curta\nO corpo explicando melhor",
    ])

    assert carousel.slides[1].headline == "A headline curta"
    assert carousel.slides[1].body == "O corpo explicando melhor"


def test_the_hook_image_shows_one_box_and_nothing_else():
    """A imagem 1 é a frase do hook — sem apoio, sem CTA, numa caixa só."""
    carousel = compose_from_blocks([
        "ninguém acorda às 5h por disciplina\nacorda porque dormiu às 21h",
        "o resto do roteiro",
    ])

    hook = carousel.slides[0]
    assert hook.role == "hook"
    assert hook.body == ""
    assert hook.call_to_action == ""
    # O apoio não é descartado: ele entra na mesma caixa, colado à frase.
    assert hook.headline == (
        "ninguém acorda às 5h por disciplina acorda porque dormiu às 21h"
    )


def test_the_hook_is_not_cut_at_the_headline_limit():
    """A caixa única do hook cabe mais que uma headline de slide comum."""
    long_hook = "palavra " * 15  # ~105 caracteres, acima do limite de headline
    carousel = compose_from_blocks([long_hook, "segundo bloco"])

    assert len(carousel.slides[0].headline) > 70
    assert len(carousel.slides[0].headline) <= 160


def test_empty_blocks_are_dropped_and_shrink_the_carousel():
    """Preencheu 3 dos 6 campos: quer 3 imagens, não 3 slides em branco."""
    carousel = compose_from_blocks(["Um", "", "  ", "Dois", "", "Três"], slides_count=6)

    assert len(carousel.slides) == 3
    assert [s.headline for s in carousel.slides] == ["Um", "Dois", "Três"]
    assert [s.order for s in carousel.slides] == [0, 1, 2]
    assert carousel.slides[0].role == "hook"


def test_no_blocks_at_all_is_an_empty_carousel():
    carousel = compose_from_blocks(["", "   ", "\n"])

    assert carousel.slides == []
    assert carousel.provider == "manual"


def test_hashtags_move_from_the_text_to_the_carousel():
    carousel = compose_from_blocks(["Rotina matinal #produtividade", "Fecho #foco"])

    assert "produtividade" in carousel.hashtags
    assert "foco" in carousel.hashtags


def test_headline_is_truncated_not_dropped():
    carousel = compose_from_blocks(["o hook", "palavra " * 40])

    assert len(carousel.slides[1].headline) <= 70
    assert carousel.slides[1].headline.startswith("palavra")


def test_never_calls_an_llm():
    """Sem provider, sem rede, sem chave: o texto já é a decisão do usuário."""
    carousel = compose_from_blocks(["Um", "Dois"])

    assert carousel.provider == "manual"


# ---------------------------------------------- roteiro colado numa caixa só
def test_labels_split_the_pasted_script():
    carousel = parse_manual_script(
        "Imagem 1: para de postar todo dia\n"
        "o alcance não vem da frequência\n"
        "\n"
        "Imagem 2: o que ninguém te conta\n"
        "\n"
        "Imagem 3: salva esse post"
    )

    assert [s.headline for s in carousel.slides] == [
        # Imagem 1 é o hook: as duas linhas do bloco viram uma caixa só.
        "para de postar todo dia o alcance não vem da frequência",
        "o que ninguém te conta",
        "salva esse post",
    ]
    assert carousel.slides[0].body == ""


def test_label_number_wins_over_position_in_the_text():
    """Quem reordenou os blocos espera que a numeração mande."""
    blocks = split_blocks("Imagem 3: terceiro\nImagem 1: primeiro\nImagem 2: segundo")

    assert blocks == ["primeiro", "segundo", "terceiro"]


def test_accepts_the_label_spellings_people_actually_type():
    for text in (
        "Foto 1: um\nFoto 2: dois",
        "slide 1 - um\nslide 2 - dois",
        "1) um\n2) dois",
        "IMAGEM 1: um\nIMAGEM 2: dois",
    ):
        assert split_blocks(text) == ["um", "dois"], text


def test_horizontal_rule_splits_when_there_are_no_labels():
    """É como o goviral.ai separa as partes do roteiro."""
    blocks = split_blocks("primeiro bloco\n---\nsegundo bloco\n---\nterceiro")

    assert blocks == ["primeiro bloco", "segundo bloco", "terceiro"]


@pytest.mark.parametrize("rule", ["---", "***", "===", "___"])
def test_accepts_the_rule_styles_markdown_uses(rule):
    assert split_blocks(f"um\n{rule}\ndois") == ["um", "dois"]


def test_a_hyphen_bullet_is_not_mistaken_for_a_rule():
    """"- item" é lista, não separador — só a linha 100% feita de traços conta."""
    assert split_blocks("- item um\n- item dois") == ["- item um", "- item dois"]


def test_blank_lines_split_when_there_are_no_labels():
    blocks = split_blocks("primeiro bloco\nsegunda linha\n\nsegundo bloco")

    assert blocks == ["primeiro bloco\nsegunda linha", "segundo bloco"]


def test_preamble_before_the_first_label_is_discarded():
    """O título do documento colado não deveria virar a imagem 1."""
    blocks = split_blocks("Roteiro do carrossel — versão final\n\nImagem 1: um\nImagem 2: dois")

    assert blocks == ["um", "dois"]


def test_single_paragraph_becomes_one_image_per_line():
    blocks = split_blocks("linha um\nlinha dois\nlinha três")

    assert blocks == ["linha um", "linha dois", "linha três"]


def test_empty_text_produces_no_blocks():
    assert split_blocks("") == []
    assert split_blocks("   \n\n  ") == []
    assert parse_manual_script("").slides == []


def test_crlf_from_windows_clipboard_splits_the_same():
    assert split_blocks("Imagem 1: um\r\nImagem 2: dois") == ["um", "dois"]


def test_slides_round_trip_back_into_blocks():
    """Reabrir o briefing repopula os campos com o que já estava escrito."""
    blocks = blocks_from_slides([
        {"headline": "o hook", "body": "o apoio"},
        {"headline": "só a headline", "body": ""},
    ])

    assert blocks == ["o hook\no apoio", "só a headline"]
    # Recompor devolve o mesmo carrossel: o bloco 1 é o hook e volta numa caixa
    # só, sem o apoio ressuscitar como segunda caixa.
    recomposed = compose_from_blocks(blocks)
    assert recomposed.slides[0].headline == "o hook o apoio"
    assert recomposed.slides[0].body == ""


# ------------------------------------- o rótulo diz a imagem, a linha a caixa
def test_a_note_in_parentheses_is_part_of_the_label():
    """"Imagem 1 (hook): frase" — a nota orienta quem escreve, não vai na foto.

    Sem isso o rótulo inteiro deixava de ser reconhecido: a frase virava
    preâmbulo (descartada) ou entrava na imagem com "Imagem 1 (hook):" colado
    nela.
    """
    blocks = split_blocks(
        "Imagem 1 (hook): para de acordar às 5h\n"
        "Imagem 2 (problema): você dormiu à 1h"
    )

    assert blocks == ["para de acordar às 5h", "você dormiu à 1h"]


def test_the_label_can_be_alone_on_its_line():
    """"Imagem 2:" com o texto embaixo — exigir texto na mesma linha fazia o
    rótulo virar corpo do bloco anterior."""
    blocks = split_blocks("Imagem 1:\no hook\n\nImagem 2:\no segundo bloco")

    assert blocks == ["o hook", "o segundo bloco"]


def test_a_blank_line_inside_a_labeled_block_splits_the_boxes():
    """Uma imagem, duas caixas: é o que a linha em branco indica no roteiro."""
    carousel = parse_manual_script(
        "Imagem 1: o hook\n"
        "\n"
        "Imagem 2: a primeira caixa\n"
        "\n"
        "a segunda caixa"
    )

    assert carousel.slides[1].headline == "a primeira caixa"
    assert carousel.slides[1].body == "a segunda caixa"


def test_a_box_can_have_more_than_one_line():
    """A caixa reencaixa o texto na largura do slide, então as duas linhas da
    mesma caixa saem como uma frase — e não como caixas diferentes."""
    carousel = parse_manual_script(
        "Imagem 1: o hook\n"
        "\n"
        "Imagem 2: primeira linha da caixa\n"
        "segunda linha da mesma caixa\n"
        "\n"
        "a caixa de baixo"
    )

    assert carousel.slides[1].headline == (
        "primeira linha da caixa segunda linha da mesma caixa"
    )
    assert carousel.slides[1].body == "a caixa de baixo"


def test_two_blank_lines_separate_images_and_one_separates_boxes():
    """O roteiro colado sem rótulo: o intervalo maior é imagem nova.

    Tratar toda linha em branco como imagem nova dobrava o carrossel e punha a
    segunda caixa de cada script numa imagem só dela.
    """
    carousel = parse_manual_script(
        "o hook\n"
        "\n\n"
        "primeira caixa da imagem 2\n"
        "\n"
        "segunda caixa da imagem 2\n"
        "\n\n"
        "primeira caixa da imagem 3\n"
        "\n"
        "segunda caixa da imagem 3"
    )

    assert len(carousel.slides) == 3
    assert carousel.slides[0].headline == "o hook"
    assert carousel.slides[0].body == ""
    assert carousel.slides[1].headline == "primeira caixa da imagem 2"
    assert carousel.slides[1].body == "segunda caixa da imagem 2"
    assert carousel.slides[2].headline == "primeira caixa da imagem 3"
    assert carousel.slides[2].body == "segunda caixa da imagem 3"


def test_the_hook_image_stays_one_box_even_with_a_blank_line():
    """A imagem 1 é uma caixa: duas caixas ali não é opção, é erro de digitação."""
    carousel = parse_manual_script("Imagem 1: o hook\n\ne mais isso\n\n\nImagem 2: outro")

    assert carousel.slides[0].headline == "o hook e mais isso"
    assert carousel.slides[0].body == ""


def test_a_time_at_the_start_of_a_line_is_not_a_label():
    """"5:30 da manhã" é texto do roteiro, não "imagem 5"."""
    blocks = split_blocks("5:30 da manhã eu já tinha desistido\n\n6:00 recomecei")

    assert blocks == ["5:30 da manhã eu já tinha desistido", "6:00 recomecei"]


def test_labeled_blocks_only_answers_when_the_labels_are_there():
    """É o sinal que autoriza pular o composer — adivinhar aqui seria pior."""
    assert labeled_blocks("Imagem 1: um\nImagem 2: dois") == ["um", "dois"]
    assert labeled_blocks("um texto corrido\n\ncom dois parágrafos") == []
    assert labeled_blocks("") == []


def test_the_label_typed_inside_the_field_does_not_reach_the_slide():
    """Quem cola no campo "Imagem 2" cola o rótulo junto; ele não é texto."""
    carousel = compose_from_blocks([
        "Imagem 1: o hook",
        "Imagem 2: o segundo bloco",
    ])

    assert carousel.slides[0].headline == "o hook"
    assert carousel.slides[1].headline == "o segundo bloco"

