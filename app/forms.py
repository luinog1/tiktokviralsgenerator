"""Formulários WTForms — validação server-side.

Mudança v0.3: o briefing agora pede o TEXTO COLADO do goviral.ai
(ferramenta externa sem API/token, acessada via login Discord pelo usuário).
"""

from __future__ import annotations

from flask_wtf import FlaskForm
from wtforms import (
    FieldList,
    HiddenField,
    SelectField,
    StringField,
    TextAreaField,
)
from wtforms.validators import DataRequired, Length, NumberRange, Optional


STYLE_CHOICES = [
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


class BriefingForm(FlaskForm):
    """Briefing para o carrossel.

    O campo `raw_text` é obrigatório e deve receber o conteúdo que o usuário
    copiou da ferramenta goviral.ai (https://content.goviralai.app/).
    """

    theme = StringField(
        "Tema *",
        validators=[DataRequired(message="Tema é obrigatório."), Length(max=200)],
        render_kw={"placeholder": "Ex.: rotina matinal produtiva", "autofocus": True},
    )
    raw_text = TextAreaField(
        "Texto do goviral.ai *",
        validators=[
            DataRequired(message="Cole o texto gerado no goviral.ai."),
            Length(min=20, max=6000, message="Texto deve ter entre 20 e 6000 caracteres."),
        ],
        render_kw={
            "placeholder": (
                "Cole aqui o texto pronto gerado em https://content.goviralai.app/ "
                "(você acessa manualmente via login Discord). O ViralPost Studio "
                "vai organizar esse texto em slides sobrepostos às imagens."
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

    def to_briefing(self) -> dict:
        keywords = [
            (k.data or "").strip()
            for k in self.keywords.entries
            if (k.data or "").strip()
        ]
        return {
            "theme": (self.theme.data or "").strip(),
            "raw_text": (self.raw_text.data or "").strip(),
            "niche": (self.niche.data or "").strip(),
            "language": (self.language.data or "pt-BR").strip(),
            "style": (self.style.data or "quote").strip(),
            "slides_count": int(self.slides_count.data or 6),
            "keywords": keywords,
        }


class SlideEditForm(FlaskForm):
    """Formulário de edição de cada slide do carrossel."""

    project_id = HiddenField()
    slides = FieldList(
        HiddenField(),
        min_entries=0,
    )
    headlines = FieldList(
        StringField("Headline", validators=[Optional(), Length(max=80)]),
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
            result.append({
                "headline": headline or orig.get("headline", ""),
                "body": body or orig.get("body", ""),
                "call_to_action": cta or orig.get("call_to_action", ""),
                "order": i,
                "image_id": image_id or orig.get("image_id", ""),
            })
        return result
