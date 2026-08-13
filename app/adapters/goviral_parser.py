"""O painel do goviral.ai colado inteiro — Hook + Script N + Paragraph 1/2.

O que o goviral.ai entrega não é texto corrido: o painel já mostra o hook
separado e, para cada script, dois parágrafos em caixas próprias. Essa estrutura
é a do carrossel — o hook na imagem 1, cada script numa imagem, o parágrafo 1 na
caixa de cima e o parágrafo 2 na de baixo.

Chegar até aqui era trabalho manual: um clique de copiar por caixa (onze deles
num roteiro de cinco scripts) e um paste por campo do formulário. Colar o painel
inteiro na caixa única não resolvia — o texto não traz os rótulos `Imagem N:`,
então ele seguia para o composer LLM redistribuir, que é justamente a chance de
o hook voltar colado no texto de outro slide.

    Hook                       → imagem 1, uma caixa só
    Script 1 / Position 1
      Paragraph 1: ...         → imagem 2, caixa de cima
      Paragraph 2: ...         → imagem 2, caixa de baixo
    Script 2 / Position 2      → imagem 3

A saída é a mesma lista de blocos que o modo "roteiro por imagem" já consome
(`compose_from_blocks`), com a linha em branco separando as duas caixas: nenhum
caminho novo de render, e nenhum LLM no meio — os rótulos do painel são a
decisão de distribuição, do mesmo jeito que `Imagem N:` é.

O parser é linha a linha e tolerante ao que o clipboard traz junto (cabeçalho da
página, "Position N", texto de botão). Tudo o que vem antes do rótulo `Hook` é
preâmbulo e é descartado — a mesma regra do `_split_by_labels` no `script_parser`,
e o que dispensa manter uma lista de todo texto de interface que possa aparecer
no topo da página.

Reconhecido pela metade não conta: sem o rótulo `Hook`, sem texto no hook ou sem
nenhum script com texto, `blocks()` devolve `[]` e o chamador segue com os
caminhos de sempre. Um painel adivinhado sairia com o hook na imagem errada, e
isso o usuário só descobre olhando o carrossel gerado.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Os rótulos do painel. Todos exigem que a linha SEJA o rótulo — "Hook",
# "Hook:" ou "Hook: a frase" — e nunca "hook that stops the scroll": um rótulo
# reconhecido no meio de uma frase abriria uma seção nova e cortaria o texto do
# usuário em dois. Por isso o texto na mesma linha só vale depois do ":".
_HOOK_RE = re.compile(
    r"^[ \t]*(?:hook|gancho)[ \t]*(?::[ \t]*(?P<text>.*))?$",
    re.IGNORECASE,
)
_SCRIPT_RE = re.compile(
    r"^[ \t]*(?:script|roteiro)[ \t]*#?[ \t]*(?P<n>\d{1,2})[ \t]*"
    r"(?::[ \t]*(?P<text>.*))?$",
    re.IGNORECASE,
)
_POSITION_RE = re.compile(
    r"^[ \t]*(?:position|posi(?:ção|cao))[ \t]*#?[ \t]*(?P<n>\d{1,2})"
    r"[ \t]*:?[ \t]*$",
    re.IGNORECASE,
)
_PARAGRAPH_RE = re.compile(
    r"^[ \t]*(?:paragraph|par(?:á|a)grafo)[ \t]*#?[ \t]*(?P<n>\d{1,2})[ \t]*"
    r"(?::[ \t]*(?P<text>.*))?$",
    re.IGNORECASE,
)

# Interface que aparece DEPOIS do rótulo Hook e não é texto do roteiro. O que
# vem antes do Hook não precisa estar aqui — é preâmbulo e já foi descartado.
_NOISE_RE = re.compile(
    r"^[ \t]*(?:scripts?|copy|copiar|copied!?|copiado!?|new content)[ \t]*$",
    re.IGNORECASE,
)

@dataclass
class GoviralScript:
    """Um script do painel: as duas caixas de uma imagem do carrossel."""

    number: int
    position: int | None = None
    # Uma entrada por caixa. O rótulo `Paragraph N` ABRE a caixa (vazia, se o
    # texto vier em outra linha); linha sem rótulo preenche — ver `fill`.
    chunks: list[str] = field(default_factory=list)

    def open_chunk(self, text: str | None) -> None:
        """Um rótulo `Paragraph N` abre uma caixa; o texto pode vir depois."""
        self.chunks.append(" ".join(str(text or "").split()))

    def fill(self, line: str) -> None:
        """Linha sem rótulo: a primeira caixa aberta vazia, senão a última.

        As duas formas de colar precisam dessa ordem de preferência:

        - Rótulos antes dos textos (o painel em duas colunas): `Paragraph 1:` e
          `Paragraph 2:` chegam abertos e vazios, e os dois textos seguintes
          preenchem cada um o seu — por ordem.
        - Parágrafo quebrado em várias linhas: a caixa aberta já tem texto,
          então a linha CONTINUA nela, em vez de vazar para a caixa de baixo.
        """
        value = " ".join(line.split())
        if not value:
            return
        for i, chunk in enumerate(self.chunks):
            if not chunk:
                self.chunks[i] = value
                return
        if self.chunks:
            self.chunks[-1] = f"{self.chunks[-1]} {value}"
        else:
            self.chunks.append(value)

    def block(self) -> str:
        """O bloco no formato do roteiro por imagem.

        A linha em branco é a fronteira entre as duas caixas daquela imagem (ver
        `_split_headline_body` no `script_parser`). Um parágrafo a mais entra na
        caixa de baixo em vez de virar imagem nova: o painel mostra duas caixas
        por script, e criar uma imagem para o excedente mudaria o número de
        fotos do carrossel sem o usuário ter pedido.
        """
        chunks = [c for c in self.chunks if c]
        if not chunks:
            return ""
        tail = " ".join(chunks[1:])
        return f"{chunks[0]}\n\n{tail}" if tail else chunks[0]


@dataclass
class GoviralPaste:
    """O painel lido: o hook e os scripts, na ordem em que as imagens saem."""

    hook_chunks: list[str] = field(default_factory=list)
    scripts: list[GoviralScript] = field(default_factory=list)
    # Os dois rótulos que provam que o texto é o painel, e não um roteiro
    # qualquer que por acaso escreve a palavra "hook" numa linha sozinha.
    saw_hook_label: bool = False
    saw_script_label: bool = False

    @property
    def hook(self) -> str:
        """A imagem 1 é uma caixa só, então o hook sai numa linha.

        Linha que sobrou na seção do hook entra na frase em vez de ser
        descartada: é a mesma escolha do `enforce_hook_slide` para o texto que o
        usuário escreveu — um hook comprido é visível e corrigível na prévia,
        texto que some sem aviso não é. O teto de 160 caracteres é aplicado
        depois, pelo `hook_box_text`.
        """
        return " ".join(" ".join(self.hook_chunks).split())

    @property
    def recognized(self) -> bool:
        """Painel reconhecido: os dois rótulos, hook com texto e script com texto."""
        if not (self.saw_hook_label and self.saw_script_label):
            return False
        return bool(self.hook) and any(s.block() for s in self.scripts)

    def ordered_scripts(self) -> list[GoviralScript]:
        """A ordem das imagens: `Position N` quando o painel a traz em todos.

        "Position" é o campo com que o painel diz a posição no carrossel — quando
        ele existe, ele é a resposta, e o número do script é só o nome do bloco.
        As duas ordenações são estáveis, então um painel sem numeração nenhuma
        sai na ordem em que foi colado.
        """
        if self.scripts and all(s.position is not None for s in self.scripts):
            return sorted(self.scripts, key=lambda s: s.position or 0)
        return sorted(self.scripts, key=lambda s: s.number)

    def blocks(self) -> list[str]:
        """Um bloco por imagem: o hook e cada script. `[]` se não reconhecido."""
        if not self.recognized:
            return []
        blocks = [self.hook]
        blocks.extend(b for b in (s.block() for s in self.ordered_scripts()) if b)
        return blocks


def parse_goviral(raw_text: str) -> GoviralPaste:
    """Lê o painel colado. Nunca levanta — texto que não é painel sai vazio."""
    text = (raw_text or "").replace("\r\n", "\n").replace("\r", "\n")
    paste = GoviralPaste()
    current: GoviralScript | None = None
    in_hook = False

    for line in text.split("\n"):
        hook = _HOOK_RE.match(line)
        if hook:
            paste.saw_hook_label = True
            in_hook = True
            current = None
            _append(paste.hook_chunks, hook.group("text"))
            continue

        # Preâmbulo: cabeçalho da página, saudação, "Sign Out". Descartado de
        # propósito — senão o título do painel viraria a imagem 1.
        if not paste.saw_hook_label:
            continue

        if not line.strip() or _NOISE_RE.match(line):
            continue

        script = _SCRIPT_RE.match(line)
        if script:
            paste.saw_script_label = True
            in_hook = False
            current = GoviralScript(number=int(script.group("n")))
            paste.scripts.append(current)
            # Texto grudado no cabeçalho ("Script 1: frase") já é a primeira
            # caixa; sem texto, quem abre as caixas são os rótulos de parágrafo.
            if (script.group("text") or "").strip():
                current.open_chunk(script.group("text"))
            continue

        position = _POSITION_RE.match(line)
        if position:
            # "Position N" vem depois do cabeçalho do script, então ela só
            # anota a posição do bloco que já está aberto.
            if current is not None and current.position is None:
                current.position = int(position.group("n"))
            continue

        paragraph = _PARAGRAPH_RE.match(line)
        if paragraph:
            paste.saw_script_label = True
            in_hook = False
            # Painel copiado sem os cabeçalhos "Script N": quem abre a imagem é
            # o parágrafo 1, porque a numeração reinicia em cada script.
            if current is None or (paragraph.group("n") == "1" and current.chunks):
                current = GoviralScript(number=len(paste.scripts) + 1)
                paste.scripts.append(current)
            current.open_chunk(paragraph.group("text"))
            continue

        if current is not None:
            current.fill(line)
        elif in_hook:
            _append(paste.hook_chunks, line)

    return paste


def _append(target: list[str], text: str | None) -> None:
    """Guarda o texto da linha na seção do hook, se houver texto."""
    value = " ".join(str(text or "").split())
    if value:
        target.append(value)


def goviral_blocks(raw_text: str) -> list[str]:
    """Blocos por imagem quando o texto é o painel do goviral. `[]` se não for.

    É o mesmo contrato do `labeled_blocks`: devolver blocos aqui é afirmar que a
    distribuição pelas imagens já está decidida no texto, e que nenhum LLM
    precisa entrar. Quem chama não precisa saber se veio do painel ou dos
    rótulos `Imagem N:` — a lista de blocos é a mesma.
    """
    return parse_goviral(raw_text).blocks()


def is_goviral_paste(raw_text: str) -> bool:
    """O texto é um painel do goviral reconhecível?"""
    return parse_goviral(raw_text).recognized


__all__ = [
    "GoviralPaste",
    "GoviralScript",
    "goviral_blocks",
    "is_goviral_paste",
    "parse_goviral",
]
