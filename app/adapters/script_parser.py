"""Modo manual: um bloco de texto por imagem do carrossel.

O LLM reorganiza o texto colado e decide sozinho o que cai em cada slide. Quem
já escreveu o roteiro no goviral.app e quer decidir a ordem à mão não tinha
como — o texto entrava inteiro e voltava fatiado por outro critério.

Aqui o usuário escreve um bloco por imagem, na ordem em que as imagens vão
aparecer. A imagem 1 é sempre o hook; as seguintes recebem os papéis do roteiro
viral na mesma ordem canônica de `viral_script_roles`.

Duas portas de entrada, uma implementação:

- `compose_from_blocks` — os campos "Imagem 1 / Imagem 2 / …" do formulário,
  um bloco já separado por campo.
- `parse_manual_script` — o roteiro colado inteiro numa caixa só, dividido
  antes por rótulo ("Imagem 2:", "Slide 3 —", "4)"), por régua horizontal ou
  pelo intervalo entre os blocos.

O contrato do texto colado é o que o usuário já escrevia à mão:

    Imagem 1: a frase do hook          ← "Imagem 1" é orientação, não texto

    Imagem 2: a primeira caixa
              (linha em branco)
              a segunda caixa

Ou seja: **o rótulo diz em qual imagem o texto entra, e a linha em branco diz
em qual caixa daquela imagem.** Dentro de um bloco sem linha em branco vale a
regra curta — primeira linha na caixa de cima, o resto na de baixo. A **imagem 1
é a exceção**: ela mostra o hook e mais nada, então o bloco inteiro vira uma
caixa só (ver `enforce_hook_slide` no text_composer) — sem apoio e sem CTA.

As duas funções são determinísticas e offline: modo manual nunca chama LLM,
porque o texto já é a decisão do usuário. `labeled_blocks` é o que permite
estender essa garantia ao texto colado no modo automático: com os rótulos
escritos, não há o que um LLM redistribua sem risco de errar.
"""

from __future__ import annotations

import re

# Reuso intra-pacote dos helpers de limpeza do composer — o destino é o mesmo
# SlideContent, então truncar/extrair hashtag tem que se comportar igual.
from app.adapters.text_composer import (
    ComposedCarousel,
    SlideContent,
    _extract_hashtags,
    _truncate,
    hook_box_text,
    viral_script_roles,
)

# "Imagem 1:", "imagem 1 -", "foto 2:", "slide 3 —", "4)" ou "5." no início da
# linha. O usuário digita o rótulo do jeito que lembra; o parser não deveria
# ser a parte frágil do fluxo.
#
# Três tolerâncias que valem cada caractere de regex, porque um rótulo não
# reconhecido não é um erro visível — é o texto do rótulo indo para dentro da
# foto, ou o bloco inteiro entrando na imagem errada:
#
# - **Nota entre parênteses**: "Imagem 1 (hook): frase". A nota é orientação
#   para quem escreve, não texto do slide, então sai junto com o rótulo.
# - **Rótulo sozinho na linha**: "Imagem 2:" com o texto nas linhas seguintes.
#   Exigir texto na mesma linha fazia o rótulo virar corpo do bloco anterior.
# - **Nada de hora**: o `(?![0-9])` impede que "5:30 da manhã" no começo de uma
#   linha seja lido como "imagem 5". Essa é a única ambiguidade real de exigir
#   menos espaço depois do separador.
_LABEL_RE = re.compile(
    r"^[ \t]*(?:(?:imagem|image|foto|photo|slide)[ \t]*)?(\d{1,2})[ \t]*"
    r"(?:\([^)\n]*\)[ \t]*[:.)\-–—]?|[:.)\-–—](?![0-9]))[ \t]*",
    re.IGNORECASE,
)

# Régua horizontal sozinha numa linha ("---", "***", "===", "___"). É como o
# goviral.ai separa as partes do roteiro, e como quem escreve em Markdown separa
# seções. Sem isso a régua virava um bloco de texto e entrava numa imagem.
_RULE_RE = re.compile(r"^[ \t]*[-*=_]{3,}[ \t]*$", re.MULTILINE)

# DUAS ou mais linhas em branco: o intervalo maior separa IMAGENS, enquanto uma
# linha em branco sozinha separa as caixas dentro da mesma imagem. É a distinção
# que o roteiro colado já carregava e que o parser jogava fora — sem ela, cada
# caixa virava uma imagem e o carrossel saía com o dobro de slides, o hook
# colado no texto do slide seguinte.
_IMAGE_GAP_RE = re.compile(r"\n[ \t]*\n(?:[ \t]*\n)+")

# Linha em branco sozinha — a fronteira entre a primeira e a segunda caixa.
_BOX_GAP_RE = re.compile(r"\n[ \t]*\n")

# Mesmos limites do LLMTextComposer — o PNG é o mesmo, só o caminho até ele muda.
_HEADLINE_LIMIT = 70
_BODY_LIMIT = 280


def compose_from_blocks(
    blocks: list[str],
    *,
    slides_count: int | None = None,
) -> ComposedCarousel:
    """Um bloco por imagem, na ordem escrita, virando slides do carrossel.

    Blocos vazios são descartados: quem preencheu 4 dos 6 campos quer um
    carrossel de 4 imagens, não 2 slides em branco no meio.
    """
    filled = [_strip_label(b) for b in blocks if b and b.strip()]
    filled = [block for block in filled if block]
    if not filled:
        return ComposedCarousel(provider="manual")

    total = slides_count or len(filled)
    roles = viral_script_roles(max(total, len(filled)))

    slides: list[SlideContent] = []
    for block in filled:
        order = len(slides)
        role = roles[order] if order < len(roles) else "value"
        # A imagem 1 é o hook e sai numa caixa só: o bloco inteiro vira a
        # frase, em vez de virar headline + apoio. Por isso ele não passa pelo
        # corte de 70 caracteres da headline — quem escreveu duas linhas de
        # hook fica com as duas.
        headline, body = (
            (hook_box_text(block), "") if role == "hook"
            else _split_headline_body(block)
        )
        if not headline and not body:
            continue
        slides.append(
            SlideContent(
                headline=headline,
                body=body,
                # O CTA continua sendo campo próprio, editável na prévia. Aqui
                # não inventamos um: o texto escrito à mão é o que vale.
                call_to_action="",
                order=order,
                role=role,
            )
        )

    if not slides:
        return ComposedCarousel(provider="manual")

    return ComposedCarousel(
        slides=slides,
        hashtags=_extract_hashtags("\n".join(filled)),
        caption=_truncate(slides[0].headline or filled[0], 200),
        provider="manual",
    )


def parse_manual_script(
    raw_text: str,
    *,
    slides_count: int | None = None,
) -> ComposedCarousel:
    """Roteiro colado inteiro numa caixa só — divide e compõe."""
    return compose_from_blocks(split_blocks(raw_text), slides_count=slides_count)


def split_blocks(raw_text: str) -> list[str]:
    """Separa o texto em um bloco por imagem.

    Cinco estratégias, em ordem de quanto o usuário foi explícito: rótulos
    "Imagem N:", régua horizontal (`---`, `***`, `===`), intervalo de duas
    linhas em branco, uma linha em branco, e uma imagem por linha quando o texto
    é um parágrafo corrido de linhas curtas.

    Um bloco devolvido aqui pode conter linha em branco: ali ela separa as
    CAIXAS daquela imagem (ver `_split_headline_body`), não as imagens.
    """
    text = (raw_text or "").replace("\r\n", "\n").strip()
    if not text:
        return []

    labeled = _split_by_labels(text)
    if labeled:
        return labeled

    ruled = [p.strip() for p in _RULE_RE.split(text) if p.strip()]
    if len(ruled) > 1:
        return ruled

    # Intervalo maior = imagem nova; a linha em branco sozinha fica no bloco e
    # vira a segunda caixa.
    gapped = [_tidy_block(p) for p in _IMAGE_GAP_RE.split(text)]
    gapped = [block for block in gapped if block]
    if len(gapped) > 1:
        return gapped

    paragraphs = [p.strip() for p in _BOX_GAP_RE.split(text) if p.strip()]
    if len(paragraphs) > 1:
        return paragraphs
    return [ln.strip() for ln in text.split("\n") if ln.strip()] or [text]


def labeled_blocks(raw_text: str) -> list[str]:
    """Blocos só quando o texto TRAZ os rótulos "Imagem N". `[]` se não trouxer.

    É o sinal que autoriza a pular o composer: com os rótulos escritos, a
    distribuição pelas imagens é uma decisão que o usuário já tomou, e um LLM
    que "melhore" essa distribuição só tem como errá-la. Sem rótulo nenhum,
    devolver blocos aqui seria adivinhar — o texto corrido segue para o
    composer, como sempre.
    """
    text = (raw_text or "").replace("\r\n", "\n").strip()
    return _split_by_labels(text) if text else []


def _split_by_labels(text: str) -> list[str]:
    """Agrupa as linhas por rótulo numerado. [] se não houver rótulo algum."""
    entries: list[tuple[int, list[str]]] = []
    for line in text.split("\n"):
        match = _LABEL_RE.match(line)
        if match:
            entries.append((int(match.group(1)), [line[match.end():].strip()]))
        elif entries:
            # A linha em branco entra no bloco: dentro de uma imagem ela é a
            # fronteira entre as duas caixas. Descartá-la, como acontecia aqui,
            # colava a segunda caixa na primeira.
            entries[-1][1].append(line.strip())
        # Linha antes do primeiro rótulo é preâmbulo — descartada de propósito,
        # senão o título do documento colado viraria a imagem 1.

    if not entries:
        return []
    # O número do rótulo manda na ordem: quem reordenou os blocos no editor
    # espera que a numeração vença a posição no texto.
    entries.sort(key=lambda entry: entry[0])
    blocks = [_tidy_block("\n".join(parts)) for _, parts in entries]
    return [block for block in blocks if block]


def _tidy_block(block: str) -> str:
    """Normaliza o bloco: no máximo uma linha em branco entre as caixas."""
    return re.sub(r"\n{3,}", "\n\n", block).strip()


def _strip_label(block: str) -> str:
    """Tira o rótulo "Imagem N:" escrito dentro do campo daquela imagem.

    O campo já diz de qual imagem ele é, mas quem cola o roteiro inteiro cola o
    rótulo junto — e ele iria para dentro da foto como texto. Só a primeira
    linha é examinada: um número no meio do bloco é conteúdo.
    """
    lines = block.split("\n")
    match = _LABEL_RE.match(lines[0])
    if match:
        lines[0] = lines[0][match.end():]
    return _tidy_block("\n".join(lines))


def _one_line(text: str) -> str:
    """Colapsa quebras e espaços — a caixa reencaixa o texto na largura do slide.

    Uma quebra escrita à mão não sobrevive ao render, e deixá-la viraria espaço
    duplo no meio da frase. Mesmo motivo do `hook_box_text`.
    """
    return " ".join(text.split())


def _split_headline_body(block: str) -> tuple[str, str]:
    """Duas caixas por imagem: a linha em branco é a fronteira entre elas.

    Cada trecho vira uma caixa de texto no slide, que é o que o roteiro colado
    já indicava com a linha em branco. Sem linha em branco vale a regra curta:
    primeira linha = caixa de cima, o resto = caixa de baixo.
    """
    chunks = [c for c in _BOX_GAP_RE.split(block) if c.strip()]
    if len(chunks) > 1:
        head, rest = chunks[0], chunks[1:]
    else:
        lines = [ln.strip() for ln in block.split("\n") if ln.strip()]
        if not lines:
            return "", ""
        head, rest = lines[0], lines[1:]
    return (
        _truncate(_one_line(head), _HEADLINE_LIMIT),
        _truncate(_one_line(" ".join(rest)), _BODY_LIMIT),
    )


def blocks_from_slides(slides: list[dict]) -> list[str]:
    """Volta de slides para blocos — repopula os campos ao reabrir o briefing."""
    blocks: list[str] = []
    for slide in slides:
        headline = str(slide.get("headline") or "").strip()
        body = str(slide.get("body") or "").strip()
        blocks.append(f"{headline}\n{body}".strip() if body else headline)
    return blocks


__all__ = [
    "compose_from_blocks",
    "parse_manual_script",
    "split_blocks",
    "labeled_blocks",
    "blocks_from_slides",
]
