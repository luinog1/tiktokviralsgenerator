"""Camada de serviços — orquestração de adapters, renderização e persistência."""

from __future__ import annotations

from .session_store import SessionStore, StoredProject
from .generation import GenerationService
from .slide_renderer import RenderedSlide, SlideRenderer

__all__ = ["SessionStore", "StoredProject", "GenerationService", "SlideRenderer", "RenderedSlide"]
