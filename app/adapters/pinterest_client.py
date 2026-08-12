"""Cliente de imagens — Pinterest (oficial ou scraping), Unsplash e mock.

Fluxo de prioridade (`IMAGE_PROVIDER=auto`, o default):
1. PINTEREST_ACCESS_TOKEN definido → Pinterest v5 (requer Standard Access para /search)
2. UNSPLASH_ACCESS_KEY definido    → Unsplash (gratuito, sem aprovação especial)
3. Nenhuma chave                   → Mock SVG (sempre funciona)

`IMAGE_PROVIDER=pinterest_scrape` troca tudo isso pelo Pinterest **sem token**
(via `pinterest-dl`). É opt-in explícito: scraping nunca entra sozinho.

Variáveis de ambiente:
    IMAGE_PROVIDER           → auto | pinterest_v5 | pinterest_scrape | unsplash | mock
    PINTEREST_ACCESS_TOKEN   → token Pinterest
    PINTEREST_API_BASE_URL   → default: https://api.pinterest.com/v5
    UNSPLASH_ACCESS_KEY      → chave pública Unsplash (Access Key, não Secret Key)
"""

from __future__ import annotations

import logging
import os
import random
import re
import importlib.util
from dataclasses import dataclass
from typing import Any, Iterable, Protocol, runtime_checkable

import requests

from app.config import Settings

logger = logging.getLogger(__name__)

# Prefixo dos ids gerados pelo MockPinterestClient. Serve para reconhecer
# resultados mock *depois* da busca — um cliente real que caiu no fallback
# continua se chamando "unsplash"/"pinterest_v5", então o nome do cliente não
# basta para saber se o carrossel saiu com gradiente sintético.
MOCK_IMAGE_ID_PREFIX = "mock-"


def is_mock_image(image: "PinterestImage | dict[str, Any]") -> bool:
    image_id = image.get("image_id") if isinstance(image, dict) else image.image_id
    return str(image_id or "").startswith(MOCK_IMAGE_ID_PREFIX)


def _http_reason(api: str, response: requests.Response) -> str:
    """Motivo legível de um HTTP de erro — o que o usuário precisa corrigir."""
    code = response.status_code
    if code == 401:
        return (
            f"{api} recusou a credencial (HTTP 401). Confira se a chave é a "
            "Access Key, não a Secret Key."
        )
    if code == 403:
        return (
            f"{api} bloqueou a chamada (HTTP 403). No Unsplash isso costuma ser "
            "o limite de 50 req/h do app em modo Demo; no Pinterest, falta de "
            "Standard Access."
        )
    if code == 429:
        return f"{api} está limitando a taxa de chamadas (HTTP 429)."
    return f"{api} respondeu HTTP {code}."



@dataclass
class PinterestImage:
    """Representação estável de uma imagem — compatível com Pinterest e Unsplash."""

    image_id: str
    image_url: str
    source_url: str
    title: str
    description: str = ""
    attribution_text: str = ""
    # Versão pequena (~400px) da mesma foto. O VLM julga composição muito bem
    # nessa resolução, e mandar a `image_url` cheia multiplicaria os tokens de
    # visão sem melhorar o julgamento. Vazio → cai na image_url.
    thumb_url: str = ""
    # De qual busca a foto veio: "hook" (query de retrato) ou "scene" (query de
    # estética). É o sinal que permite ao casting reservar o slide 1 para uma
    # pessoa sem depender de VLM configurado. Vazio = busca única, sem casting.
    pool: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "image_id": self.image_id,
            "image_url": self.image_url,
            "source_url": self.source_url,
            "title": self.title,
            "description": self.description,
            "attribution_text": self.attribution_text,
            "thumb_url": self.thumb_url,
            "pool": self.pool,
        }

    @property
    def vision_url(self) -> str:
        return self.thumb_url or self.image_url


@runtime_checkable
class PinterestClient(Protocol):
    """Interface oficial — qualquer cliente deve implementar search()."""

    name: str

    def search(self, query: str, limit: int = 8) -> list[PinterestImage]:  # pragma: no cover
        ...


# ---------------------------------------------------------------------------
# Mock — sempre disponível, sem credenciais
# ---------------------------------------------------------------------------

class MockPinterestClient:
    """Gera imagens sintéticas SVG — funciona sem credenciais."""

    name = "mock"

    _PALETTES = [
        ("#FF6B6B", "#FFE66D"), ("#4ECDC4", "#556270"), ("#C7F464", "#FF6B6B"),
        ("#A8E6CF", "#FF8B94"), ("#FFD3A5", "#FD6585"), ("#614385", "#516395"),
        ("#FCE38A", "#F38181"), ("#AAFFA9", "#11FFBD"),
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
            results.append(PinterestImage(
                image_id=f"mock-{i}-{abs(hash(query)) % 100000}",
                image_url=data_uri,
                source_url=f"https://www.pinterest.com/search/pins/?q={requests.utils.quote(query)}",
                title=f"Resultado mock #{i + 1} — {query}",
                description=f"Imagem ilustrativa (mock) para o tema \u201c{query}\u201d.",
                attribution_text="Mock \u2014 n\u00e3o usar para publica\u00e7\u00e3o comercial.",
            ))
        return results


# ---------------------------------------------------------------------------
# Unsplash — substituto funcional imediato, gratuito
# ---------------------------------------------------------------------------

class UnsplashClient:
    """Unsplash API — gratuita, sem aprovação especial, token não expira."""

    name = "unsplash"
    _BASE = "https://api.unsplash.com"
    # /search/photos é determinístico: mesma query + order_by=relevant devolve
    # sempre a mesma página 1, o que parecia cache do lado do app. Sortear a
    # página dentro desta janela renova as fotos sem perder relevância — ela
    # cai rápido depois das primeiras páginas.
    _PAGE_WINDOW = 5

    def __init__(self, access_key: str, timeout: int = 20):
        self._access_key = access_key
        self._timeout = timeout
        # Por que a última busca caiu no mock. Vazio = não caiu.
        self.last_fallback_reason = ""

    def _request(self, query: str, per_page: int, page: int) -> dict[str, Any]:
        response = requests.get(
            f"{self._BASE}/search/photos",
            params={
                "query": query,
                "per_page": per_page,
                "page": page,
                "orientation": "portrait",  # ideal para TikTok/Instagram
            },
            headers={
                "Authorization": f"Client-ID {self._access_key}",
                "Accept-Version": "v1",
            },
            timeout=self._timeout,
        )
        if response.status_code >= 400:
            logger.warning("Unsplash HTTP %d: %s", response.status_code, response.text[:200])
            self.last_fallback_reason = _http_reason("Unsplash", response)
        response.raise_for_status()
        return response.json() or {}

    def search(self, query: str, limit: int = 8) -> list[PinterestImage]:
        self.last_fallback_reason = ""
        per_page = min(limit, 30)
        page = random.randint(1, self._PAGE_WINDOW)
        try:
            payload = self._request(query, per_page, page)
            results = payload.get("results") or []
            total_pages = int(payload.get("total_pages") or 0)
            # A página sorteada pode cair além do fim do catálogo desta query.
            if not results and total_pages:
                page = ((page - 1) % total_pages) + 1
                payload = self._request(query, per_page, page)
                results = payload.get("results") or []
        except requests.Timeout:
            logger.warning("Unsplash timeout — usando fallback mock.")
            self.last_fallback_reason = (
                f"Unsplash não respondeu em {self._timeout}s."
            )
            return MockPinterestClient().search(query, limit)
        except requests.RequestException as exc:
            logger.warning("Unsplash erro: %s — usando fallback mock.", type(exc).__name__)
            self.last_fallback_reason = self.last_fallback_reason or (
                f"Falha de rede ao chamar o Unsplash ({type(exc).__name__})."
            )
            return MockPinterestClient().search(query, limit)

        images: list[PinterestImage] = []
        for item in results:
            urls = item.get("urls") or {}
            user = item.get("user") or {}
            images.append(PinterestImage(
                image_id=str(item.get("id") or ""),
                image_url=urls.get("regular") or urls.get("full") or "",
                thumb_url=urls.get("small") or urls.get("thumb") or "",
                source_url=item.get("links", {}).get("html") or "",
                title=str(item.get("alt_description") or query)[:200],
                description=str(item.get("description") or "")[:500],
                # Atribuição obrigatória pelos termos do Unsplash
                attribution_text=(
                    f"Foto de {user.get('name', '?')} "
                    f"(@{user.get('username', 'unsplash')}) no Unsplash"
                ),
            ))
        logger.info(
            "Unsplash retornou %d imagens para query=%r (página %d)",
            len(images), query[:80], page,
        )
        return images[:limit]


# ---------------------------------------------------------------------------
# Pinterest v5 — requer Standard Access para /search/pins/
# ---------------------------------------------------------------------------

class PinterestV5Client:
    """Implementação real usando a API oficial v5 do Pinterest."""

    name = "pinterest_v5"

    def __init__(self, settings: Settings):
        self._settings = settings
        self._base = settings.pinterest_api_base_url.rstrip("/")
        self._timeout = settings.request_timeout_seconds
        # Por que a última busca caiu no mock. Vazio = não caiu.
        self.last_fallback_reason = ""

    def search(self, query: str, limit: int = 8) -> list[PinterestImage]:
        if not self._settings.pinterest_configured:
            raise RuntimeError("Pinterest não configurado — token ausente.")

        self.last_fallback_reason = ""
        try:
            response = requests.get(
                f"{self._base}/search/pins/",   # /pins/ — não /boards/
                params={
                    "query": query,
                    "page_size": min(limit, 100),
                },
                headers={
                    "Authorization": f"Bearer {self._settings.pinterest_access_token}",
                    "Accept": "application/json",
                },
                timeout=self._timeout,
            )
            if response.status_code >= 400:
                self._log_error(response)
                self.last_fallback_reason = _http_reason("Pinterest", response)
            response.raise_for_status()
        except requests.Timeout:
            logger.warning("Pinterest timeout — usando fallback mock.")
            self.last_fallback_reason = f"Pinterest não respondeu em {self._timeout}s."
            return MockPinterestClient().search(query, limit)
        except requests.RequestException as exc:
            logger.warning("Pinterest erro de rede: %s — usando fallback mock.", type(exc).__name__)
            self.last_fallback_reason = self.last_fallback_reason or (
                f"Falha de rede ao chamar o Pinterest ({type(exc).__name__})."
            )
            return MockPinterestClient().search(query, limit)

        data = response.json() or {}
        items: Iterable[dict[str, Any]] = data.get("items") or data.get("results") or []
        images: list[PinterestImage] = []
        for item in items:
            pin = item.get("pin") or item
            images.append(PinterestImage(
                image_id=str(pin.get("id") or ""),
                image_url=self._extract_image_url(pin),
                source_url=pin.get("link") or f"https://www.pinterest.com/pin/{pin.get('id')}/",
                title=str(pin.get("title") or pin.get("description") or "")[:200],
                description=str(pin.get("description") or "")[:500],
                attribution_text="Fonte: Pinterest",
            ))
        if not images:
            logger.info("Pinterest sem resultados para query=%r — fallback mock.", query[:80])
            self.last_fallback_reason = "Pinterest não retornou resultados para a busca."
            return MockPinterestClient().search(query, limit)
        logger.info("Pinterest retornou %d imagens para query=%r", len(images), query[:80])
        return images[:limit]

    def validate_token(self) -> dict[str, Any]:
        """Testa se o token é válido. Útil para diagnóstico."""
        if not self._settings.pinterest_configured:
            return {"configured": False, "valid": False, "reason": "Token ausente"}
        try:
            response = requests.get(
                f"{self._base}/user_account/",
                headers={
                    "Authorization": f"Bearer {self._settings.pinterest_access_token}",
                    "Accept": "application/json",
                },
                timeout=self._timeout,
            )
        except requests.RequestException as exc:
            return {"configured": True, "valid": False, "reason": str(exc)}

        if response.status_code == 200:
            data = response.json() or {}
            return {
                "configured": True,
                "valid": True,
                "username": data.get("username"),
                "account_type": data.get("account_type"),
            }
        self._log_error(response)
        return {
            "configured": True,
            "valid": False,
            "status_code": response.status_code,
            "reason": self._extract_error_message(response),
        }

    @staticmethod
    def _log_error(response: requests.Response) -> None:
        try:
            err_data = response.json()
            err_msg = err_data.get("message") or err_data.get("detail") or str(err_data)[:200]
        except Exception:
            err_msg = response.text[:200]
        logger.warning("Pinterest API HTTP %d: %s", response.status_code, err_msg)

    @staticmethod
    def _extract_error_message(response: requests.Response) -> str:
        try:
            data = response.json() or {}
            return str(data.get("message") or data.get("detail") or data)[:200]
        except Exception:
            return response.text[:200]

    @staticmethod
    def _extract_image_url(pin: dict[str, Any]) -> str:
        media = pin.get("media") or {}
        images = pin.get("images") or {}
        for key in ("original", "large", "medium", "small"):
            entry = images.get(key) or media.get(key)
            if isinstance(entry, dict) and entry.get("url"):
                return str(entry["url"])
        media_images = media.get("images") or {}
        for key in ("original", "large", "medium", "small"):
            entry = media_images.get(key)
            if isinstance(entry, dict) and entry.get("url"):
                return str(entry["url"])
        return ""


# ---------------------------------------------------------------------------
# Pinterest sem API oficial — via pinterest-dl (lê a API interna do site)
# ---------------------------------------------------------------------------

# A URL da foto no CDN do Pinterest carrega o tamanho no próprio caminho:
# `.../originals/ab/cd/ef/hash.png` é a versão cheia e `.../474x/...` a
# reduzida. Duas armadilhas: o caminho reduzido serve **só JPEG** (pedir
# `.png` ali responde 403), e é essa versão que vai para o VLM — thumb
# quebrada significa visão sem foto e casting sem sinal.
_PINIMG_SIZE_RE = re.compile(
    r"^(https?://i\.pinimg\.com/)(?:originals|\d+x)/(.+?)\.[A-Za-z0-9]+$"
)
# ~474px: o suficiente para o VLM julgar composição, como o `urls.small` do
# Unsplash. A foto cheia multiplicaria os tokens de visão sem melhorar nada.
_PINIMG_THUMB_SIZE = "474x"


def _pinimg_thumb(src: str) -> str:
    """Versão reduzida da mesma foto. Vazio quando a URL não é do CDN."""
    match = _PINIMG_SIZE_RE.match(src or "")
    if not match:
        return ""
    return f"{match.group(1)}{_PINIMG_THUMB_SIZE}/{match.group(2)}.jpg"


def pinterest_scrape_available() -> bool:
    """A biblioteca está instalada? Ela é opcional — o app roda sem ela.

    `find_spec` responde sem pagar o import: carregar o pacote de verdade custa
    ~1,3s (ele puxa cryptography junto), e o `/health` não deveria gastar isso
    só para dizer "sim, está instalado".
    """
    try:
        return importlib.util.find_spec("pinterest_dl") is not None
    except (ImportError, ValueError):  # pragma: no cover - defensivo
        return False


def _is_portrait(media: Any) -> bool:
    """A foto é em pé? Resolução ausente ou zerada conta como "não sei"."""
    resolution = getattr(media, "resolution", None) or ()
    try:
        width, height = int(resolution[0]), int(resolution[1])
    except (IndexError, TypeError, ValueError):
        return False
    return width > 0 and height >= width


def _load_pinterest_dl() -> Any | None:
    try:
        from pinterest_dl import PinterestDL
    except ImportError:
        return None
    return PinterestDL


class PinterestScrapeClient:
    """Pinterest sem token — `pinterest-dl` lendo a API interna do site.

    A segunda opção de busca no Pinterest: a v5 oficial exige Standard Access
    (aprovação manual) no `/search/pins/`, e sem essa aprovação o app só tinha
    o Unsplash. Aqui não há credencial nem cota; o custo é depender de uma API
    não documentada e das regras de uso do Pinterest (ver README).
    """

    name = "pinterest_scrape"

    # Uma chamada à API interna traz 50 pins; pedir mais dispara uma segunda
    # página e um `sleep` entre elas, dentro do POST /generate. 40 mantém tudo
    # numa requisição só e ainda sobra material para filtrar e sortear.
    _POOL_SIZE = 40

    def __init__(self, timeout: int = 20):
        self._timeout = timeout
        # Por que a última busca caiu no mock. Vazio = não caiu.
        self.last_fallback_reason = ""

    def search(self, query: str, limit: int = 8) -> list[PinterestImage]:
        self.last_fallback_reason = ""
        pinterest_dl = _load_pinterest_dl()
        if pinterest_dl is None:
            self.last_fallback_reason = (
                "IMAGE_PROVIDER=pinterest_scrape, mas o pacote `pinterest-dl` "
                "não está instalado (pip install pinterest-dl)."
            )
            logger.warning(self.last_fallback_reason)
            return MockPinterestClient().search(query, limit)

        try:
            medias = pinterest_dl.with_api(timeout=self._timeout).search(
                query,
                num=self._POOL_SIZE,
                min_resolution=(0, 0),
            )
        except Exception as exc:
            # A API interna não tem contrato publicado: erro de rede, mudança
            # de payload e bloqueio chegam aqui como exceções diferentes. Todas
            # significam a mesma coisa para o carrossel — sem foto.
            logger.warning(
                "Pinterest (scraping) falhou: %s — usando fallback mock.",
                type(exc).__name__,
            )
            self.last_fallback_reason = (
                f"A busca sem token no Pinterest falhou ({type(exc).__name__})."
            )
            return MockPinterestClient().search(query, limit)

        medias = [m for m in medias if str(getattr(m, "src", "") or "")]
        if not medias:
            logger.info("Pinterest (scraping) sem resultados para query=%r.", query[:80])
            self.last_fallback_reason = (
                "A busca sem token no Pinterest não retornou pins."
            )
            return MockPinterestClient().search(query, limit)

        selected = self._select(medias, limit)
        logger.info(
            "Pinterest (scraping) retornou %d imagens para query=%r (de um pool de %d)",
            len(selected), query[:80], len(medias),
        )
        return [self._to_image(media, query) for media in selected]

    def _select(self, medias: list[Any], limit: int) -> list[Any]:
        """Recorta o pool: retrato primeiro, começando num ponto sorteado.

        Duas correções do mesmo pool, pelos mesmos motivos que já valem para o
        Unsplash. **Retrato** porque o slide é 4:5 e uma foto deitada perde
        metade da cena no recorte — o Unsplash resolve isso com
        `orientation=portrait`, que a API interna não oferece. **Ponto
        sorteado** porque a busca vem ordenada por relevância e essa ordem é
        estável: sem isso o mesmo tema devolveria as mesmas fotos toda vez, o
        que parece cache do app e não é.
        """
        portrait = [m for m in medias if _is_portrait(m)]
        pool = portrait if len(portrait) >= limit else medias
        start = random.randint(0, max(0, len(pool) - limit))
        return pool[start : start + limit]

    @staticmethod
    def _to_image(media: Any, query: str) -> PinterestImage:
        # `alt` é a descrição que o Pinterest guarda do pin ("a woman sitting
        # on a couch…") — a mesma forma do `alt_description` do Unsplash, que é
        # onde o casting procura por pessoa quando não há VLM configurado.
        alt = str(getattr(media, "alt", "") or "").strip()
        media_id = str(getattr(media, "id", "") or "")
        src = str(getattr(media, "src", "") or "")
        return PinterestImage(
            image_id=media_id,
            image_url=src,
            thumb_url=_pinimg_thumb(src),
            source_url=(
                str(getattr(media, "origin", "") or "")
                or f"https://www.pinterest.com/pin/{media_id}/"
            ),
            title=(alt or query)[:200],
            description="",
            attribution_text="Pin do Pinterest",
        )


# ---------------------------------------------------------------------------
# Fábrica — escolhe o melhor cliente disponível automaticamente
# ---------------------------------------------------------------------------

def build_pinterest_client(settings: Settings) -> PinterestClient:
    """Cliente de imagens conforme `IMAGE_PROVIDER`.

    Em `auto` (default) vale a escada de sempre: token oficial → chave do
    Unsplash → mock. O scraping fica **de fora** do automático de propósito —
    ele lê uma API não documentada do Pinterest e as regras de uso do site são
    problema de quem publica (ver README). Entrar sozinho num ambiente sem
    chave transformaria "esqueci de configurar" em "estou raspando o
    Pinterest", que não é uma decisão que o app deva tomar pelo usuário.

    Uma escolha explícita que não dá para atender (provider sem credencial)
    cai na mesma escada com um aviso no log, em vez de devolver um cliente que
    só sabe falhar.
    """
    unsplash_key = os.environ.get("UNSPLASH_ACCESS_KEY", "").strip()
    choice = settings.image_provider

    if choice == "mock":
        logger.info("IMAGE_PROVIDER=mock — usando cliente mock.")
        return MockPinterestClient()
    if choice == "pinterest_scrape":
        # Sem o pacote, o cliente ainda é devolvido: ele explica a ausência no
        # `last_fallback_reason`, que a prévia mostra. Trocar por outro provider
        # aqui esconderia a única pista de por que o carrossel saiu diferente.
        logger.info("IMAGE_PROVIDER=pinterest_scrape — Pinterest sem token.")
        return PinterestScrapeClient(timeout=settings.request_timeout_seconds)
    if choice == "pinterest_v5":
        if settings.pinterest_configured:
            return PinterestV5Client(settings)
        logger.warning("IMAGE_PROVIDER=pinterest_v5 sem PINTEREST_ACCESS_TOKEN.")
    if choice == "unsplash":
        if unsplash_key:
            return UnsplashClient(unsplash_key, timeout=settings.request_timeout_seconds)
        logger.warning("IMAGE_PROVIDER=unsplash sem UNSPLASH_ACCESS_KEY.")

    if settings.pinterest_configured:
        logger.info("Usando cliente Pinterest v5.")
        return PinterestV5Client(settings)
    if unsplash_key:
        logger.info("Pinterest não configurado — usando Unsplash.")
        return UnsplashClient(
            access_key=unsplash_key,
            timeout=settings.request_timeout_seconds,
        )

    logger.info("Nenhuma chave de imagens configurada — usando cliente mock.")
    return MockPinterestClient()