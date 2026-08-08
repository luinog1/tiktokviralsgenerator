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


@dataclass(frozen=True)
class Settings:
    """Snapshot imutável das configurações carregadas do ambiente."""

    flask_env: str
    secret_key: str
    debug: bool

    # Pinterest
    pinterest_access_token: str
    pinterest_api_base_url: str

    # LLM (OpenAI-compatible: Groq, OpenAI, Ollama, etc.) — usado para
    # composição de slides E ranking de imagens (mesma fonte).
    llm_provider: Literal["mock", "openai_compatible"]
    llm_api_base_url: str
    llm_api_key: str
    llm_model: str

    # Ranking visual — desligável independentemente do LLM de composição
    ranking_enabled: bool

    # HTTP
    request_timeout_seconds: int

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

        return cls(
            flask_env=_get("FLASK_ENV", "development"),
            secret_key=_get("SECRET_KEY", "dev-insecure-change-me"),
            debug=_bool(env.get("DEBUG"), True),  # type: ignore[union-attr]
            pinterest_access_token=_get("PINTEREST_ACCESS_TOKEN"),
            pinterest_api_base_url=_get(
                "PINTEREST_API_BASE_URL",
                "https://api.pinterest.com/v5",
            ),
            llm_provider=cls._provider(llm_provider_raw),
            llm_api_base_url=llm_base_raw,
            llm_api_key=llm_key_raw,
            llm_model=llm_model_raw,
            ranking_enabled=_bool(env.get("RANKING_ENABLED"), True),  # type: ignore[union-attr]
            request_timeout_seconds=int(_get("REQUEST_TIMEOUT_SECONDS", "20") or 20),
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


__all__ = ["Settings"]
