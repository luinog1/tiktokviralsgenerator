"""Dependências do ViralPost Studio."""

from importlib.metadata import PackageNotFoundError, version

# Versão central do projeto
__version__ = "0.2.0"

try:
    FLASK_VERSION = version("flask")
except PackageNotFoundError:  # pragma: no cover - ambiente de desenvolvimento
    FLASK_VERSION = "unknown"
