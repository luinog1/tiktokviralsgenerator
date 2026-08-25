"""Mais fotos do mesmo @ — a busca que a prévia faz sem gerar outro carrossel.

O problema que isto resolve: a galeria de cada slide é montada na geração, e
quando nenhuma das seis fotos do hook serve, a única saída era gerar tudo de
novo — texto, casting, os outros slides. Aqui a prévia pede **só** mais fotos
de hook de um perfil, e o resto do carrossel fica onde está.

Duas fontes, nesta ordem, porque elas respondem coisas diferentes:

1. **Instagram (Apify).** Os posts do próprio perfil. É a resposta certa para
   "mais fotos desta modelo", e é paga por item — por isso o limite é baixo e
   a busca só roda quando alguém clica.
2. **Pinterest.** Reserva, e de graça: o handle **sem arroba** é um termo de
   busca legítimo lá (medido em 2026-08-25: `bellebres` devolve 50 pins,
   `@bellebres` devolve zero). São re-pins *sobre* aquela pessoa, não o feed
   dela — pior fidelidade, mas cobre o caso de não haver `APIFY_TOKEN` e o de
   a Apify não achar o perfil.
"""

from __future__ import annotations

import logging
import re

from app.adapters.pinterest_client import (
    PinterestImage,
    build_pinterest_client,
    _instagram_scrape_client,
    _pinterest_scrape_client,
    is_mock_image,
    media_identity,
)
from app.config import Settings

logger = logging.getLogger(__name__)

# Quantas alternativas a busca on-spot devolve por clique. O mesmo número que
# `casting.MIN_IMAGE_ALTERNATIVES` promete na geração, e no Instagram cada uma
# é um item pago da Apify — subir isso é subir a conta.
MAX_HANDLE_ALTERNATIVES = 5
# Busca por clique continua pequena: é uma troca de galeria, não uma nova
# geração do carrossel.
MAX_QUERY_ALTERNATIVES = 5

_HANDLE_CLEAN_RE = re.compile(r"[^a-z0-9._]")


def normalize_handle(raw: str) -> str:
    """`@Fulana.Silva ` → `fulana.silva`. Vazio quando não sobra handle.

    O usuário digita com arroba, sem arroba, com espaço sobrando ou colando a
    URL do perfil — as quatro formas viram a mesma coisa.
    """
    text = str(raw or "").strip()
    text = re.sub(
        r"^(?:https?://)?(?:www\.)?instagram\.com/", "", text, flags=re.I
    )
    text = text.strip("/").split("/")[0].split("?")[0]
    return _HANDLE_CLEAN_RE.sub("", text.lstrip("@").lower())


def search_by_handle(
    settings: Settings,
    handle: str,
    *,
    avoid_ids: set[str],
    avoid_media: set[str] = frozenset(),
    limit: int = MAX_HANDLE_ALTERNATIVES,
) -> tuple[list[PinterestImage], str, str]:
    """Até `limit` fotos novas do perfil. Devolve (fotos, fonte, motivo).

    `avoid_ids` são as fotos que o projeto já tem: alternativa que já está na
    galeria não é alternativa. O motivo só vem preenchido quando a lista sai
    vazia — é o texto que a prévia mostra em vez de um silêncio.
    """
    reasons: list[str] = []

    for source, fetch in (
        ("instagram", lambda: _from_instagram(settings, handle, avoid_media, limit)),
        ("pinterest", lambda: _from_pinterest(settings, handle, avoid_media, limit)),
    ):
        try:
            found, reason = fetch()
        except Exception as exc:  # pragma: no cover - defensivo
            logger.warning(
                "Busca on-spot em %s falhou (%s).", source, type(exc).__name__
            )
            found, reason = [], f"A busca no {source} falhou."
        fresh = [
            img
            for img in found
            if img.image_id and img.image_id not in avoid_ids
        ]
        if fresh:
            logger.info(
                "Busca on-spot: %d foto(s) de @%s via %s.", len(fresh), handle, source
            )
            return fresh[:limit], source, ""
        if reason:
            reasons.append(reason)

    return [], "", " ".join(reasons) or f"Nenhuma foto nova encontrada para @{handle}."


def search_by_query(
    settings: Settings,
    query: str,
    *,
    avoid_ids: set[str],
    avoid_media: set[str] = frozenset(),
    image_source: str = "",
    limit: int = MAX_QUERY_ALTERNATIVES,
) -> tuple[list[PinterestImage], str, str]:
    """Busca alternativas para um slide usando a fonte da geração.

    A busca só acontece quando o usuário clica. As fotos já presentes no
    projeto sao filtradas por id e por URL normalizada, porque providers podem
    devolver o mesmo arquivo com ids diferentes.
    """
    clean_query = " ".join(str(query or "").split())[:240]
    if not clean_query:
        return [], "", "Escreva o que a imagem deve mostrar."
    target_limit = min(max(int(limit or MAX_QUERY_ALTERNATIVES), 1), MAX_QUERY_ALTERNATIVES)
    try:
        client = build_pinterest_client(
            settings,
            override=image_source,
            avoid_media=avoid_media,
        )
        images = client.search(clean_query, limit=target_limit)
    except Exception as exc:  # pragma: no cover - defensivo
        logger.warning("Busca de alternativas falhou (%s).", type(exc).__name__)
        return [], "", "A busca de imagens falhou."

    # O modo mock é válido localmente. Um provider real que caiu no mock não
    # deve poluir a galeria com gradientes sem explicar a falha.
    if getattr(client, "name", "") != "mock" and images and all(
        is_mock_image(image) for image in images
    ):
        reason = getattr(client, "last_fallback_reason", "")
        return [], "", reason or "A fonte de imagens não retornou fotos reais."

    fresh: list[PinterestImage] = []
    for image in images:
        media_key = media_identity(image.image_url)
        if image.image_id in avoid_ids or (media_key and media_key in avoid_media):
            continue
        if any(
            image.image_id == candidate.image_id
            or (
                media_key
                and media_key == media_identity(candidate.image_url)
            )
            for candidate in fresh
        ):
            continue
        fresh.append(image)
        if len(fresh) >= target_limit:
            break
    if not fresh:
        return [], "", "Nenhuma imagem nova encontrada para essa busca."
    return fresh, getattr(client, "name", ""), ""


def _from_instagram(
    settings: Settings, handle: str, avoid_media: set[str], limit: int
) -> tuple[list[PinterestImage], str]:
    if not settings.apify_token:
        # Sem token o transporte anônimo existe, mas o endpoint de perfil está
        # atrás do muro de login — dizer isso é mais útil que tentar e falhar.
        return [], "Sem APIFY_TOKEN, o Instagram não responde por perfil."
    client = _instagram_scrape_client(settings, avoid_media=avoid_media)
    images = client.search_exact(f"@{handle}", limit=limit)
    real = [img for img in images if not is_mock_image(img)]
    if not real:
        return [], getattr(client, "last_fallback_reason", "")
    return real, ""


def _from_pinterest(
    settings: Settings, handle: str, avoid_media: set[str], limit: int
) -> tuple[list[PinterestImage], str]:
    client = _pinterest_scrape_client(settings, avoid_media=avoid_media)
    # Sem arroba de propósito: é assim que o Pinterest acha o perfil.
    images = client.search(handle, limit=limit)
    real = [img for img in images if not is_mock_image(img)]
    if not real:
        return [], getattr(client, "last_fallback_reason", "")
    return real, ""


__all__ = [
    "MAX_HANDLE_ALTERNATIVES",
    "MAX_QUERY_ALTERNATIVES",
    "normalize_handle",
    "search_by_handle",
    "search_by_query",
]
