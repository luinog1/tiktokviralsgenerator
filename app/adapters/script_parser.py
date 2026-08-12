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
  antes por rótulo ("Imagem 2:", "Slide 3 —", "4)") ou por linha em branco.

Dentro de um bloco, a primeira linha vira headline e o resto vira body. Uma
linha só = headline sozinha. A **imagem 1 é a exceção**: ela mostra o hook e
mais nada, então o bloco inteiro vira uma caixa só (ver `enforce_hook_slide`
no text_composer) — sem texto de apoio e sem CTA.

As duas funções são determinísticas e offline: modo manual nunca chama LLM,
porque o texto já é a decisão do usuário.
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
_LABEL_RE = re.compile(
    r"^\s*(?:(?:imagem|image|foto|photo|slide)\s*)?(\d{1,2})\s*[:.)\-–—]\s+",
    re.IGNORECASE,
)

# Régua horizontal sozinha numa linha ("---", "***", "===", "___"). É como o
# goviral.ai separa as partes do roteiro, e como quem escreve em Markdown separa
# seções. Sem isso a régua virava um bloco de texto e entrava numa imagem.
_RULE_RE = re.compile(r"^[ \t]*[-*=_]{3,}[ \t]*$", re.MULTILINE)

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
    filled = [b.strip() for b in blocks if b and b.strip()]
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

    Quatro estratégias, em ordem de quanto o usuário foi explícito: rótulos
    "Imagem N:", régua horizontal (`---`, `***`, `===`), linhas em branco, e
    uma imagem por linha quando o texto é um parágrafo corrido de linhas curtas.
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

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if len(paragraphs) > 1:
        return paragraphs
    return [ln.strip() for ln in text.split("\n") if ln.strip()] or [text]


def _split_by_labels(text: str) -> list[str]:
    """Agrupa as linhas por rótulo numerado. [] se não houver rótulo algum."""
    entries: list[tuple[int, list[str]]] = []
    for line in text.split("\n"):
        match = _LABEL_RE.match(line)
        if match:
            entries.append((int(match.group(1)), [line[match.end():].strip()]))
        elif entries and line.strip():
            entries[-1][1].append(line.strip())
        # Linha antes do primeiro rótulo é preâmbulo — descartada de propósito,
        # senão o título do documento colado viraria a imagem 1.

    if not entries:
        return []
    # O número do rótulo manda na ordem: quem reordenou os blocos no editor
    # espera que a numeração vença a posição no texto.
    entries.sort(key=lambda entry: entry[0])
    return [
        "\n".join(part for part in parts if part).strip()
        for _, parts in entries
        if any(part for part in parts)
    ]


def _split_headline_body(block: str) -> tuple[str, str]:
    """Primeira linha = headline; o resto = body."""
    lines = [ln.strip() for ln in block.split("\n") if ln.strip()]
    if not lines:
        return "", ""
    return (
        _truncate(lines[0], _HEADLINE_LIMIT),
        _truncate(" ".join(lines[1:]).strip(), _BODY_LIMIT),
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
    "blocks_from_slides",
]
