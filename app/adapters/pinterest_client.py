"""Cliente Unsplash — substituto temporário ao Pinterest.

Unsplash API é gratuita, sem expiração de token e funciona em produção imediatamente.
Documentação: https://unsplash.com/developers

Para usar:
1. Crie conta em https://unsplash.com/developers
2. Crie um app → copie o "Access Key"
3. No Render, adicione: UNSPLASH_ACCESS_KEY=sua_chave_aqui
4. Substitua o pinterest_client.py por este arquivo (ou use em paralelo)

Escopos necessários: nenhum especial — a chave pública já basta para /search/photos
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import requests

logger = logging.getLogger(__name__)


# Reutiliza o mesmo dataclass PinterestImage para não quebrar o resto do código
@dataclass
class PinterestImage:
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


class UnsplashClient:
    """Cliente Unsplash — funciona em produção sem aprovação especial."""

    name = "unsplash"
    _BASE = "https://api.unsplash.com"

    def __init__(self, access_key: str, timeout: int = 20):
        self._access_key = access_key
        self._timeout = timeout

    def search(self, query: str, limit: int = 8) -> list[PinterestImage]:
        if not self._access_key:
            raise RuntimeError("UNSPLASH_ACCESS_KEY não definido.")

        try:
            response = requests.get(
                f"{self._BASE}/search/photos",
                params={
                    "query": query,
                    "per_page": min(limit, 30),
                    "orientation": "portrait",   # melhor para formato TikTok/Instagram
                },
                headers={
                    "Authorization": f"Client-ID {self._access_key}",
                    "Accept-Version": "v1",
                },
                timeout=self._timeout,
            )
            if response.status_code >= 400:
                logger.warning("Unsplash HTTP %d: %s", response.status_code, response.text[:200])
            response.raise_for_status()
        except requests.Timeout:
            logger.warning("Unsplash timeout.")
            return []
        except requests.RequestException as exc:
            logger.warning("Unsplash erro: %s", type(exc).__name__)
            return []

        data = response.json() or {}
        results = data.get("results") or []
        images: list[PinterestImage] = []

        for item in results:
            urls = item.get("urls") or {}
            user = item.get("user") or {}
            username = user.get("username", "unsplash")
            name = user.get("name", "Unsplash")

            images.append(PinterestImage(
                image_id=str(item.get("id") or ""),
                # "regular" = 1080px de largura — ideal para slides
                image_url=urls.get("regular") or urls.get("full") or "",
                source_url=item.get("links", {}).get("html") or f"https://unsplash.com/photos/{item.get('id')}",
                title=str(item.get("alt_description") or item.get("description") or query)[:200],
                description=str(item.get("description") or "")[:500],
                # Atribuição obrigatória pelos termos do Unsplash
                attribution_text=f"Foto de {name} (@{username}) no Unsplash",
            ))

        logger.info("Unsplash retornou %d imagens para query=%r", len(images), query[:80])
        return images[:limit]