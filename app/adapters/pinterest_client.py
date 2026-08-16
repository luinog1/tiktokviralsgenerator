"""Cliente de imagens — Pinterest (oficial ou scraping), Instagram, Unsplash e mock.

Fluxo de prioridade (`IMAGE_PROVIDER=auto`, o default):
1. PINTEREST_ACCESS_TOKEN definido → Pinterest v5 (requer Standard Access para /search)
2. UNSPLASH_ACCESS_KEY definido    → Unsplash (gratuito, sem aprovação especial)
3. Nenhuma chave                   → Mock SVG (sempre funciona)

`IMAGE_PROVIDER=pinterest_scrape` troca tudo isso pelo Pinterest **sem token**
(via `pinterest-dl`). `instagram_scrape` busca no Instagram sem token (a API
interna do site, os mesmos endpoints do instagram-php-scraper) e
`instagram_pinterest` combina as duas buscas, intercaladas. Todos são opt-in
explícitos: scraping nunca entra sozinho.

Variáveis de ambiente:
    IMAGE_PROVIDER           → auto | pinterest_v5 | pinterest_scrape | unsplash
                               | instagram_scrape | instagram_pinterest | mock
    PINTEREST_ACCESS_TOKEN   → token Pinterest
    PINTEREST_API_BASE_URL   → default: https://api.pinterest.com/v5
    UNSPLASH_ACCESS_KEY      → chave pública Unsplash (Access Key, não Secret Key)
    INSTAGRAM_PROXY          → proxy só para as chamadas do Instagram sem token
    SCRAPEDO_TOKEN           → as mesmas chamadas, saindo pelo gateway do
                               Scrape.do (vence o proxy quando os dois existem)
"""

from __future__ import annotations

import logging
import os
import random
import re
import unicodedata
import importlib.util
from dataclasses import dataclass
from itertools import zip_longest
from types import SimpleNamespace
from typing import Any, Iterable, Protocol, runtime_checkable
from urllib.parse import urlencode

import requests
import urllib3

from app.config import IMAGE_PROVIDERS, Settings

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
    width, height = _resolution(media)
    return width > 0 and height >= width


def _resolution(media: Any) -> tuple[int, int]:
    """(largura, altura) do pin. (0, 0) quando o payload não trouxe medida."""
    resolution = getattr(media, "resolution", None) or ()
    try:
        return int(resolution[0]), int(resolution[1])
    except (IndexError, TypeError, ValueError):
        return 0, 0


def _covers_slide(media: Any, minimum: tuple[int, int]) -> bool:
    """A foto tem pixel suficiente para preencher o slide sem ser ampliada?

    O render faz `cover` da foto no canvas de 1080×1350: um pin de 474×711 é
    esticado para caber e chega ao feed borrado, com a legenda nítida por cima —
    a assinatura visual de post amador. O VLM não tem como reprovar isso, porque
    ele julga uma thumb de 474px: a resolução da origem não está na imagem que
    ele vê. Por isso o piso é aplicado aqui, na busca, e não no ranking.

    Medida ausente conta como reprovada: o pool tem 40 pins e sobra material
    para exigir prova em vez de dar o benefício da dúvida.
    """
    min_width, min_height = minimum
    if min_width <= 0 and min_height <= 0:
        return True
    width, height = _resolution(media)
    return width >= min_width and height >= min_height


def _cut_pool(medias: list[Any], limit: int, min_resolution: tuple[int, int]) -> list[Any]:
    """O recorte comum das buscas sem token (Pinterest e Instagram).

    Alta resolução e retrato primeiro, com as exigências caindo em ordem quando
    o acervo não dá para elas, e o ponto de corte sorteado para a mesma busca
    não devolver sempre as mesmas fotos. Ver `PinterestScrapeClient._select`
    para o porquê de cada correção.
    """
    sharp = [m for m in medias if _covers_slide(m, min_resolution)]
    portrait = [m for m in medias if _is_portrait(m)]
    for pool in ([m for m in sharp if _is_portrait(m)], sharp, portrait, medias):
        if len(pool) >= limit:
            break
    start = random.randint(0, max(0, len(pool) - limit))
    return pool[start : start + limit]


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

    def __init__(self, timeout: int = 20, min_resolution: tuple[int, int] = (0, 0)):
        self._timeout = timeout
        # Piso de resolução: o tamanho do slide, para a foto não ser ampliada no
        # render. Filtrado aqui e não no parâmetro `min_resolution` da
        # biblioteca porque lá o corte acontece ANTES da contagem: para fechar
        # os 40 pins ela pagina de novo, com um `sleep` a cada página, dentro do
        # POST /generate. Filtrando o pool já recebido, a busca continua sendo
        # uma requisição só.
        self._min_resolution = min_resolution
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
            "Pinterest (scraping) retornou %d imagens para query=%r "
            "(pool de %d, %d acima do piso de %dx%d)",
            len(selected), query[:80], len(medias),
            sum(1 for m in medias if _covers_slide(m, self._min_resolution)),
            self._min_resolution[0], self._min_resolution[1],
        )
        return [self._to_image(media, query) for media in selected]

    def related(self, pin_url: str, limit: int = 8) -> list[PinterestImage]:
        """Pins relacionados a um pin — o "mais como este" do Pinterest.

        É a busca da pessoa fixada: para um pin de retrato, os relacionados
        costumam trazer a mesma pessoa (similaridade visual do próprio
        Pinterest — nenhum reconhecimento facial). O recorte é o mesmo da
        busca por query: piso de resolução, retrato primeiro, ponto sorteado.

        Falha devolve `[]` em vez do mock: quem chama tem um fallback melhor
        que gradiente — a busca de retrato de sempre.
        """
        pinterest_dl = _load_pinterest_dl()
        if pinterest_dl is None:
            logger.warning(
                "Pessoa fixada ignorada: o pacote `pinterest-dl` não está "
                "instalado (pip install pinterest-dl)."
            )
            return []
        try:
            medias = pinterest_dl.with_api(timeout=self._timeout).related(
                pin_url,
                num=self._POOL_SIZE,
                min_resolution=(0, 0),
            )
        except Exception as exc:
            logger.warning(
                "Pins relacionados falharam para %s: %s",
                pin_url, type(exc).__name__,
            )
            return []

        medias = [m for m in medias if str(getattr(m, "src", "") or "")]
        if not medias:
            logger.info("Nenhum pin relacionado para %s.", pin_url)
            return []
        selected = self._select(medias, limit)
        logger.info(
            "Pinterest devolveu %d pin(s) relacionado(s) a %s (pool de %d).",
            len(selected), pin_url, len(medias),
        )
        return [self._to_image(media, "") for media in selected]

    def _select(self, medias: list[Any], limit: int) -> list[Any]:
        """Recorta o pool: alta resolução e retrato primeiro, num ponto sorteado.

        Três correções do mesmo pool. **Resolução** porque o slide tem 1080×1350
        e uma foto menor é ampliada no render — sai borrada com o texto nítido
        por cima. **Retrato** porque uma foto deitada perde metade da cena no
        recorte de cover; o Unsplash resolve isso com `orientation=portrait`, que
        a API interna não oferece. **Ponto sorteado** porque a busca vem ordenada
        por relevância e essa ordem é estável: sem isso o mesmo tema devolveria
        as mesmas fotos toda vez, o que parece cache do app e não é.

        As duas exigências caem em ordem quando o tema não tem acervo para elas:
        primeiro a orientação, depois a resolução. Um carrossel com foto pequena
        ainda é melhor que um carrossel de gradientes — e a foto pequena aparece
        na galeria da prévia, onde dá para trocar.
        """
        return _cut_pool(medias, limit, self._min_resolution)

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
# Instagram sem token — os endpoints web do site (como o instagram-php-scraper)
# ---------------------------------------------------------------------------

# O app id do site web do Instagram — o mesmo que o instagram-php-scraper manda
# em toda chamada anônima. Sem ele, os endpoints /api/v1/ respondem 401 direto.
_IG_APP_ID = "936619743392459"
_IG_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# Gateway do Scrape.do — transporte alternativo para as MESMAS chamadas quando
# o IP local está no muro (datacenter). A chamada sai pelos proxies deles.
_SCRAPEDO_ENDPOINT = "https://api.scrape.do/"


def _ig_slug(text: str) -> str:
    """Hashtag a partir de texto livre: sem acento, sem espaço, minúscula."""
    ascii_text = (
        unicodedata.normalize("NFKD", str(text or ""))
        .encode("ascii", "ignore")
        .decode("ascii")
    )
    return re.sub(r"[^a-z0-9_]", "", ascii_text.lower())


def _ig_username(query: str) -> str:
    """O @perfil digitado na busca, se houver. Vazio = busca por hashtag."""
    for token in str(query or "").split():
        if token.startswith("@") and len(token) > 1:
            return re.sub(r"[^a-z0-9._]", "", token[1:].lower())
    return ""


def _ig_dedupe(entries: list[Any]) -> list[Any]:
    """O mesmo post aparece em `top` e `recent` — a primeira ocorrência vale."""
    seen: set[str] = set()
    unique: list[Any] = []
    for entry in entries:
        if entry.media_id in seen:
            continue
        seen.add(entry.media_id)
        unique.append(entry)
    return unique


def _ig_entry_from_node(node: Any) -> SimpleNamespace | None:
    """Post no formato GraphQL (perfil e fallback de hashtag) → entrada comum.

    A entrada tem `.resolution` para reusar o recorte do pool (`_cut_pool`).
    Vídeo fica de fora: o slide é uma foto.
    """
    if not isinstance(node, dict) or node.get("is_video"):
        return None
    src = str(node.get("display_url") or "")
    if not src:
        return None
    dims = node.get("dimensions") or {}
    caption_edges = (node.get("edge_media_to_caption") or {}).get("edges") or []
    caption = ""
    if caption_edges:
        caption = str(((caption_edges[0] or {}).get("node") or {}).get("text") or "")
    try:
        resolution = (int(dims.get("width") or 0), int(dims.get("height") or 0))
    except (TypeError, ValueError):
        resolution = (0, 0)
    return SimpleNamespace(
        media_id=str(node.get("id") or node.get("shortcode") or ""),
        code=str(node.get("shortcode") or ""),
        src=src,
        thumb=str(node.get("thumbnail_src") or ""),
        resolution=resolution,
        # `accessibility_caption` ("May be an image of 1 person…") é o que
        # alimenta o casting por metadado, como o alt do Pinterest/Unsplash.
        alt=str(node.get("accessibility_caption") or "") or caption,
        username=str((node.get("owner") or {}).get("username") or ""),
    )


def _ig_entry_from_v1(media: Any) -> SimpleNamespace | None:
    """Post no formato da API v1 (seções de hashtag) → entrada comum."""
    if not isinstance(media, dict):
        return None
    media_type = media.get("media_type")
    if media_type == 2:  # vídeo/reel
        return None
    if media_type == 8:  # carrossel: a primeira foto é a capa
        children = media.get("carousel_media") or []
        cover = next(
            (c for c in children if isinstance(c, dict) and c.get("media_type") == 1),
            None,
        )
        if cover is not None:
            media = {
                **media,
                **{
                    key: cover[key]
                    for key in ("image_versions2", "original_width", "original_height")
                    if key in cover
                },
            }
    candidates = (media.get("image_versions2") or {}).get("candidates") or []
    candidates = [c for c in candidates if isinstance(c, dict) and c.get("url")]
    if not candidates:
        return None

    def _width(candidate: dict[str, Any]) -> int:
        try:
            return int(candidate.get("width") or 0)
        except (TypeError, ValueError):
            return 0

    best = max(candidates, key=_width)
    smallest = min(candidates, key=_width)
    try:
        resolution = (
            int(media.get("original_width") or _width(best)),
            int(media.get("original_height") or best.get("height") or 0),
        )
    except (TypeError, ValueError):
        resolution = (0, 0)
    caption = str(((media.get("caption") or {}) or {}).get("text") or "")
    code = str(media.get("code") or "")
    return SimpleNamespace(
        media_id=str(media.get("pk") or media.get("id") or code),
        code=code,
        src=str(best.get("url") or ""),
        thumb=str(smallest.get("url") or "") if smallest is not best else "",
        resolution=resolution,
        alt=str(media.get("accessibility_caption") or "") or caption,
        username=str((media.get("user") or {}).get("username") or ""),
    )


def _ig_tag_entries(payload: dict[str, Any]) -> list[Any]:
    """Fotos do payload de hashtag, nas DUAS formas que o endpoint responde.

    O contrato é interno e o Instagram alterna entre as seções da API v1
    (`data.top/recent.sections[].layout_content.medias[].media`) e o formato
    GraphQL antigo (`…hashtag.edge_hashtag_to_media.edges[].node`). Ler as
    duas custa pouco e é o que evita "parou de funcionar" num rollout deles.
    """
    if not isinstance(payload, dict):
        return []
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    entries: list[Any] = []
    for section_key in ("top", "recent"):
        sections = (data.get(section_key) or {}).get("sections") or []
        for section in sections:
            medias = ((section or {}).get("layout_content") or {}).get("medias") or []
            for item in medias:
                entry = _ig_entry_from_v1((item or {}).get("media"))
                if entry is not None:
                    entries.append(entry)
    for container in (data, payload.get("graphql") or {}):
        if not isinstance(container, dict):
            continue
        edges = (
            ((container.get("hashtag") or {}).get("edge_hashtag_to_media") or {}).get(
                "edges"
            )
            or []
        )
        for edge in edges:
            entry = _ig_entry_from_node((edge or {}).get("node"))
            if entry is not None:
                entries.append(entry)
    return _ig_dedupe(entries)


def _instagram_reason(response: requests.Response) -> str:
    """Motivo legível de um HTTP de erro do Instagram — sem falar de chave,
    porque não existe chave: o acesso anônimo é liberado e bloqueado por IP."""
    code = response.status_code
    if code in (401, 403):
        return (
            f"Instagram bloqueou o acesso anônimo (HTTP {code}) — sem login, o "
            "site libera e bloqueia por IP. Tente de outra rede ou configure "
            "INSTAGRAM_PROXY."
        )
    if code == 429:
        return "Instagram está limitando a taxa de chamadas (HTTP 429)."
    return f"Instagram respondeu HTTP {code}."


def _scrapedo_reason(response: requests.Response) -> str:
    """Motivo legível de um HTTP de erro vindo do gateway do Scrape.do.

    Os códigos são DELES (auth, créditos, concorrência do plano), não do
    Instagram — sem esta separação, um token errado apareceria na prévia como
    "Instagram bloqueou", que é a pista errada."""
    code = response.status_code
    if code == 401:
        return (
            "O Scrape.do recusou o token (HTTP 401) — token errado, sem "
            "créditos ou assinatura suspensa. Confira o painel do Scrape.do."
        )
    if code == 429:
        return (
            "O Scrape.do limitou a concorrência do plano (HTTP 429) — "
            "tente gerar de novo em alguns segundos."
        )
    if code == 502:
        return (
            "O Scrape.do não conseguiu uma resposta válida do Instagram mesmo "
            "com os retries dele (HTTP 502, sem consumo de crédito) — tente "
            "gerar de novo."
        )
    return f"O Scrape.do respondeu HTTP {code}."


class InstagramScrapeClient:
    """Instagram sem token — os endpoints web anônimos do próprio site.

    São os mesmos endpoints que o `instagram-php-scraper` usa: o perfil em
    `/api/v1/users/web_profile_info/` e a hashtag em `/api/v1/tags/web_info/`,
    ambos com o header `x-ig-app-id` do site. Não há credencial: o Instagram
    libera (e bloqueia) o acesso anônimo por IP, então a busca funciona na
    maior parte do tempo e cai no gradiente mock com o motivo quando o site
    devolve a página de login — o mesmo contrato instável do
    `pinterest_scrape`, com as mesmas ressalvas de compliance (ver README).

    A query vira **uma hashtag**: o Instagram não busca texto livre sem login.
    As palavras das queries de casting (HOOK/SCENE_QUERY_HINTS) são removidas
    antes — "#rotinamatinalwomanportrait" não existe — e um `@perfil` ou
    `#hashtag` digitados no tema/palavras-chave vencem a derivação.

    De um IP no balde do muro (datacenter — Render, AWS…), `proxy` dá um IP de
    saída só para estas chamadas (`INSTAGRAM_PROXY` no ambiente); os downloads
    do CDN seguem diretos, porque as URLs assinadas não são presas ao IP.
    `scrapedo_token` (`SCRAPEDO_TOKEN`) é a alternativa gerida: as MESMAS
    chamadas saem pelo gateway do Scrape.do com proxies residenciais
    (`super=true`) — o parse e os fallbacks não mudam, só o transporte. Com os
    dois definidos, o Scrape.do vence.
    """

    name = "instagram_scrape"
    _BASE = "https://www.instagram.com"

    def __init__(
        self,
        timeout: int = 20,
        min_resolution: tuple[int, int] = (0, 0),
        hint_words: Iterable[str] = (),
        proxy: str = "",
        proxy_insecure: bool = False,
        scrapedo_token: str = "",
    ):
        self._scrapedo_token = scrapedo_token
        # O gateway do Scrape.do tenta vários IPs por dentro antes de responder
        # — os 20s dimensionados para a chamada direta cancelariam metade das
        # chamadas no meio dos retries (a mesma lição do VISION_TIMEOUT).
        self._timeout = max(timeout, 60) if scrapedo_token else timeout
        # O mesmo piso do pinterest_scrape: foto menor que o slide é ampliada
        # no render e chega ao feed borrada.
        self._min_resolution = min_resolution
        self._hint_words = {w.strip().lower() for w in hint_words if w.strip()}
        # None deixa o requests honrar HTTPS_PROXY/HTTP_PROXY do ambiente.
        self._proxies = {"http": proxy, "https": proxy} if proxy else None
        # Portas-proxy de agregadores (ScrapeOps etc.) interceptam o TLS por
        # design e as docs deles mandam desligar a validação de certificado.
        # Opt-in explícito, e só para estas chamadas — que não carregam
        # credencial nenhuma (o acesso é anônimo por definição).
        self._verify = not proxy_insecure
        if proxy_insecure:
            # Sem isto, cada busca emitiria um InsecureRequestWarning — ruído
            # permanente que ensina a ignorar warnings.
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        # Por que a última busca caiu no mock. Vazio = não caiu.
        self.last_fallback_reason = ""

    def search(self, query: str, limit: int = 8) -> list[PinterestImage]:
        self.last_fallback_reason = ""
        username = _ig_username(query)
        tag = "" if username else self._tag_from(query)
        if not username and not tag:
            self.last_fallback_reason = (
                "A busca no Instagram precisa de uma #hashtag, um @perfil ou "
                "um tema com letras — a query ficou vazia depois da limpeza."
            )
            logger.warning(self.last_fallback_reason)
            return MockPinterestClient().search(query, limit)
        scope = f"@{username}" if username else f"#{tag}"

        try:
            if username:
                entries = self._profile_entries(username)
            else:
                entries = _ig_tag_entries(
                    self._get_json("/api/v1/tags/web_info/", {"tag_name": tag})
                )
        except requests.Timeout:
            logger.warning("Instagram timeout — usando fallback mock.")
            self.last_fallback_reason = f"Instagram não respondeu em {self._timeout}s."
            return MockPinterestClient().search(query, limit)
        except ValueError:
            # HTML (ou redirect) no lugar do JSON: o muro de login do Instagram.
            # O redirect já chega com o motivo preenchido pelo `_get_json`.
            if not self.last_fallback_reason:
                logger.warning(
                    "Instagram devolveu HTML (muro de login) — fallback mock."
                )
                self.last_fallback_reason = self._wall_reason()
            return MockPinterestClient().search(query, limit)
        except requests.RequestException as exc:
            logger.warning("Instagram erro: %s — usando fallback mock.", type(exc).__name__)
            self.last_fallback_reason = self.last_fallback_reason or (
                f"Falha de rede ao chamar o Instagram ({type(exc).__name__})."
            )
            return MockPinterestClient().search(query, limit)

        if not entries:
            logger.info("Instagram sem resultados para %s.", scope)
            self.last_fallback_reason = self.last_fallback_reason or (
                f"A busca no Instagram não retornou fotos para {scope}."
            )
            return MockPinterestClient().search(query, limit)

        selected = _cut_pool(entries, limit, self._min_resolution)
        logger.info(
            "Instagram retornou %d imagens para %s (pool de %d, %d acima do piso)",
            len(selected), scope, len(entries),
            sum(1 for e in entries if _covers_slide(e, self._min_resolution)),
        )
        return [self._to_image(entry, scope) for entry in selected]

    # ---- helpers ----

    def _tag_from(self, query: str) -> str:
        tokens = str(query or "").split()
        explicit = next((t for t in tokens if t.startswith("#") and len(t) > 1), "")
        if explicit:
            return _ig_slug(explicit)
        words = [t for t in tokens if t.lower() not in self._hint_words]
        return _ig_slug("".join(words))

    def _wall_reason(self) -> str:
        """O muro de login, com o remédio: a causa é o IP de saída, então o
        aviso da prévia precisa dizer QUAL IP trocar — o do servidor, o do
        proxy que já está configurado, ou o sorteado pelo Scrape.do."""
        if self._scrapedo_token:
            remedy = (
                "a chamada saiu pelos proxies residenciais do Scrape.do e "
                "mesmo assim caiu no muro — o IP muda a cada chamada, então "
                "gerar de novo costuma resolver"
            )
        elif self._proxies:
            remedy = (
                "o IP do proxy configurado em INSTAGRAM_PROXY também caiu no "
                "muro — troque o proxy por um de IP residencial/móvel"
            )
        else:
            remedy = (
                "IPs de datacenter (Render, AWS…) caem quase sempre nesse "
                "balde — configure INSTAGRAM_PROXY com um proxy de IP "
                "residencial ou rode de outra rede"
            )
        return (
            "O Instagram devolveu a página de login em vez de dados — o "
            f"acesso anônimo está bloqueado para este IP; {remedy}."
        )

    def _get_json(self, path: str, params: dict[str, str]) -> dict[str, Any]:
        if self._scrapedo_token:
            response = self._get_via_scrapedo(path, params)
        else:
            # Proxy rotativo (ScrapeOps etc.) sorteia outro IP de saída a cada
            # conexão: um exit no muro não condena os próximos, então o muro
            # com proxy configurado merece mais duas tentativas. Sem proxy o
            # IP é sempre o mesmo e repetir seria só latência.
            attempts = 3 if self._proxies else 1
            for attempt in range(1, attempts + 1):
                response = requests.get(
                    f"{self._BASE}{path}",
                    params=params,
                    headers={
                        "User-Agent": _IG_USER_AGENT,
                        "x-ig-app-id": _IG_APP_ID,
                        "Accept": "*/*",
                        "Referer": f"{self._BASE}/",
                    },
                    timeout=self._timeout,
                    proxies=self._proxies,
                    verify=self._verify,
                    # De um IP no balde do muro, a API 302-redireciona para
                    # /accounts/login/. O redirect já É a resposta: segui-lo só
                    # baixaria o HTML do login para falhar no json() logo
                    # adiante.
                    allow_redirects=False,
                )
                if not (300 <= response.status_code < 400):
                    break
                if attempt < attempts:
                    logger.info(
                        "Instagram devolveu o muro (HTTP %d) na tentativa "
                        "%d/%d — repetindo por outro IP do proxy.",
                        response.status_code, attempt, attempts,
                    )
        if 300 <= response.status_code < 400:
            logger.warning(
                "Instagram redirecionou a API para o login (HTTP %d) — "
                "fallback mock.",
                response.status_code,
            )
            self.last_fallback_reason = self._wall_reason()
            raise ValueError("login wall")
        if response.status_code >= 400:
            api = "Scrape.do" if self._scrapedo_token else "Instagram"
            logger.warning(
                "%s HTTP %d: %s", api, response.status_code, response.text[:200]
            )
            # Um erro do gateway (token, créditos, concorrência) não pode
            # aparecer na prévia como "Instagram bloqueou" — é a pista errada.
            self.last_fallback_reason = (
                _scrapedo_reason(response)
                if self._scrapedo_token
                else _instagram_reason(response)
            )
            response.raise_for_status()
        return response.json() or {}

    def _get_via_scrapedo(self, path: str, params: dict[str, str]) -> requests.Response:
        """A mesma chamada, saindo pelo gateway do Scrape.do.

        `extraHeaders` manda o x-ig-app-id num header `sd-*` POR CIMA do
        fingerprint deles (`customHeaders` substituiria os headers todos e
        estragaria o disfarce); `disableRedirection` faz o muro de login
        voltar como header em vez de virar o HTML da página de login.
        """
        response = requests.get(
            _SCRAPEDO_ENDPOINT,
            params={
                "token": self._scrapedo_token,
                "url": f"{self._BASE}{path}?{urlencode(params)}",
                # Proxies residenciais/móveis (10x créditos por chamada): os
                # de datacenter caem no mesmo balde do muro que o IP local.
                "super": "true",
                "extraHeaders": "true",
                "disableRedirection": "true",
            },
            headers={"sd-x-ig-app-id": _IG_APP_ID, "sd-referer": f"{self._BASE}/"},
            timeout=self._timeout,
        )
        if response.headers.get("Scrape.do-Target-Redirected-Location"):
            logger.warning(
                "Instagram redirecionou para o login (via Scrape.do) — "
                "fallback mock."
            )
            self.last_fallback_reason = self._wall_reason()
            raise ValueError("login wall")
        return response

    def _profile_entries(self, username: str) -> list[Any]:
        payload = self._get_json(
            "/api/v1/users/web_profile_info/", {"username": username}
        )
        user = (payload.get("data") or {}).get("user") or {}
        if user.get("is_private"):
            self.last_fallback_reason = (
                f"O perfil @{username} é privado — sem fotos para o carrossel."
            )
            return []
        edges = (user.get("edge_owner_to_timeline_media") or {}).get("edges") or []
        entries = [
            entry
            for entry in (_ig_entry_from_node((edge or {}).get("node")) for edge in edges)
            if entry is not None
        ]
        return _ig_dedupe(entries)

    def _to_image(self, entry: Any, scope: str) -> PinterestImage:
        if entry.code:
            source = f"{self._BASE}/p/{entry.code}/"
        elif scope.startswith("@"):
            source = f"{self._BASE}/{scope[1:]}/"
        else:
            source = f"{self._BASE}/explore/tags/{scope.lstrip('#')}/"
        by = f"@{entry.username}" if entry.username else scope
        return PinterestImage(
            # O prefixo evita colisão de id com pins na busca combinada.
            image_id=f"ig-{entry.media_id}",
            image_url=entry.src,
            thumb_url=entry.thumb,
            source_url=source,
            title=(entry.alt or scope)[:200],
            description="",
            attribution_text=f"{by} no Instagram",
        )


class CombinedImageClient:
    """Mais de uma busca na mesma geração — Instagram e Pinterest, intercalados.

    Cada cliente busca com o MESMO limite e o resultado é intercalado (um de
    cada, na ordem da lista) até fechar o limite: metade de cada fonte quando
    as duas respondem, e uma preenche o que a outra não trouxe. Resultado mock
    de um cliente que caiu no fallback fica de fora — gradiente sintético no
    meio de fotos reais só polui a galeria. Sem NENHUMA foto real, o mock
    volta com os motivos somados, como nos outros clientes.
    """

    def __init__(self, clients: list[Any], name: str = "combined"):
        self._clients = clients
        self.name = name
        # Por que a última busca caiu no mock. Vazio = não caiu.
        self.last_fallback_reason = ""

    def search(self, query: str, limit: int = 8) -> list[PinterestImage]:
        self.last_fallback_reason = ""
        pools: list[list[PinterestImage]] = []
        reasons: list[str] = []
        for client in self._clients:
            try:
                found = client.search(query, limit=limit)
            except Exception as exc:  # pragma: no cover - defensivo
                logger.warning(
                    "Busca combinada: %s falhou (%s).",
                    getattr(client, "name", "?"), type(exc).__name__,
                )
                found = []
            real = [img for img in found if not is_mock_image(img)]
            if not real:
                reasons.append(
                    getattr(client, "last_fallback_reason", "")
                    or f"{getattr(client, 'name', 'cliente')} não retornou fotos."
                )
            pools.append(real)

        merged: list[PinterestImage] = []
        seen: set[str] = set()
        for group in zip_longest(*pools):
            for img in group:
                if img is None or img.image_id in seen:
                    continue
                seen.add(img.image_id)
                merged.append(img)
        if not merged:
            self.last_fallback_reason = (
                " ".join(reasons) or "Nenhuma das buscas combinadas retornou fotos."
            )
            return MockPinterestClient().search(query, limit)
        return merged[:limit]

    def related(self, pin_url: str, limit: int = 8) -> list[PinterestImage]:
        """Pins relacionados (pessoa fixada) — repassado a quem sabe responder."""
        for client in self._clients:
            related = getattr(client, "related", None)
            if callable(related):
                return related(pin_url, limit=limit)
        return []


# ---------------------------------------------------------------------------
# Fábrica — escolhe o melhor cliente disponível automaticamente
# ---------------------------------------------------------------------------

def _pinterest_scrape_client(settings: Settings) -> PinterestScrapeClient:
    return PinterestScrapeClient(
        timeout=settings.request_timeout_seconds,
        # O piso de resolução é o próprio slide: exigir mais seria arbitrário
        # e exigir menos deixaria entrar foto que o render precisa ampliar.
        min_resolution=(settings.slide_width, settings.slide_height),
    )


def _instagram_scrape_client(settings: Settings) -> InstagramScrapeClient:
    return InstagramScrapeClient(
        timeout=settings.request_timeout_seconds,
        min_resolution=(settings.slide_width, settings.slide_height),
        # As palavras das queries de casting não entram na hashtag derivada.
        hint_words=f"{settings.hook_query_hints} {settings.scene_query_hints}".split(),
        proxy=settings.instagram_proxy,
        proxy_insecure=settings.instagram_proxy_insecure,
        scrapedo_token=settings.scrapedo_token,
    )


def build_pinterest_client(settings: Settings, override: str = "") -> PinterestClient:
    """Cliente de imagens conforme `IMAGE_PROVIDER`.

    `override` é a escolha feita na UI (o seletor de fonte dos formulários):
    vale só para aquela geração e vence o ambiente. Vazio ou desconhecido, o
    `IMAGE_PROVIDER` do ambiente decide, como sempre.

    Em `auto` (default) vale a escada de sempre: token oficial → chave do
    Unsplash → mock. O scraping (Pinterest sem token, Instagram e o modo
    combinado) fica **de fora** do automático de propósito — ele lê APIs não
    documentadas e as regras de uso dos sites são problema de quem publica
    (ver README). Entrar sozinho num ambiente sem chave transformaria
    "esqueci de configurar" em "estou raspando o Pinterest/Instagram", que
    não é uma decisão que o app deva tomar pelo usuário.

    Uma escolha explícita que não dá para atender (provider sem credencial)
    cai na mesma escada com um aviso no log, em vez de devolver um cliente que
    só sabe falhar.
    """
    unsplash_key = os.environ.get("UNSPLASH_ACCESS_KEY", "").strip()
    choice = (override or "").strip().lower() or settings.image_provider
    if choice not in IMAGE_PROVIDERS:
        choice = settings.image_provider

    if choice == "mock":
        logger.info("IMAGE_PROVIDER=mock — usando cliente mock.")
        return MockPinterestClient()
    if choice == "pinterest_scrape":
        # Sem o pacote, o cliente ainda é devolvido: ele explica a ausência no
        # `last_fallback_reason`, que a prévia mostra. Trocar por outro provider
        # aqui esconderia a única pista de por que o carrossel saiu diferente.
        logger.info("Fonte de imagens: Pinterest sem token.")
        return _pinterest_scrape_client(settings)
    if choice == "instagram_scrape":
        logger.info("Fonte de imagens: Instagram sem token.")
        return _instagram_scrape_client(settings)
    if choice == "instagram_pinterest":
        logger.info("Fonte de imagens: Instagram + Pinterest (sem token).")
        return CombinedImageClient(
            [_instagram_scrape_client(settings), _pinterest_scrape_client(settings)],
            name="instagram_pinterest",
        )
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