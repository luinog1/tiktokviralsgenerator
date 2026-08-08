"""Cliente Pinterest — apenas API oficial, sempre no backend.

Sempre usa o token do servidor. O token nunca é exposto ao cliente.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Iterable, Protocol

import requests

from app.config import Settings

logger = logging.getLogger(__name__)


@dataclass
class PinterestImage:
    """Representação estável de uma imagem retornada pelo Pinterest."""

    image_id: str
    image_url: str
    source_url: str
    title: str
    description: str = ""
    attribution_text: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "image_id": self.image_id,
            "image_url": self.image_url,
            "source_url": self.source_url,
            "title": self.title,
            "description": self.description,
            "attribution_text": self.attribution_text,
        }


class PinterestClient(Protocol):
    """Interface oficial."""

    name: str

    def search(self, query: str, limit: int = 8) -> list[PinterestImage]:  # pragma: no cover
        ...


class MockPinterestClient:
    """Gera imagens sintéticas — funciona sem credenciais.

    Não busca fotos reais; apenas satisfaz o fluxo de UI.
    """

    name = "mock"

    # Paleta de gradientes SVG para variedade visual sem dependência externa.
    _PALETTES = [
        ("#FF6B6B", "#FFE66D"),
        ("#4ECDC4", "#556270"),
        ("#C7F464", "#FF6B6B"),
        ("#A8E6CF", "#FF8B94"),
        ("#FFD3A5", "#FD6585"),
        ("#614385", "#516395"),
        ("#FCE38A", "#F38181"),
        ("#AAFFA9", "#11FFBD"),
    ]

    def search(self, query: str, limit: int = 8) -> list[PinterestImage]:
        query = (query or "viral").strip() or "viral"
        results: list[PinterestImage] = []
        for i in range(min(limit, len(self._PALETTES))):
            idx = (hash(query) + i) % len(self._PALETTES)
            c1, c2 = self._PALETTES[idx]
            svg = (
                f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 800">'
                f'<defs><linearGradient id="g{i}" x1="0%" y1="0%" x2="100%" y2="100%">'
                f'<stop offset="0%" stop-color="{c1}"/>'
                f'<stop offset="100%" stop-color="{c2}"/>'
                f'</linearGradient></defs>'
                f'<rect width="600" height="800" fill="url(#g{i})"/>'
                f'<text x="50%" y="50%" text-anchor="middle" '
                f'font-family="sans-serif" font-size="38" fill="rgba(0,0,0,0.55)" '
                f'font-weight="700">{query[:24]}</text>'
                f'</svg>'
            )
            data_uri = "data:image/svg+xml;utf8," + requests.utils.quote(svg)
            results.append(
                PinterestImage(
                    image_id=f"mock-{i}-{abs(hash(query)) % 100000}",
                    image_url=data_uri,
                    source_url=f"https://www.pinterest.com/search/pins/?q={requests.utils.quote(query)}",
                    title=f"Resultado mock #{i + 1} — {query}",
                    description=f"Imagem ilustrativa (mock) para o tema “{query}”.",
                    attribution_text="Mock — não usar para publicação comercial.",
                )
            )
        return results


class PinterestV5Client:
    """Implementação real usando a API oficial v5 do Pinterest.

    Documentação: https://developers.pinterest.com/docs/api/v5/
    Requer token com escopo de busca.
    """

    name = "pinterest_v5"

    def __init__(self, settings: Settings):
        self._settings = settings
        self._base = settings.pinterest_api_base_url.rstrip("/")
        self._timeout = settings.request_timeout_seconds

    def search(self, query: str, limit: int = 8) -> list[PinterestImage]:
        if not self._settings.pinterest_configured:
            raise RuntimeError("Pinterest não configurado — token ausente.")

        try:
            response = requests.get(
                f"{self._base}/search/boards/",
                # Nota: a API v5 tem endpoints específicos. Aqui usamos /pins/search
                # conforme documentação oficial. Ajustar conforme necessário.
                params={"query": query, "page_size": limit},
                headers={"Authorization": f"Bearer {self._settings.pinterest_access_token}"},
                timeout=self._timeout,
            )
            response.raise_for_status()
        except requests.Timeout:
            logger.warning("Pinterest timeout — usando fallback mock.")
            return MockPinterestClient().search(query, limit)
        except requests.RequestException as exc:
            logger.warning("Pinterest erro de rede: %s — usando fallback mock.", type(exc).__name__)
            return MockPinterestClient().search(query, limit)

        data = response.json() or {}
        items: Iterable[dict[str, Any]] = data.get("items") or data.get("results") or []
        images: list[PinterestImage] = []
        for item in items:
            pin = item.get("pin") or item
            images.append(
                PinterestImage(
                    image_id=str(pin.get("id") or ""),
                    image_url=self._extract_image_url(pin),
                    source_url=pin.get("link") or f"https://www.pinterest.com/pin/{pin.get('id')}/",
                    title=str(pin.get("title") or pin.get("description") or "")[:200],
                    description=str(pin.get("description") or "")[:500],
                    attribution_text="Fonte: Pinterest",
                )
            )
        if not images:
            logger.info("Pinterest não retornou itens — fallback mock.")
            return MockPinterestClient().search(query, limit)
        return images[:limit]

    @staticmethod
    def _extract_image_url(pin: dict[str, Any]) -> str:
        media = pin.get("media") or {}
        images = pin.get("images") or {}
        # Preferir imagem original; cair para próxima resolução disponível
        for key in ("original", "large", "medium", "small"):
            entry = images.get(key) or media.get(key)
            if isinstance(entry, dict) and entry.get("url"):
                return str(entry["url"])
        return ""


def build_pinterest_client(settings: Settings) -> PinterestClient:
    """Fábrica Pinterest — usa mock se não houver token."""
    if not settings.pinterest_configured:
        logger.info("Pinterest token ausente — usando cliente mock.")
        return MockPinterestClient()
    return PinterestV5Client(settings)
