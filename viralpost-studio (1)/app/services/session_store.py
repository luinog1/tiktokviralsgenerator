"""Persistência leve em memória com expiração por TTL.

Mudança v0.3: agora armazena carrossel (lista de slides) em vez de um único content.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Iterable

logger = logging.getLogger(__name__)


@dataclass
class StoredProject:
    """Projeto de carrossel gerado pelo usuário."""

    project_id: str
    briefing: dict[str, Any]
    carousel: dict[str, Any]  # {slides, hashtags, caption, provider}
    images: list[dict[str, Any]] = field(default_factory=list)
    ranking: list[dict[str, Any]] = field(default_factory=list)
    style: str = "quote"
    slides_count: int = 6
    raw_text: str = ""
    edited_slides: list[dict[str, Any]] = field(default_factory=list)
    selected_image_ids: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_public_dict(self) -> dict[str, Any]:
        """Versão sem tokens/sensitive fields. Sempre usada pela view."""
        return {
            "project_id": self.project_id,
            "briefing": dict(self.briefing),
            "carousel": dict(self.carousel),
            "images": list(self.images),
            "ranking": list(self.ranking),
            "style": self.style,
            "slides_count": self.slides_count,
            "raw_text": self.raw_text,
            "edited_slides": list(self.edited_slides),
            "selected_image_ids": list(self.selected_image_ids),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class SessionStore:
    """Store em memória thread-safe com TTL."""

    def __init__(self, ttl_minutes: int = 60):
        self._projects: dict[str, StoredProject] = {}
        self._lock = threading.Lock()
        self._ttl_seconds = max(60, ttl_minutes * 60)

    def create(
        self,
        *,
        briefing: dict[str, Any],
        carousel: dict[str, Any],
        images: list[dict[str, Any]],
        ranking: list[dict[str, Any]],
        style: str,
        slides_count: int,
        raw_text: str,
    ) -> StoredProject:
        project_id = uuid.uuid4().hex[:12]
        now = time.time()
        project = StoredProject(
            project_id=project_id,
            briefing=dict(briefing),
            carousel=dict(carousel),
            images=list(images),
            ranking=list(ranking),
            style=style,
            slides_count=slides_count,
            raw_text=raw_text,
            created_at=now,
            updated_at=now,
        )
        with self._lock:
            self._gc(now)
            self._projects[project_id] = project
        logger.info("Projeto criado id=%s slides=%d", project_id, len(carousel.get("slides", [])))
        return project

    def get(self, project_id: str) -> StoredProject | None:
        with self._lock:
            self._gc(time.time())
            return self._projects.get(project_id)

    def update(
        self,
        project_id: str,
        *,
        edited_slides: list[dict[str, Any]] | None = None,
        selected_image_ids: list[str] | None = None,
    ) -> StoredProject | None:
        with self._lock:
            project = self._projects.get(project_id)
            if not project:
                return None
            if edited_slides is not None:
                project.edited_slides = list(edited_slides)
            if selected_image_ids is not None:
                project.selected_image_ids = list(selected_image_ids)
            project.updated_at = time.time()
            return project

    def delete(self, project_id: str) -> bool:
        with self._lock:
            return self._projects.pop(project_id, None) is not None

    def list_recent(self, limit: int = 10) -> Iterable[StoredProject]:
        with self._lock:
            self._gc(time.time())
            items = sorted(
                self._projects.values(),
                key=lambda p: p.updated_at,
                reverse=True,
            )
            return items[:limit]

    def _gc(self, now: float) -> None:
        expired = [
            pid
            for pid, p in self._projects.items()
            if (now - p.updated_at) > self._ttl_seconds
        ]
        for pid in expired:
            self._projects.pop(pid, None)
        if expired:
            logger.info("Removidos %d projeto(s) expirados.", len(expired))


# Instância global — Flask roda single-process por padrão.
_global_store: SessionStore | None = None


def get_store(ttl_minutes: int = 60) -> SessionStore:
    global _global_store
    if _global_store is None:
        _global_store = SessionStore(ttl_minutes=ttl_minutes)
    return _global_store


def reset_store() -> None:
    """Reset para testes."""
    global _global_store
    _global_store = None
