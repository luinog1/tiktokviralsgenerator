"""Formulários WTForms — validação server-side.

Mudança v0.3: o briefing agora pede o TEXTO COLADO do goviral.ai
(ferramenta externa sem API/token, acessada via login Discord pelo usuário).
"""

from __future__ import annotations

from flask_wtf import FlaskForm
from wtforms import (
    BooleanField,
    FieldList,
    HiddenField,
    SelectField,
    StringField,
    TextAreaField,
)
from wtforms.validators import DataRequired, Length, Optional, ValidationError

from app.adapters.text_composer import viral_script_roles


STYLE_CHOICES = [
    ("sticker", "Sticker TikTok — caixas brancas sobre a foto (recomendado)"),
    ("sticker_outline", "Sticker TikTok — texto branco com contorno preto (black outline)"),
    ("quote", "Citação — texto centralizado, aspas decorativas"),
    ("list", "Lista — bullets à esquerda, headline no topo"),
    ("tutorial", "Tutorial — passo a passo com CTA em caixa"),
    ("story", "História — narrativa com headline grande"),
]

SLIDES_CHOICES = [
    ("3", "3 slides (curto)"),
    ("6", "6 slides (médio)"),
    ("9", "9 slides (longo)"),
    ("12", "12 slides (carrossel completo)"),
]

LANGUAGE_CHOICES = [
    ("pt-BR", "Português (Brasil)"),
    ("en-US", "English (US)"),
    ("es-ES", "Español (España)"),
]

# Fonte das fotos, escolhida por geração. "" mantém o IMAGE_PROVIDER do
# ambiente. As opções de scraping (Pinterest sem token, Instagram e o
# combinado) valem as mesmas ressalvas de compliance do README — a escolha na
# UI é o opt-in.
IMAGE_SOURCE_CHOICES = [
    ("", "Padrão do servidor (IMAGE_PROVIDER)"),
    ("unsplash", "Só Unsplash"),
    ("pinterest_scrape", "Só Pinterest (sem token)"),
    ("instagram_scrape", "Só Instagram (sem token)"),
    ("instagram_pinterest", "Instagram + Pinterest (metade de cada)"),
]

MODE_CHOICES = [
    ("script", "Roteiro por imagem — eu escrevo o texto de cada foto"),
    ("auto", "Automático — o LLM organiza o texto colado em slides"),
]

# Teto de campos de roteiro. Bate com a maior opção de SLIDES_CHOICES: mais que
# isso o formulário renderiza campos que o carrossel nunca usaria.
MAX_SCRIPT_BLOCKS = 12

# Rótulo de cada campo do roteiro, pelo papel do slide naquela posição. O papel
# vem de `viral_script_roles`, a mesma função que decide o papel real no
# carrossel — assim o que o formulário promete é o que o render entrega.
_ROLE_HINTS = {
    "hook": "hook — para o scroll",
    "problem": "problema — nomeia a dor",
    "agitation": "agitação — amplia a consequência",
    "value": "valor — uma ideia só",
    "proof": "prova — número ou resultado",
    "cta": "CTA — uma ação clara",
}


def script_field_labels(slides_count: int) -> list[str]:
    """"Imagem 1 (hook — …)" para cada campo, na ordem do carrossel."""
    roles = viral_script_roles(slides_count)
    return [
        f"Imagem {i + 1} ({_ROLE_HINTS.get(role, role)})"
        for i, role in enumerate(roles)
    ]


class BriefingForm(FlaskForm):
    """Briefing para o carrossel.

    Dois modos, mutuamente exclusivos na validação:

    - `script` (padrão): um campo por imagem. O usuário decide o que vai em cada
      foto e em que ordem; nenhum LLM reescreve por cima.
    - `auto`: o campo `raw_text` recebe o texto do goviral.ai inteiro e o
      composer (LLM ou mock) fatia em slides.
    """

    theme = StringField(
        "Tema *",
        validators=[DataRequired(message="Tema é obrigatório."), Length(max=200)],
        render_kw={"placeholder": "Ex.: rotina matinal produtiva", "autofocus": True},
    )
    script_mode = SelectField(
        "Como montar os slides *",
        choices=MODE_CHOICES,
        default="script",
        validators=[DataRequired(message="Selecione como montar os slides.")],
    )
    # Um bloco por imagem, na ordem em que as imagens aparecem no carrossel.
    # `max_entries` é o teto; o número real de campos vem do slides_count e a
    # FieldList lê do POST quantos vierem.
    slide_scripts = FieldList(
        TextAreaField(
            "Roteiro da imagem",
            validators=[Optional(), Length(max=600)],
        ),
        min_entries=0,
        max_entries=MAX_SCRIPT_BLOCKS,
    )
    raw_text = TextAreaField(
        "Texto do goviral.ai",
        # Sem DataRequired: no modo `script` este campo fica vazio de propósito.
        # A obrigatoriedade por modo está em `validate_raw_text` — um
        # `Optional()` aqui abortaria a cadeia e o validador nunca rodaria.
        validators=[Length(max=6000)],
        render_kw={
            "placeholder": (
                "Cole aqui o texto pronto gerado em https://content.goviralai.app/ "
                "(você acessa manualmente via login Discord).\n\n"
                "Escreva \"Imagem 1:\", \"Imagem 2:\"… na frente de cada trecho "
                "para decidir você mesmo o que entra em cada foto — o rótulo "
                "orienta a montagem e não aparece na imagem. Uma linha em branco "
                "dentro do trecho separa as duas caixas daquela imagem. Sem "
                "rótulo, o texto vai para o LLM organizar em slides."
            ),
            "rows": 10,
        },
    )
    niche = StringField(
        "Nicho",
        validators=[Optional(), Length(max=120)],
        render_kw={"placeholder": "Ex.: produtividade"},
    )
    language = SelectField(
        "Idioma *",
        choices=LANGUAGE_CHOICES,
        validators=[DataRequired(message="Selecione um idioma.")],
    )
    style = SelectField(
        "Estilo visual *",
        choices=STYLE_CHOICES,
        validators=[DataRequired(message="Selecione um estilo.")],
    )
    slides_count = SelectField(
        "Nº de slides *",
        choices=SLIDES_CHOICES,
        # Sem default explícito o select abre em "3" enquanto o formulário
        # renderiza 6 campos de roteiro — o usuário vê uma contradição.
        default="6",
        validators=[DataRequired(message="Selecione o número de slides.")],
    )
    keywords = FieldList(
        StringField(
            "Palavra-chave",
            validators=[Optional(), Length(max=80)],
            render_kw={"placeholder": "Ex.: foco, hábitos"},
        ),
        min_entries=0,
        max_entries=8,
    )
    # Fonte das fotos desta geração. Vazio = IMAGE_PROVIDER do ambiente.
    image_source = SelectField(
        "Fonte das fotos",
        choices=IMAGE_SOURCE_CHOICES,
        default="",
        validators=[Optional()],
    )
    # Só aparece no formulário quando há pessoa fixada (ver template). Desligado
    # por padrão: repetir a pessoa é escolha por carrossel, não estado global.
    use_pinned_person = BooleanField(
        "Buscar mais fotos da pessoa fixada para a imagem 1",
        default=False,
    )

    @property
    def is_script_mode(self) -> bool:
        """Modo roteiro (um bloco por imagem) vs. modo automático (texto único).

        O seletor manda quando o formulário o enviou — é a escolha explícita do
        usuário, e ele pode ter deixado texto nos campos do outro modo. Quando o
        campo não vem no POST (cliente antigo, teste que só manda `raw_text`), o
        modo é inferido do que foi preenchido: exigir um campo que o cliente nem
        sabe que existe transformaria uma requisição válida em 422.
        """
        if self.script_mode.raw_data:
            return (self.script_mode.data or "script") == "script"
        if self._filled_blocks():
            return True
        return not (self.raw_text.data or "").strip()

    def _filled_blocks(self) -> list[str]:
        return [
            (entry.data or "").strip()
            for entry in self.slide_scripts.entries
            if (entry.data or "").strip()
        ]

    def script_blocks(self) -> list[str]:
        """Blocos preenchidos, na ordem dos campos. Vazios ficam de fora."""
        return self._filled_blocks() if self.is_script_mode else []

    def validate_raw_text(self, field: TextAreaField) -> None:
        """Obrigatório só no modo automático — é a entrada dele."""
        if self.is_script_mode:
            return
        text = (field.data or "").strip()
        if not text:
            raise ValidationError("Cole o texto gerado no goviral.ai.")
        if len(text) < 20:
            raise ValidationError(
                "Texto deve ter entre 20 e 6000 caracteres."
            )

    def validate_slide_scripts(self, field: FieldList) -> None:
        """No modo roteiro, o hook e mais um slide são o mínimo viável."""
        if not self.is_script_mode:
            return
        filled = len(self.script_blocks())
        if filled < 2:
            raise ValidationError(
                "Escreva o roteiro de pelo menos 2 imagens (a primeira é o hook)."
            )

    def to_briefing(self) -> dict:
        keywords = [
            (k.data or "").strip()
            for k in self.keywords.entries
            if (k.data or "").strip()
        ]
        blocks = self.script_blocks()
        # No modo roteiro o raw_text costuma vir vazio, mas a busca de imagens, o
        # ranking e a visão usam esse campo como corpus do tema. Os blocos são o
        # melhor corpus disponível ali.
        raw_text = (self.raw_text.data or "").strip() or "\n\n".join(blocks)
        return {
            "theme": (self.theme.data or "").strip(),
            "raw_text": raw_text,
            "niche": (self.niche.data or "").strip(),
            "language": (self.language.data or "pt-BR").strip(),
            "style": (self.style.data or "quote").strip(),
            "slides_count": int(self.slides_count.data or 6),
            "keywords": keywords,
            "script_mode": "script" if self.is_script_mode else "auto",
            "script_blocks": blocks,
            "use_pinned_person": bool(self.use_pinned_person.data),
            "image_source": (self.image_source.data or "").strip(),
        }


class GoviralForm(FlaskForm):
    """O painel do goviral colado inteiro — a ferramenta de um campo.

    O que essa tela automatiza é justamente o que o `BriefingForm` pede em
    pedaços: o número de imagens e a distribuição do texto entre elas saem do
    próprio painel (`goviral_parser`), então aqui só sobra o que o painel não
    tem — o tema da busca de fotos e o estilo visual. Nem `slides_count` nem
    `script_mode` aparecem: escolher um número que contradiga o painel seria a
    forma mais fácil de errar o carrossel.
    """

    raw_text = TextAreaField(
        "Painel do goviral (Hook + Scripts) *",
        validators=[
            DataRequired(message="Cole o painel do goviral."),
            Length(max=12000),
        ],
        render_kw={
            "placeholder": (
                "Selecione o painel inteiro no goviral.ai (Ctrl+A, Ctrl+C) e cole "
                "aqui:\n\n"
                "Hook\n"
                "a frase que para o scroll\n"
                "Script 1\n"
                "Position 1\n"
                "Paragraph 1:\n"
                "a caixa de cima\n"
                "Paragraph 2:\n"
                "a caixa de baixo"
            ),
            "rows": 14,
            "autofocus": True,
        },
    )
    theme = StringField(
        "Tema da busca de fotos",
        validators=[Optional(), Length(max=200)],
        render_kw={"placeholder": "Ex.: rotina matinal produtiva"},
    )
    style = SelectField(
        "Estilo visual *",
        choices=STYLE_CHOICES,
        default="sticker",
        validators=[DataRequired(message="Selecione um estilo.")],
    )
    keywords = StringField(
        "Palavras-chave",
        validators=[Optional(), Length(max=200)],
        render_kw={"placeholder": "separadas por vírgula: foco, hábitos"},
    )
    # Mesmo seletor do BriefingForm: a fonte vale para ESTA geração.
    image_source = SelectField(
        "Fonte das fotos",
        choices=IMAGE_SOURCE_CHOICES,
        default="",
        validators=[Optional()],
    )
    # Mesmo comportamento do checkbox no BriefingForm: opt-in por carrossel.
    use_pinned_person = BooleanField(
        "Buscar mais fotos da pessoa fixada para a imagem 1",
        default=False,
    )

    def keyword_list(self) -> list[str]:
        """As palavras-chave num campo só, separadas por vírgula.

        A FieldList do briefing existe para o formulário completo; aqui um campo
        de texto entrega o mesmo resultado sem JS de adicionar/remover linha. O
        teto de 8 é o mesmo do `BriefingForm`.
        """
        return [
            part.strip()
            for part in (self.keywords.data or "").split(",")
            if part.strip()
        ][:8]


class SlideEditForm(FlaskForm):
    """Formulário de edição de cada slide do carrossel."""

    project_id = HiddenField()
    slides = FieldList(
        HiddenField(),
        min_entries=0,
    )
    headlines = FieldList(
        # 200 e não 80: no slide de hook a caixa única guarda a frase inteira
        # (`HOOK_TEXT_LIMIT` = 160), e um limite menor aqui reprovaria na
        # prévia um texto que a geração acabou de produzir.
        StringField("Headline", validators=[Optional(), Length(max=200)]),
        min_entries=0,
    )
    bodies = FieldList(
        TextAreaField("Texto", validators=[Optional(), Length(max=400)]),
        min_entries=0,
    )
    ctas = FieldList(
        StringField("CTA", validators=[Optional(), Length(max=100)]),
        min_entries=0,
    )
    selected_image_ids = FieldList(
        HiddenField(),
        min_entries=0,
    )
    # Posição do bloco de texto, gravada pelo arraste na prévia. Formato
    # "x,y" em fração do canvas (0..1). Vazio = posição padrão do papel.
    text_positions = FieldList(
        HiddenField(),
        min_entries=0,
    )
    # Posição de CADA caixa, quando o usuário arrasta uma sozinha. Formato
    # "headline:x,y;body:x,y;cta:x,y" — só as caixas movidas aparecem.
    box_positions = FieldList(
        HiddenField(),
        min_entries=0,
    )
    # Escala de cada caixa, do controle de tamanho na prévia. Mesmo formato,
    # com um número só: "headline:1.2;body:1".
    box_scales = FieldList(
        HiddenField(),
        min_entries=0,
    )

    def to_edited_slides(self, original_slides: list[dict]) -> list[dict]:
        """Mescla os campos editados com a estrutura original."""
        result = []
        for i, orig in enumerate(original_slides):
            headline = (
                self.headlines[i].data.strip() if i < len(self.headlines.entries) else orig.get("headline", "")
            )
            body = (
                self.bodies[i].data.strip() if i < len(self.bodies.entries) else orig.get("body", "")
            )
            cta = (
                self.ctas[i].data.strip() if i < len(self.ctas.entries) else orig.get("call_to_action", "")
            )
            image_id = (
                self.selected_image_ids[i].data if i < len(self.selected_image_ids.entries) else ""
            )
            raw_pos = (
                self.text_positions[i].data if i < len(self.text_positions.entries) else ""
            )
            pos_x, pos_y = _parse_position(raw_pos)
            raw_boxes = (
                self.box_positions[i].data if i < len(self.box_positions.entries) else ""
            )
            raw_scales = (
                self.box_scales[i].data if i < len(self.box_scales.entries) else ""
            )
            role = orig.get("role", "value")
            slide = {
                "headline": headline or orig.get("headline", ""),
                "body": body or orig.get("body", ""),
                "call_to_action": cta or orig.get("call_to_action", ""),
                "order": i,
                "image_id": image_id or orig.get("image_id", ""),
                # O papel no roteiro viral não é editável — preservar o original.
                "role": role,
                # Sem arraste, o campo vem vazio e o slide volta à âncora do papel.
                "pos_x": pos_x,
                "pos_y": pos_y,
                # Ajustes por caixa. Vazios = a caixa segue o bloco.
                "box_positions": _parse_box_positions(raw_boxes),
                "box_scales": _parse_box_scales(raw_scales),
            }
            # O slide de hook é uma caixa só. A prévia já entrega apoio e CTA
            # como leitura apenas, então aqui não se perde edição nenhuma — é a
            # trava contra um POST montado à mão, que reintroduziria as caixas
            # que a imagem 1 não deve ter.
            if role == "hook":
                slide["body"] = ""
                slide["call_to_action"] = ""
            result.append(slide)
        return result


__all__ = [
    "BriefingForm",
    "GoviralForm",
    "SlideEditForm",
    "STYLE_CHOICES",
    "SLIDES_CHOICES",
    "LANGUAGE_CHOICES",
    "IMAGE_SOURCE_CHOICES",
    "MODE_CHOICES",
    "MAX_SCRIPT_BLOCKS",
    "script_field_labels",
    "BOX_KEYS",
    "MIN_BOX_SCALE",
    "MAX_BOX_SCALE",
]


def _parse_position(raw: str | None) -> tuple[float | None, float | None]:
    """Lê o par "x,y" gravado pelo arraste na prévia. Inválido → sem posição."""
    if not raw:
        return None, None
    parts = str(raw).split(",")
    if len(parts) != 2:
        return None, None
    try:
        x, y = float(parts[0]), float(parts[1])
    except ValueError:
        return None, None
    if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
        return None, None
    return round(x, 4), round(y, 4)


# Caixas que a prévia pode ajustar sozinhas. Qualquer outra chave que chegue no
# POST é descartada — o hidden é editável pelo cliente.
BOX_KEYS = ("headline", "body", "cta")

# Limites do controle de tamanho. Abaixo de 0.5 o texto some no feed; acima de
# 2.5 uma linha sozinha não caberia na largura do slide.
MIN_BOX_SCALE = 0.5
MAX_BOX_SCALE = 2.5


def _iter_box_entries(raw: str | None):
    """Fatia "headline:...;body:..." em pares (chave, valor)."""
    for chunk in str(raw or "").split(";"):
        key, _, value = chunk.partition(":")
        key = key.strip().lower()
        if key in BOX_KEYS and value.strip():
            yield key, value.strip()


def _parse_box_positions(raw: str | None) -> dict[str, list[float]]:
    """Lê "headline:x,y;cta:x,y" — o arraste de cada caixa isolada."""
    positions: dict[str, list[float]] = {}
    for key, value in _iter_box_entries(raw):
        x, y = _parse_position(value)
        if x is not None and y is not None:
            positions[key] = [x, y]
    return positions


def _parse_box_scales(raw: str | None) -> dict[str, float]:
    """Lê "headline:1.2;body:0.9" — o controle de tamanho de cada caixa."""
    scales: dict[str, float] = {}
    for key, value in _iter_box_entries(raw):
        try:
            scale = float(value)
        except ValueError:
            continue
        if MIN_BOX_SCALE <= scale <= MAX_BOX_SCALE and scale != 1.0:
            scales[key] = round(scale, 3)
    return scales
