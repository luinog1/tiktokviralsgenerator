"""TextComposer — divide o texto colado (vindo do goviral.ai) em slides.

O usuário cola o texto gerado pela ferramenta externa goviral.ai
(https://content.goviralai.app/), acessada manualmente via login Discord.
Este módulo NÃO chama o goviral.ai — apenas estrutura o texto já pronto.

Dois modos:
- mock: divisão determinística por sentenças/parágrafos.
- llm:   usa endpoint compatível com Groq (openai-compatible) para refinar os slides.
         Se o endpoint não estiver configurado ou falhar, cai para mock.

Saída é sempre uma lista de slide dicts com headline + body + cta opcional.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Protocol

import requests

from app.config import Settings

logger = logging.getLogger(__name__)


@dataclass
class SlideContent:
    """Um slide do carrossel: headline curta + corpo + CTA opcional.

    `role` indica a função do slide dentro do roteiro viral
    (hook / problem / agitation / value / proof / cta) — usado pelo
    SlideRenderer para posicionar o texto na imagem.

    `pos_x`/`pos_y` são o centro do bloco de texto em fração do canvas (0..1),
    definidos quando o usuário arrasta as caixas na prévia. `None` mantém a
    posição padrão do papel no roteiro.

    `box_positions` e `box_scales` são o ajuste por CAIXA — chaves "headline",
    "body" e "cta". No photo post do TikTok os blocos não andam juntos: a
    pergunta fica no topo da foto e a resposta embaixo, cada uma no seu espaço
    limpo. Uma caixa com posição própria sai do empilhamento e vale por si; as
    demais continuam seguindo `pos_x`/`pos_y` ou a âncora do papel.
    """

    headline: str
    body: str = ""
    call_to_action: str = ""
    order: int = 0
    role: str = "value"
    pos_x: float | None = None
    pos_y: float | None = None
    # {"headline": (0.5, 0.22), ...} — centro daquela caixa em fração do canvas.
    box_positions: dict[str, tuple[float, float]] = field(default_factory=dict)
    # {"headline": 1.15, ...} — multiplicador do corpo da fonte daquela caixa.
    box_scales: dict[str, float] = field(default_factory=dict)
    # Foto escolhida para este slide. Preenchido pelo casting (hook = pessoa,
    # demais = cenário) e depois pela galeria da prévia. Vazio = a prévia cai na
    # rotação `i % len(images)`.
    image_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "headline": self.headline,
            "body": self.body,
            "call_to_action": self.call_to_action,
            "order": self.order,
            "role": self.role,
            "pos_x": self.pos_x,
            "pos_y": self.pos_y,
            "box_positions": {
                key: [x, y] for key, (x, y) in self.box_positions.items()
            },
            "box_scales": dict(self.box_scales),
            "image_id": self.image_id,
        }


@dataclass
class ComposedCarousel:
    """Resultado da composição: lista ordenada de slides + metadados."""

    slides: list[SlideContent] = field(default_factory=list)
    hashtags: list[str] = field(default_factory=list)
    caption: str = ""
    provider: str = "unknown"

    def to_dict(self) -> dict[str, Any]:
        return {
            "slides": [s.to_dict() for s in self.slides],
            "hashtags": list(self.hashtags),
            "caption": self.caption,
            "provider": self.provider,
        }


class TextComposer(Protocol):
    """Interface para composição de carrossel a partir de texto bruto."""

    name: str

    def compose(
        self,
        raw_text: str,
        *,
        style: str = "quote",
        slides_count: int = 6,
        extra: dict[str, Any] | None = None,
    ) -> ComposedCarousel:  # pragma: no cover
        ...


# ---------- helpers de limpeza ----------

_BULLET_RE = re.compile(r"^\s*([•\-\*\u2022]|(\d+\.)|\(\d+\))\s+", re.MULTILINE)
_HASHTAG_RE = re.compile(r"(^|\s)(#[\wÀ-ÿ]+)")
_SENTENCE_END_RE = re.compile(r"(?<=[.!?])\s+")


def _clean(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    # Normaliza bullets (mantém a frase, remove o marcador)
    text = _BULLET_RE.sub(r"", text)
    # Colapsa múltiplos espaços / quebras
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _extract_hashtags(text: str) -> list[str]:
    matches = _HASHTAG_RE.findall(text)
    tags: list[str] = []
    for _, tag in matches:
        clean_tag = tag.lstrip("#").strip()
        if clean_tag and clean_tag.lower() not in {t.lower() for t in tags}:
            tags.append(clean_tag)
    return tags[:10]


def _split_sentences(text: str) -> list[str]:
    text = text.replace("\n", " ")
    parts = _SENTENCE_END_RE.split(text)
    return [p.strip() for p in parts if p and len(p.strip()) > 3]


def _split_paragraphs(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]


def _truncate(text: str, limit: int) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return cut + "…"


def _spread(items: list[str], slots: int) -> list[list[str]]:
    """Reparte os trechos entre `slots` slides, o último ficando com as sobras.

    Menos trechos que slides significa texto curto demais para o carrossel
    pedido: os trechos entram em rotação e os slides que sobrarem saem com o
    texto de espera do `_build_slide`, editável na prévia.
    """
    if slots <= 0:
        return []
    if not items:
        return [[] for _ in range(slots)]
    if len(items) < slots:
        return [[items[i % len(items)]] for i in range(slots)]
    per_slot = len(items) // slots
    return [
        items[i * per_slot :] if i == slots - 1
        else items[i * per_slot : (i + 1) * per_slot]
        for i in range(slots)
    ]


# ---------- roteiro viral (estrutura de 3 atos) ----------
#
# Estrutura clássica de script viral de TikTok:
#   Ato 1 — HOOK (0-3s): para o scroll.
#   Ato 2 — DESENVOLVIMENTO: problema → agitação → valor → prova.
#   Ato 3 — CTA: fecha com uma ação clara.
#
# Cada slide do carrossel recebe um desses papéis. O SlideRenderer usa o papel
# para decidir onde posicionar o texto na imagem (hook fica embaixo e sozinho,
# slides de valor ficam em dois blocos, etc.).

VIRAL_ROLES = ("hook", "problem", "agitation", "value", "proof", "cta")


def viral_script_roles(slides_count: int) -> list[str]:
    """Distribui os papéis do roteiro viral ao longo de N slides."""
    n = max(1, slides_count)
    if n == 1:
        return ["hook"]
    if n == 2:
        return ["hook", "cta"]
    if n == 3:
        return ["hook", "value", "cta"]
    if n == 4:
        return ["hook", "problem", "value", "cta"]
    if n == 5:
        return ["hook", "problem", "value", "value", "cta"]
    # n >= 6 — estrutura completa, com o miolo em slides de valor
    return ["hook", "problem", "agitation"] + ["value"] * (n - 5) + ["proof", "cta"]


def _normalize_role(value: str) -> str:
    role = str(value or "").strip().lower()
    return role if role in VIRAL_ROLES else ""


# ---------- a regra do slide 1 ----------
#
# A primeira foto do carrossel mostra o hook e MAIS NADA: uma caixa, a frase
# que para o scroll. Sem texto de apoio, sem CTA. É o formato do photo post
# nativo — no primeiro quadro o olho tem menos de um segundo para uma frase, e
# qualquer coisa abaixo dela divide essa atenção.
#
# A regra vale nos três caminhos que produzem slides (roteiro escrito à mão,
# composer mock e LLM), então mora aqui, num lugar só. O destino do apoio que
# chegar junto com o hook depende de quem o escreveu — usuário ou modelo — e
# está documentado em `enforce_hook_slide`.
HOOK_TEXT_LIMIT = 160


def hook_box_text(*parts: str) -> str:
    """Junta as partes do hook numa frase só, do tamanho de uma caixa.

    As quebras de linha do texto original somem aqui de propósito: a caixa
    reencaixa o texto na largura do slide, então uma quebra escrita à mão não
    sobreviveria ao render — e deixá-la viraria um espaço duplo no meio da
    frase.
    """
    joined = " ".join(part.strip() for part in parts if part and part.strip())
    return _truncate(" ".join(joined.split()), HOOK_TEXT_LIMIT)


def enforce_hook_slide(slide: SlideContent, *, merge_body: bool = True) -> SlideContent:
    """Colapsa o slide de hook numa caixa só. Outros papéis passam intactos.

    `merge_body` diz o destino do apoio que chegou junto com o hook:
    - `True` (roteiro manual, composer mock): entra na mesma caixa, colado à
      frase — ali o apoio é texto do usuário, e descartar texto escrito é pior
      que um hook comprido.
    - `False` (composer LLM): é apagado. O prompt proíbe body no slide 1; o que
      o modelo escreve ali mesmo assim é excesso dele — a informação continua
      no texto original e nos outros slides — e colar inflava o hook. O body só
      é aproveitado quando veio no LUGAR da headline, para o slide 1 não sair
      em branco.
    """
    if slide.role != "hook":
        return slide
    if merge_body:
        slide.headline = hook_box_text(slide.headline, slide.body)
    else:
        slide.headline = hook_box_text(slide.headline or slide.body)
    slide.body = ""
    slide.call_to_action = ""
    return slide


# CTA padrão por estilo — usado só no slide de fecho (role="cta").
_STYLE_CTA = {
    "sticker": "salva esse post pra não esquecer 🤍",
    "quote": "salva pra reler depois 🤍",
    "list": "salva esse post 🔖",
    "tutorial": "comenta qual passo você vai aplicar 👇",
    "story": "segue para mais conteúdos 💜",
}



# ---------- implementação mock (determinística) ----------


class MockTextComposer:
    """Divisão determinística — funciona sem LLM."""

    name = "mock"

    def compose(
        self,
        raw_text: str,
        *,
        style: str = "quote",
        slides_count: int = 6,
        extra: dict[str, Any] | None = None,
    ) -> ComposedCarousel:
        cleaned = _clean(raw_text)
        if not cleaned:
            return ComposedCarousel(slides=[], provider=self.name)

        hashtags = _extract_hashtags(cleaned)
        # Remove hashtags do corpo para não poluir os slides
        body_text = _HASHTAG_RE.sub("", cleaned).strip()
        # Só espaço e tab. O `\s{2,}` que havia aqui incluía o `\n` e colapsava
        # TODAS as linhas em branco do texto colado: o `_split_paragraphs` abaixo
        # via um parágrafo só, os slides recebiam o texto INTEIRO em rotação e o
        # hook saía com o roteiro colado dentro dele — o sintoma era "o hook
        # juntou com outro texto" e valia para todos os slides de uma vez.
        body_text = re.sub(r"[ \t]{2,}", " ", body_text)
        body_text = re.sub(r"[ \t]*\n[ \t]*", "\n", body_text)

        slides: list[SlideContent] = []
        paragraphs = _split_paragraphs(body_text)

        if paragraphs and len(paragraphs) >= 2:
            chunks = paragraphs
        else:
            sentences = _split_sentences(body_text)
            chunks = sentences if sentences else [body_text]

        # Sempre produzir exatamente `target` slides, mesmo que
        # o texto seja curto — repetimos os chunks em rotação.
        target = max(1, slides_count)
        if not chunks:
            # Sem conteúdo útil — preenche com placeholder
            chunks = ["Conteúdo a ser editado."]

        roles = viral_script_roles(target)

        # O slide 1 é o hook: o PRIMEIRO trecho e nada mais. A divisão anterior
        # repartia os trechos em partes iguais sem reservar esse, então o hook
        # saía com o começo do slide 2 colado — e a regra do hook sozinho, que
        # todo o resto do código respeita, era desfeita aqui na origem.
        slides.append(self._build_slide([chunks[0]], 0, style, roles[0]))
        for i, group in enumerate(_spread(chunks[1:], target - 1), start=1):
            slides.append(self._build_slide(group, i, style, roles[i]))

        caption = self._build_caption(body_text, style)
        return ComposedCarousel(
            slides=slides,
            hashtags=hashtags,
            caption=caption,
            provider=self.name,
        )

    @staticmethod
    def _build_slide(
        parts: list[str], order: int, style: str, role: str = "value"
    ) -> SlideContent:
        """Um slide a partir dos trechos que couberam nele — um por caixa.

        Dois trechos significam que o texto colado tinha uma linha em branco
        entre eles, e é assim que o roteiro indica "isto vai em outra caixa":
        o primeiro trecho fica na caixa de cima e o resto na de baixo. Um
        trecho só volta à regra por sentença — headline = primeira frase — que
        existe para o slide não mostrar a mesma frase duas vezes.
        """
        parts = [p.strip() for p in parts if p and p.strip()]
        if not parts:
            parts = ["Continue para o próximo slide."]
        if len(parts) > 1:
            headline = _truncate(parts[0], 90)
            rest = _truncate(" ".join(parts[1:]), 280)
        else:
            sentences = _split_sentences(parts[0])
            if len(sentences) > 1:
                headline = _truncate(sentences[0], 90)
                rest = _truncate(" ".join(sentences[1:]), 280)
            else:
                headline = _truncate(parts[0], 90)
                rest = ""
        # CTA só no slide de fecho — repetir em todos polui o carrossel.
        cta = _STYLE_CTA.get(style, "comenta abaixo 👇") if role == "cta" else ""
        return enforce_hook_slide(SlideContent(
            headline=headline,
            body=rest,
            call_to_action=cta,
            order=order,
            role=role,
        ))

    @staticmethod
    def _build_caption(body: str, style: str) -> str:
        first_line = body.split("\n")[0].strip()
        if not first_line:
            first_line = "Conteúdo para o seu carrossel."
        return _truncate(first_line, 200)


# ---------- implementação LLM (Groq-compatible, OpenAI-style) ----------


# Estrutura de roteiro viral de TikTok (hook → desenvolvimento → CTA).
# O texto colado do goviral.ai já vem pronto em prosa; o papel do LLM aqui é
# REORDENAR e ENCURTAR esse texto na sequência que retém atenção, não inventar
# conteúdo novo.
#
# O prompt é específico de propósito. Pedir "escreva um hook" devolve a média
# do que existe na internet — "descubra o segredo para transformar sua rotina".
# Nomear os tipos de hook, dar o teto de caracteres e listar o que é proibido
# empurra o modelo para uma frase que arrisca alguma coisa, que é o que para o
# scroll. O mesmo vale para o miolo: sem a regra de uma ideia por slide, o
# modelo empilha três ideias na mesma imagem e o carrossel vira parágrafo.
_VIRAL_GUIDE = """Você é roteirista de carrosséis virais para TikTok (photo post).

Recebe um texto bruto já escrito e o REORGANIZA em {n} slides. Você não cria
conteúdo novo: tudo o que sair já estava no texto — cortado, encurtado e posto
na ordem que segura a atenção.

Cada slide recebe um "role" nesta ordem exata: {roles}

SLIDE 1 — O HOOK, SOZINHO
O primeiro slide é UMA FRASE e nada mais: body vazio, sem CTA, sem hashtag.
É a única coisa que a pessoa lê antes de decidir se desliza, então ele carrega
a tensão do carrossel inteiro — a resposta fica nos slides seguintes.
- até 60 caracteres, o fôlego de uma linha só
- escolha UM tipo e comprometa-se com ele:
  · contrarian — contraria o senso comum ("para de acordar às 5h")
  · omissão — aponta o que ninguém conta ("ninguém fala essa parte")
  · erro — nomeia o erro que o público comete ("você tá salvando e não aplica")
  · número — promessa concreta ("levei 3 anos pra entender isso")
  · história — primeira pessoa, começando no meio da cena ("testei 50 formatos")
- proibido: saudação, contexto, "neste carrossel vou te mostrar", pergunta
  genérica ("já pensou nisso?"), elogio vazio ("incrível", "sensacional")
- o hook diz de que assunto se trata: lido fora de contexto, ainda faz sentido

ATO 2 — DESENVOLVIMENTO (slides do meio)
- problema: nomeia a dor em uma frase, na língua de quem sente
- agitação: a consequência de não resolver
- valor: a entrega concreta — UMA ideia por slide, nunca duas
- prova: número, resultado ou exemplo que já esteja no texto original
- cada slide fecha a sua ideia; nenhuma frase continua no slide seguinte
- não repita a abertura de um slide no outro ("e ainda", "além disso")

ATO 3 — CTA (último slide)
- uma ação só, no imperativo, ligada ao tema ("salva pra tentar amanhã")

REGRAS DE ESCRITA (formato sticker do TikTok):
- Escreva como fala: frases curtas, "você", contrações, tom de conversa.
- Tudo em minúsculas, sem ponto final no fim das frases.
- headline: máx 60 caracteres. É a frase que vai grande na imagem.
- body: máx 180 caracteres, 1 ou 2 frases. VAZIO no slide 1 (role="hook").
- call_to_action: SÓ no último slide (role="cta"). Vazio nos demais.
- Nada de emoji nem hashtag dentro dos slides — eles não aparecem na imagem.
  As hashtags vão no campo "hashtags", que é onde elas são usadas.
- Use os números específicos que estiverem no texto original.
- Idioma da saída: {language}.
- Não invente fatos que não estejam no texto original.

Retorne APENAS JSON válido, sem markdown, neste formato:
"""

_VIRAL_SCHEMA = (
    '{"slides":[{"role":"hook","headline":"","body":"","call_to_action":""}],'
    '"hashtags":["",""],"caption":""}'
)


def _build_viral_prompt(slides_count: int, language: str, roles: list[str]) -> str:
    return _VIRAL_GUIDE.format(
        n=slides_count,
        language=language or "pt-BR",
        roles=" → ".join(roles),
    ) + _VIRAL_SCHEMA


def _viral_max_tokens(slides_count: int) -> int:
    """Orçamento de saída proporcional ao nº de slides, não fixo.

    Um slide ocupa ~90 tokens de JSON (role, headline, body, CTA e as aspas
    todas). Com o teto fixo de 1200 que havia aqui, um carrossel de 12 slides
    chegava cortado no meio de um item — e o JSON quebrado descarta o documento
    inteiro, então o pedido inteiro caía no composer mock sem dizer por quê. Os
    400 de base cobrem hashtags e legenda.
    """
    return 400 + 120 * max(1, slides_count)



class LLMTextComposer:
    """Usa um endpoint OpenAI-compatible (Groq, OpenAI, Ollama, etc.)."""

    name = "llm"

    def __init__(self, settings: Settings):
        self._settings = settings
        self._timeout = settings.request_timeout_seconds
        self._base = settings.llm_api_base_url.rstrip("/")
        self._key = settings.llm_api_key
        self._model = settings.llm_model or "llama-3.1-8b-instant"

    def compose(
        self,
        raw_text: str,
        *,
        style: str = "quote",
        slides_count: int = 6,
        extra: dict[str, Any] | None = None,
    ) -> ComposedCarousel:
        cleaned = _clean(raw_text)
        if not cleaned:
            return ComposedCarousel(provider=self.name)

        language = str((extra or {}).get("language") or "pt-BR")
        roles = viral_script_roles(slides_count)

        # Tentativa 1: sem response_format (compatível com QUALQUER modelo Groq,
        # incluindo qwen, gemma, etc. que podem não suportar JSON mode).
        # O _parse_json_loose já extrai JSON mesmo se o modelo cercar com texto.
        try:
            payload = {
                "model": self._model,
                "messages": [
                    {
                        "role": "system",
                        "content": _build_viral_prompt(slides_count, language, roles),
                    },
                    {"role": "user", "content": cleaned},
                ],
                "temperature": 0.6,
                "max_tokens": _viral_max_tokens(slides_count),
            }
            response = requests.post(
                f"{self._base}/chat/completions",
                json=payload,
                headers={
                    "Authorization": f"Bearer {self._key}",
                    "Content-Type": "application/json",
                },
                timeout=self._timeout,
            )
            # Se erro 4xx relacionado a response_format ou parâmetros,
            # tentar novamente com payload mínimo
            if response.status_code in (400, 422):
                error_text = response.text[:300]
                logger.warning(
                    "LLM rejeitou payload (HTTP %d): %s — tentando sem json_mode",
                    response.status_code,
                    error_text,
                )
            response.raise_for_status()
        except requests.Timeout:
            logger.warning("LLM composer timeout — fallback mock.")
            return MockTextComposer().compose(
                cleaned, style=style, slides_count=slides_count, extra=extra
            )
        except requests.RequestException as exc:
            logger.warning("LLM composer erro: %s — fallback mock.", type(exc).__name__)
            return MockTextComposer().compose(
                cleaned, style=style, slides_count=slides_count, extra=extra
            )

        try:
            data = response.json() or {}
            content = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
            parsed = _parse_json_loose(content)
        except (ValueError, KeyError, IndexError) as exc:
            logger.warning("LLM retornou JSON inválido (%s) — fallback mock.", type(exc).__name__)
            return MockTextComposer().compose(
                cleaned, style=style, slides_count=slides_count, extra=extra
            )

        if not parsed:
            return MockTextComposer().compose(
                cleaned, style=style, slides_count=slides_count, extra=extra
            )

        slides_data: Iterable[dict[str, Any]] = parsed.get("slides") or []
        slides: list[SlideContent] = []
        for i, s in enumerate(slides_data):
            order = len(slides)
            # O slide 1 é uma caixa só, e essa caixa cabe mais que uma headline
            # comum (HOOK_TEXT_LIMIT vs. 70). Cortar o hook em 70 aqui era o
            # que devolvia a frase com "…" no meio — texto alterado sem motivo,
            # já que a caixa comportava a frase inteira.
            limit = HOOK_TEXT_LIMIT if order == 0 else 70
            headline = _truncate(str(s.get("headline") or "").strip(), limit)
            body = _truncate(str(s.get("body") or "").strip(), 280)
            if not headline and not body:
                continue
            # O papel vem do modelo, mas a posição manda: se o modelo devolver
            # um papel inválido (ou nenhum), usamos o da estrutura canônica.
            role = _normalize_role(s.get("role")) or (
                roles[order] if order < len(roles) else "value"
            )
            if order == 0:
                # A primeira foto do carrossel é o hook por definição do
                # produto. Um modelo que rotule o slide 1 de outra coisa não
                # muda isso — mudaria só o que o renderer faz com ele.
                role = "hook"
            cta = _truncate(str(s.get("call_to_action") or "").strip(), 80)
            slides.append(
                enforce_hook_slide(
                    SlideContent(
                        headline=headline,
                        body=body,
                        call_to_action=cta if role == "cta" else "",
                        order=order,
                        role=role,
                    ),
                    # Apoio no slide 1 aqui é desobediência ao prompt, não texto
                    # do usuário — apagar, não colar (colar inflava o hook).
                    merge_body=False,
                )
            )

        if not slides:
            return MockTextComposer().compose(
                cleaned, style=style, slides_count=slides_count, extra=extra
            )

        # A primeira foto do carrossel é a única que ninguém desliza sem ler:
        # sair sem texto nenhum é o pior resultado possível dela. Nenhuma regra
        # acima deveria esvaziá-la, mas o veredicto é do modelo — se sobrou
        # caixa vazia, ela recebe a primeira frase do texto colado, que é a
        # melhor aproximação de hook disponível sem inventar nada.
        if not slides[0].headline:
            fallback = _split_sentences(cleaned) or [cleaned]
            slides[0].headline = hook_box_text(fallback[0])
            logger.warning(
                "LLM devolveu o slide 1 sem texto — hook tirado do texto colado."
            )

        # Garantir que o carrossel sempre feche com um CTA visível.
        last = slides[-1]
        if last.role == "cta" and not last.call_to_action:
            last.call_to_action = _STYLE_CTA.get(style, "comenta abaixo 👇")

        hashtags_raw = parsed.get("hashtags") or []
        hashtags = [str(h).lstrip("#").strip() for h in hashtags_raw if str(h).strip()][:10]
        if not hashtags:
            hashtags = _extract_hashtags(cleaned)

        caption = _truncate(str(parsed.get("caption") or "").strip(), 200)
        if not caption:
            caption = MockTextComposer._build_caption(cleaned, style)

        return ComposedCarousel(
            slides=slides,
            hashtags=hashtags,
            caption=caption,
            provider=self.name,
        )


def _parse_json_loose(content: str) -> dict[str, Any] | None:
    """Tenta extrair JSON mesmo se o modelo cercar com texto/markdown."""
    if not content:
        return None
    content = content.strip()
    # Remove cercas ```json ... ```
    fence = re.search(r"```(?:json)?\s*(.*?)```", content, re.DOTALL)
    if fence:
        content = fence.group(1).strip()
    try:
        import json
        return json.loads(content)
    except json.JSONDecodeError:
        # Procura o primeiro { ... }
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if not match:
            return None
        try:
            import json
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None


# ---------- fábrica ----------


def build_text_composer(settings: Settings) -> TextComposer:
    """Fábrica: mock por padrão, llm se configurado."""
    if settings.llm_provider == "mock":
        return MockTextComposer()
    if not settings.llm_configured:
        logger.info("LLM provider=%s mas sem credenciais — caindo para mock.", settings.llm_provider)
        return MockTextComposer()
    try:
        return LLMTextComposer(settings)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Falha ao construir LLMTextComposer: %s — mock.", type(exc).__name__)
        return MockTextComposer()


__all__ = [
    "SlideContent",
    "ComposedCarousel",
    "TextComposer",
    "MockTextComposer",
    "LLMTextComposer",
    "build_text_composer",
    "VIRAL_ROLES",
    "viral_script_roles",
    "HOOK_TEXT_LIMIT",
    "hook_box_text",
    "enforce_hook_slide",
]
