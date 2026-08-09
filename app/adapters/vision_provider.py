"""Ranking de imagens por VISÃO — o modelo olha a foto, não só o metadado.

Diferença para o `ranking_provider`: aquele manda `title`/`description` (que no
Unsplash vêm vazios ou genéricos com frequência) e pede uma nota. Aqui a foto
vai junto, num endpoint OpenAI-compatible com `image_url` — o formato que
ModelScope API-Inference, OpenRouter e OpenAI aceitam igual.

Além da nota, o modelo devolve ONDE o texto cabe. O estilo sticker desenha
caixas brancas por cima da foto; sem olhar a imagem, a posição vem da âncora do
papel no roteiro e às vezes cai em cima do rosto ou da região clara. O `anchor`
retornado vira `pos_x`/`pos_y` no slide — os mesmos campos que o arraste na
prévia grava, então o usuário continua podendo corrigir por cima.

Nada aqui é obrigatório: sem VISION_* configurado, ou em qualquer falha, o
fluxo cai no ranking textual de sempre.
"""

from __future__ import annotations

import json
import logging
import math
import re
from dataclasses import dataclass
from typing import Any

import requests

from app.adapters.pinterest_client import PinterestImage, is_mock_image
from app.config import Settings

logger = logging.getLogger(__name__)

# Zonas que o modelo pode escolher para o texto, e o centro de cada uma em
# fração do canvas. Pedir uma zona nomeada em vez de coordenadas cruas é o que
# torna a saída estável: VLM erra número solto, mas acerta "topo/meio/base".
_ANCHOR_POINTS: dict[str, tuple[float, float]] = {
    "top": (0.5, 0.22),
    "center": (0.5, 0.5),
    "bottom": (0.5, 0.76),
    "top-left": (0.34, 0.22),
    "top-right": (0.66, 0.22),
    "bottom-left": (0.34, 0.76),
    "bottom-right": (0.66, 0.76),
}

# Assunto da foto. O carrossel de lifestyle abre com uma pessoa em cena e segue
# com cenário — para montar isso o casting precisa saber o que tem em cada foto,
# e o metadado do Unsplash não diz de forma confiável.
_SUBJECTS = ("woman", "man", "person", "scene")

_SYSTEM_PROMPT = (
    "Você seleciona fotos de fundo para carrosséis do TikTok (photo post 4:5). "
    "O texto é desenhado por cima, em caixas BRANCAS com texto preto.\n\n"
    "Para cada imagem, avalie:\n"
    "1. score (0 a 1): a foto combina com o tema do post? Estética de feed, "
    "boa luz, sem marca d'água, sem texto embutido na foto.\n"
    "2. anchor: em que região há espaço LIMPO para as caixas de texto, sem "
    "cobrir rosto ou o assunto principal. Escolha uma de: "
    f"{', '.join(_ANCHOR_POINTS)}.\n"
    "3. subject: o que a foto mostra em primeiro plano. Escolha uma de: "
    "woman (mulher em cena), man (homem em cena), person (pessoa sem dar para "
    "dizer, ou mais de uma), scene (sem pessoa em destaque: lugar, comida, "
    "objeto, interior, paisagem).\n"
    "4. reason: no máximo 90 caracteres, em português.\n\n"
    "Penalize com score baixo: foto com texto/logo embutido, muito escura, "
    "muito poluída no centro, ou sem relação com o tema.\n"
    'Responda APENAS JSON: {"results":[{"image_id":"","score":0.0,'
    '"anchor":"top","subject":"scene","reason":""}]}'
)


@dataclass
class VisionVerdict:
    """Nota + zona de texto + assunto da foto."""

    image_id: str
    score: float
    anchor: str = ""
    # "woman" | "man" | "person" | "scene" | "" (o modelo não classificou).
    # Leitura do enquadramento de uma foto de banco de imagens, usada só para
    # escolher qual slide recebe qual foto.
    subject: str = ""
    reason: str = ""

    @property
    def position(self) -> tuple[float, float] | None:
        """Centro do bloco de texto, no mesmo formato de pos_x/pos_y."""
        return _ANCHOR_POINTS.get(self.anchor)

    def to_dict(self) -> dict[str, Any]:
        return {
            "image_id": self.image_id,
            "score": round(self.score, 4),
            "reason": self.reason,
            "anchor": self.anchor,
            "subject": self.subject,
        }


class VisionRankingProvider:
    """Ranqueia olhando as fotos, via endpoint OpenAI-compatible com visão."""

    name = "vision"

    # Teto de imagens por chamada. Cada foto custa tokens de visão e o request
    # é síncrono dentro do POST /generate — 8 já cobre um carrossel de 12
    # slides, que reusa imagens em rotação.
    MAX_IMAGES = 8

    def __init__(self, settings: Settings):
        self._settings = settings
        self._base = settings.vision_api_base_url.rstrip("/")
        self._key = settings.vision_api_key
        self._model = settings.vision_model
        # Timeout próprio, não o `request_timeout_seconds` da busca de imagens:
        # o VLM olha até 8 fotos numa chamada e leva dezenas de segundos.
        self._timeout = settings.vision_timeout_seconds

    def rank(
        self, briefing: dict[str, Any], images: list[PinterestImage]
    ) -> list[VisionVerdict]:
        """Devolve um veredicto por imagem, ou [] se a visão não puder rodar.

        Lista vazia é o sinal de "use o ranking textual" — nunca uma exceção,
        porque isso derrubaria a geração inteira do carrossel.
        """
        judgeable = [
            img for img in images if img.vision_url and not is_mock_image(img)
        ]
        candidates = _cap_across_pools(judgeable, self.MAX_IMAGES)
        if not candidates:
            # Gradientes sintéticos não têm o que julgar visualmente.
            return []

        content: list[dict[str, Any]] = [{
            "type": "text",
            "text": (
                f"Tema do post: {briefing.get('theme') or '(sem tema)'}\n"
                f"Texto do carrossel: {str(briefing.get('raw_text') or '')[:400]}\n\n"
                f"Avalie as {len(candidates)} imagens a seguir, na ordem. "
                "Os image_id são: " + ", ".join(i.image_id for i in candidates)
            ),
        }]
        for img in candidates:
            content.append({
                "type": "image_url",
                "image_url": {"url": img.vision_url},
            })

        try:
            response = requests.post(
                f"{self._base}/chat/completions",
                json={
                    "model": self._model,
                    "messages": [
                        {"role": "system", "content": _SYSTEM_PROMPT},
                        {"role": "user", "content": content},
                    ],
                    "temperature": 0.1,
                    "max_tokens": 900,
                },
                headers={
                    "Authorization": f"Bearer {self._key}",
                    "Content-Type": "application/json",
                },
                timeout=self._timeout,
            )
            if response.status_code >= 400:
                # 404 aqui é quase sempre model id errado (no ModelScope o ID
                # precisa do prefixo da org: "Qwen/Qwen3-VL-...").
                logger.warning(
                    "Vision endpoint HTTP %d: %s",
                    response.status_code,
                    response.text[:300],
                )
            response.raise_for_status()
        except requests.Timeout:
            logger.warning(
                "Vision endpoint não respondeu em %ds — seguindo sem visão.",
                self._timeout,
            )
            return []
        except requests.RequestException as exc:
            logger.warning(
                "Vision endpoint falhou (%s) — seguindo sem visão.", type(exc).__name__
            )
            return []

        try:
            data = response.json() or {}
            raw = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
        except (ValueError, KeyError, IndexError) as exc:
            logger.warning("Vision devolveu resposta ilegível (%s).", type(exc).__name__)
            return []

        parsed = _parse_json_loose(_strip_reasoning(raw))
        if not parsed:
            logger.warning("Vision não devolveu JSON utilizável.")
            return []

        by_id = {img.image_id: img for img in candidates}
        verdicts: list[VisionVerdict] = []
        seen: set[str] = set()
        for item in parsed.get("results") or []:
            if not isinstance(item, dict):
                continue
            image_id = str(item.get("image_id") or "")
            if image_id not in by_id or image_id in seen:
                continue
            seen.add(image_id)
            verdicts.append(
                VisionVerdict(
                    image_id=image_id,
                    score=_clamp_score(item.get("score")),
                    anchor=_normalize_anchor(item.get("anchor")),
                    subject=_normalize_subject(item.get("subject")),
                    reason=str(item.get("reason") or "")[:200],
                )
            )

        if not verdicts:
            logger.warning("Vision respondeu, mas nenhum image_id bateu.")
            return []
        logger.info(
            "Vision avaliou %d/%d imagens com %s.",
            len(verdicts), len(candidates), self._model,
        )
        return verdicts


def _cap_across_pools(images: list[PinterestImage], cap: int) -> list[PinterestImage]:
    """Corta em `cap` imagens sem deixar um pool de fora.

    Com o casting ligado a lista chega como [fotos de retrato] + [fotos de
    cenário]. Um `[:cap]` cru gastaria a cota toda no primeiro pool e o modelo
    nunca veria as fotos de cenário — o casting então classificaria metade das
    fotos no escuro. Intercalar os pools mantém os dois representados.
    """
    if len(images) <= cap:
        return images
    buckets: dict[str, list[PinterestImage]] = {}
    for img in images:
        buckets.setdefault(img.pool, []).append(img)
    if len(buckets) < 2:
        return images[:cap]

    picked: list[PinterestImage] = []
    queues = list(buckets.values())
    round_index = 0
    while len(picked) < cap:
        progressed = False
        for queue in queues:
            if round_index < len(queue):
                picked.append(queue[round_index])
                progressed = True
                if len(picked) == cap:
                    break
        if not progressed:
            break
        round_index += 1
    return picked


def _clamp_score(value: Any) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return 0.0
    if math.isnan(score) or math.isinf(score):
        return 0.0
    return max(0.0, min(1.0, score))


def _normalize_anchor(value: Any) -> str:
    anchor = str(value or "").strip().lower().replace("_", "-").replace(" ", "-")
    return anchor if anchor in _ANCHOR_POINTS else ""


# Sinônimos que os VLMs devolvem no lugar do vocabulário pedido. Sem isso um
# "female" ou "girl" perfeitamente correto viraria "" e o casting perderia o
# único sinal confiável que tinha sobre aquela foto.
_SUBJECT_ALIASES = {
    "female": "woman", "girl": "woman", "lady": "woman", "mulher": "woman",
    "male": "man", "boy": "man", "guy": "man", "homem": "man",
    "people": "person", "human": "person", "pessoa": "person",
    "portrait": "person", "couple": "person",
    "place": "scene", "food": "scene", "object": "scene", "landscape": "scene",
    "interior": "scene", "nature": "scene", "cenario": "scene",
    "cenário": "scene", "none": "scene", "no-person": "scene",
}


def _normalize_subject(value: Any) -> str:
    subject = str(value or "").strip().lower().replace("_", "-").replace(" ", "-")
    subject = _SUBJECT_ALIASES.get(subject, subject)
    return subject if subject in _SUBJECTS else ""


# Modelos com cadeia de raciocínio (Qwen3-VL "thinking", ERNIE) abrem com um
# bloco <think>…</think>. O JSON vem depois — remover antes de procurar.
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def _strip_reasoning(content: str) -> str:
    return _THINK_RE.sub("", content or "").strip()


def _parse_json_loose(content: str) -> dict[str, Any] | None:
    """Extrai JSON mesmo se o modelo cercar com markdown ou texto solto."""
    if not content:
        return None
    content = content.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", content, re.DOTALL)
    if fence:
        content = fence.group(1).strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if not match:
            return None
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None


def build_vision_provider(settings: Settings) -> VisionRankingProvider | None:
    """Devolve o provider, ou None quando a visão não está configurada."""
    if not settings.vision_configured:
        return None
    return VisionRankingProvider(settings)


__all__ = [
    "VisionRankingProvider",
    "VisionVerdict",
    "build_vision_provider",
]
