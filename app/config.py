"""Configuração centralizada por variáveis de ambiente.

Mudança (v0.3):
- ViralAI foi removido — o goviral.ai (https://content.goviralai.app/) é uma
  ferramenta externa acessada manualmente pelo usuário via login Discord,
  sem API nem token. O usuário cola o texto pronto no formulário.
- LLM_* substitui RANKING_*: o endpoint OpenAI-compatible (Groq, etc.) agora
  ajuda a estruturar o texto em slides. Ranking visual fica como sub-produto
  opcional do mesmo endpoint.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal


def _bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "y"}


# Casting de imagens — o formato "hook + imagens secundárias" dos photo posts
# de lifestyle: o slide 1 traz uma pessoa (é o rosto que para o scroll) e os
# demais trazem cenário/estética. Os termos entram na busca de imagens porque
# uma query genérica raramente devolve retrato na primeira página.
HOOK_SUBJECTS = ("woman", "person", "off")
_DEFAULT_SCENE_HINTS = "aesthetic lifestyle travel food"

# De onde vêm as fotos. "auto" mantém a escada histórica (token oficial →
# chave do Unsplash → scraping → mock); os demais fixam um cliente.
IMAGE_PROVIDERS = ("auto", "pinterest_v5", "pinterest_scrape", "unsplash", "mock")


def _hook_hints(subject: str) -> str:
    return f"{subject} portrait lifestyle aesthetic"


@dataclass(frozen=True)
class Settings:
    """Snapshot imutável das configurações carregadas do ambiente."""

    flask_env: str
    secret_key: str
    debug: bool

    # Pinterest
    pinterest_access_token: str
    pinterest_api_base_url: str

    # Qual cliente de imagens usar. Ver IMAGE_PROVIDERS.
    image_provider: str

    # LLM (OpenAI-compatible: Groq, OpenAI, Ollama, etc.) — usado para
    # composição de slides E ranking de imagens (mesma fonte).
    llm_provider: Literal["mock", "openai_compatible"]
    llm_api_base_url: str
    llm_api_key: str
    llm_model: str

    # Ranking visual — desligável independentemente do LLM de composição
    ranking_enabled: bool

    # Casting de imagens por papel do slide. "woman"/"person" reservam o slide
    # de hook para uma foto com pessoa; "off" volta ao comportamento antigo
    # (uma busca só, imagens em rotação).
    hook_subject: str
    hook_query_hints: str
    scene_query_hints: str

    # Vision (VLM) — olha a foto de verdade para ranquear e sugerir onde o
    # texto cabe sem cobrir o assunto. Cai para o ranking textual se falhar.
    vision_enabled: bool
    vision_api_base_url: str
    vision_api_key: str
    vision_model: str

    # HTTP
    request_timeout_seconds: int

    # Timeout exclusivo da chamada de visão. Um VLM olhando 8 fotos leva
    # dezenas de segundos — muito mais que o Unsplash ou o LLM de texto, que
    # compartilhavam o `request_timeout_seconds`. Com um valor só para os dois,
    # o número que servia para a busca de imagens (20s) cancelava a visão antes
    # da primeira resposta, e o carrossel caía no ranking textual sem que nada
    # estivesse configurado errado.
    vision_timeout_seconds: int

    # Persistência leve (em memória) — expira em minutos
    session_ttl_minutes: int

    # Composição de imagem
    slide_width: int
    slide_height: int

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "Settings":
        env = env or os.environ  # type: ignore[assignment]

        def _get(name: str, default: str = "") -> str:
            value = env.get(name, default)  # type: ignore[union-attr]
            return value.strip() if isinstance(value, str) else default

        # Compatibilidade reversa: aceitar RANKING_* legados
        llm_provider_raw = _get("LLM_PROVIDER") or _get("RANKING_PROVIDER", "mock")
        llm_base_raw = _get("LLM_API_BASE_URL") or _get("RANKING_API_BASE_URL")
        llm_key_raw = _get("LLM_API_KEY") or _get("RANKING_API_KEY")
        llm_model_raw = _get("LLM_MODEL") or _get("RANKING_MODEL")

        # Auto-detecção amigável: se o usuário definiu LLM_API_KEY e
        # LLM_API_BASE_URL mas esqueceu LLM_PROVIDER, assumir openai_compatible.
        # Evita o bug comum de "configurei tudo mas continua em mock".
        if llm_provider_raw == "mock" and llm_key_raw and llm_base_raw:
            llm_provider_raw = "openai_compatible"

        hook_subject = (_get("HOOK_SUBJECT", "woman") or "woman").lower()
        if hook_subject not in HOOK_SUBJECTS:
            hook_subject = "woman"

        # Um provider desconhecido cai em "auto" em vez de derrubar o boot: o
        # erro de digitação vira a escada de sempre, e o /health mostra qual
        # cliente ficou ativo.
        image_provider = (_get("IMAGE_PROVIDER", "auto") or "auto").lower()
        if image_provider not in IMAGE_PROVIDERS:
            image_provider = "auto"

        return cls(
            flask_env=_get("FLASK_ENV", "development"),
            secret_key=_get("SECRET_KEY", "dev-insecure-change-me"),
            debug=_bool(env.get("DEBUG"), True),  # type: ignore[union-attr]
            pinterest_access_token=_get("PINTEREST_ACCESS_TOKEN"),
            pinterest_api_base_url=_get(
                "PINTEREST_API_BASE_URL",
                "https://api.pinterest.com/v5",
            ),
            image_provider=image_provider,
            llm_provider=cls._provider(llm_provider_raw),
            llm_api_base_url=llm_base_raw,
            llm_api_key=llm_key_raw,
            llm_model=llm_model_raw,
            ranking_enabled=_bool(env.get("RANKING_ENABLED"), True),  # type: ignore[union-attr]
            hook_subject=hook_subject,
            hook_query_hints=(
                _get("HOOK_QUERY_HINTS") or _hook_hints(hook_subject)
            ),
            scene_query_hints=(
                _get("SCENE_QUERY_HINTS") or _DEFAULT_SCENE_HINTS
            ),
            vision_enabled=_bool(env.get("VISION_ENABLED"), False),  # type: ignore[union-attr]
            # Vision costuma morar em outro provider que o LLM de texto
            # (ex.: Groq para roteiro, ModelScope para VLM). Sem VISION_*,
            # herda o LLM_* para quem usa o mesmo endpoint nos dois papéis.
            vision_api_base_url=_get("VISION_API_BASE_URL") or llm_base_raw,
            vision_api_key=_get("VISION_API_KEY") or llm_key_raw,
            vision_model=_get("VISION_MODEL"),
            request_timeout_seconds=int(_get("REQUEST_TIMEOUT_SECONDS", "20") or 20),
            vision_timeout_seconds=int(_get("VISION_TIMEOUT_SECONDS", "90") or 90),
            session_ttl_minutes=int(_get("SESSION_TTL_MINUTES", "60") or 60),
            slide_width=int(_get("SLIDE_WIDTH", "1080") or 1080),
            slide_height=int(_get("SLIDE_HEIGHT", "1350") or 1350),
        )

    @staticmethod
    def _provider(value: str) -> Literal["mock", "openai_compatible"]:
        if value in {"openai_compatible", "inference", "groq", "openai"}:
            return "openai_compatible"
        return "mock"

    @property
    def pinterest_configured(self) -> bool:
        return bool(self.pinterest_access_token)

    @property
    def llm_configured(self) -> bool:
        if self.llm_provider == "mock":
            return True
        return bool(self.llm_api_base_url and self.llm_api_key)

    @property
    def vision_configured(self) -> bool:
        """Vision exige o trio completo — o modelo não tem default seguro.

        Um ID errado responde 404 e o carrossel só perderia tempo antes de cair
        no ranking textual.
        """
        return bool(
            self.vision_enabled
            and self.vision_api_base_url
            and self.vision_api_key
            and self.vision_model
        )


    @property
    def casting_enabled(self) -> bool:
        """Casting por papel — hook com pessoa, demais com cenário."""
        return self.hook_subject != "off"


__all__ = ["Settings", "HOOK_SUBJECTS", "IMAGE_PROVIDERS"]
