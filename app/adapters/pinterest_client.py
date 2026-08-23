"""Cliente de imagens — Pinterest e Instagram sem token, Unsplash e mock.

Fluxo de prioridade (`IMAGE_PROVIDER=auto`, o default):
1. UNSPLASH_ACCESS_KEY definido → Unsplash (gratuito, sem aprovação especial)
2. Nenhuma chave                → Mock SVG (sempre funciona)

`IMAGE_PROVIDER=pinterest_scrape` troca isso pelo Pinterest **sem token** (via
`pinterest-dl`). `instagram_scrape` busca no Instagram sem token (a API interna
do site, os mesmos endpoints do instagram-php-scraper); `instagram_pinterest`
e `unsplash_pinterest` combinam duas buscas, intercaladas. Todos os modos com
scraping são opt-in explícitos: scraping nunca entra sozinho.

A API oficial v5 do Pinterest foi removida: o `/search/pins/` dela exige
Standard Access (aprovação manual da Pinterest), então o cliente nunca chegou a
buscar nada — e o `pinterest_scrape` faz a mesma busca sem credencial.

Variáveis de ambiente:
    IMAGE_PROVIDER           → auto | pinterest_scrape | unsplash
                               | instagram_scrape | instagram_pinterest
                               | unsplash_pinterest | mock
    UNSPLASH_ACCESS_KEY      → chave pública Unsplash (Access Key, não Secret Key)
    APIFY_TOKEN              → roda um actor da Apify que raspa o Instagram e
                               devolve dataset próprio (vence o Scrape.do)
    APIFY_ACTOR              → default: apify~instagram-scraper
    SCRAPEDO_TOKEN           → as mesmas chamadas da API web, saindo pelo
                               gateway do Scrape.do
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
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests

from app.config import IMAGE_PROVIDERS, Settings

logger = logging.getLogger(__name__)

# Prefixo dos ids gerados pelo MockPinterestClient. Serve para reconhecer
# resultados mock *depois* da busca — um cliente real que caiu no fallback
# continua se chamando "unsplash"/"pinterest_scrape", então o nome do cliente não
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


# `@perfil` é alvo do Instagram (a Apify sabe o que fazer com ele) e o `#` de
# uma hashtag vira token desconhecido em qualquer banco de imagens. Os dois
# chegam aqui porque o mesmo texto do formulário alimenta as três fontes.
_HANDLE_RE = re.compile(r"(?<!\w)@[\w.]+")
_HASHTAG_RE = re.compile(r"#(\w+)")


def _plain_terms(query: str) -> list[str]:
    """Os termos da query como uma busca por palavra-chave os entende.

    Tira `@perfil`, desembrulha `#hashtag` para a palavra e remove repetição —
    o mesmo termo costuma chegar duas vezes porque o tema e as dicas de casting
    se sobrepõem ("lifestyle cozy … aesthetic lifestyle travel" tinha
    *lifestyle* e *aesthetic* duplicados no log de produção). Termo repetido não
    melhora a relevância e ainda gasta uma das poucas vagas que uma busca por
    palavra-chave aguenta antes de não devolver nada.
    """
    cleaned = _HASHTAG_RE.sub(r"\1", _HANDLE_RE.sub(" ", str(query or "")))
    seen: set[str] = set()
    terms: list[str] = []
    for word in cleaned.split():
        key = "".join(
            char
            for char in unicodedata.normalize("NFKD", word.casefold())
            if not unicodedata.combining(char)
        ).strip("#@.,;:!?\"'()[]")
        if not key or key in seen:
            continue
        seen.add(key)
        terms.append(word)
    return terms


# Quantos termos das dicas de casting preservar quando a query é encurtada. As
# dicas ficam sempre no FIM da query (`"{tema} {hook_query_hints}"`), e são elas
# que fazem a foto de pessoa aparecer — cortar só a cauda salvaria o tema e
# perderia o casting. Quatro é o tamanho de `_hook_hints`: "woman portrait
# lifestyle aesthetic".
_HINT_TAIL = 4


def _query_attempts(query: str) -> list[str]:
    """A mesma busca, da mais específica para a mais genérica.

    Uma busca por palavra-chave devolve **zero** quando a query tem termos
    demais, e zero aqui significa cair no mock — cujos gradientes são
    deterministas por query, o que do lado de quem gera parece cache forçado.
    Medido em produção: `lifestyle cozy #aesthetic #praia #vibe bellebres girly
    aesthetic lifestyle travel interior workspace` não achava nada, enquanto
    `bellebres` sozinho acha pins no site.

    A redução do meio é o passo intermediário: mantém o tema (que o usuário
    reconhece no resultado) e as dicas do fim (que fazem o casting funcionar).
    O último passo é só o tema — se nem ele achar nada, não havia o que achar.
    """
    terms = _plain_terms(query)
    if not terms:
        return []
    attempts = [terms]
    if len(terms) > 6:
        tail = min(_HINT_TAIL, 6 // 2)
        attempts.append(terms[: 6 - tail] + terms[len(terms) - tail :])
    if len(terms) > 3:
        attempts.append(terms[:3])
    return [" ".join(attempt) for attempt in attempts]


def _prefer_unseen(
    images: list["PinterestImage"], avoid: Iterable[str], limit: int
) -> list["PinterestImage"]:
    """As `limit` primeiras, com o que já saiu em carrosséis recentes no fim.

    É o equivalente do `avoid` de `_cut_pool` para as fontes que devolvem
    `PinterestImage` já montada. Preferência, não veto: acervo pequeno continua
    devolvendo carrossel, só na ordem inversa.
    """
    seen = frozenset(avoid)
    if not seen:
        return images[:limit]
    fresh, stale = [], []
    for image in images:
        identity = media_identity(image.image_url)
        (stale if identity and identity in seen else fresh).append(image)
    return (fresh + stale)[:limit]



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

    def __init__(
        self,
        access_key: str,
        timeout: int = 20,
        target_size: tuple[int, int] = (1080, 1350),
        avoid_media: Iterable[str] = (),
    ):
        self._access_key = access_key
        self._timeout = timeout
        self._target_size = target_size
        # O que já saiu em carrosséis recentes — fica por último na escolha.
        self._avoid_media = frozenset(avoid_media)
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
        if not self._access_key:
            # Só o modo combinado constrói este cliente sem chave (a fábrica
            # não devolve o Unsplash solo sem ela). Falhar aqui, sem ir à
            # rede, deixa o motivo certo: um 401 do Unsplash diria "chave
            # recusada" — e chave não há.
            self.last_fallback_reason = (
                "O Unsplash está sem UNSPLASH_ACCESS_KEY configurada."
            )
            return MockPinterestClient().search(query, limit)
        # Pedir mais do que entra no carrossel é o que dá material para a
        # galeria da prévia e para deixar por último o que já foi usado.
        per_page = max(1, min(limit * 2, 30))
        try:
            results, page = self._results_for(query, per_page)
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

        if not results:
            # Sem isto o caminho seguinte é o mock — e o mock é DETERMINÍSTICO
            # por query (`hash(query)` escolhe a paleta), então uma query que
            # não acha nada devolve os mesmos gradientes para sempre. É o que
            # parece cache forçado do lado de quem gera duas vezes.
            self.last_fallback_reason = (
                "O Unsplash não tem fotos para esta busca. Termos demais ou "
                "muito específicos (hashtags, nome de perfil) devolvem zero — "
                "tente um tema mais curto."
            )
            logger.warning(
                "Unsplash retornou 0 imagens para query=%r mesmo após encurtar.",
                query[:120],
            )
            return MockPinterestClient().search(query, limit)

        images: list[PinterestImage] = []
        for item in results:
            urls = item.get("urls") or {}
            user = item.get("user") or {}
            full_url = (
                urls.get("raw") or urls.get("full") or urls.get("regular") or ""
            )
            images.append(PinterestImage(
                image_id=str(item.get("id") or ""),
                image_url=_sized_unsplash_url(full_url, self._target_size),
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
        chosen = _prefer_unseen(images, self._avoid_media, limit)
        logger.info(
            "Unsplash retornou %d imagens para query=%r (página %d, pool de %d)",
            len(chosen), query[:80], page, len(images),
        )
        return chosen

    def _results_for(self, query: str, per_page: int) -> tuple[list[Any], int]:
        """Resultados da busca, encurtando a query enquanto ela vier vazia.

        O Unsplash devolve **zero** quando a query tem termos demais — medido em
        produção com `lifestyle cozy #aesthetic #praia #vibe bellebres girly
        aesthetic lifestyle travel interior workspace`. Os degraus vêm de
        `_query_attempts`, que reduz pelo meio para preservar as duas pontas.

        A página é sorteada de novo a cada degrau: uma query diferente tem um
        catálogo diferente, e reaproveitar o número da tentativa anterior só
        aumentaria a chance de cair fora do fim dele.
        """
        for attempt, texto in enumerate(_query_attempts(query)):
            page = random.randint(1, self._PAGE_WINDOW)
            payload = self._request(texto, per_page, page)
            results = payload.get("results") or []
            if not results and int(payload.get("total_pages") or 0):
                # A página sorteada caiu além do fim do catálogo desta query.
                # Voltar para a 1 é o que sempre tem resultado; a aritmética
                # antiga (`(page-1) % total_pages + 1`) repetia a MESMA página
                # sempre que `total_pages >= page`, gastando a chamada à toa.
                page = 1
                results = self._request(texto, per_page, page).get("results") or []
            if results:
                if attempt:
                    logger.info(
                        "Unsplash: query encurtada para %r depois de 0 resultados.",
                        texto,
                    )
                return results, page
        return [], 0


def _sized_unsplash_url(url: str, target_size: tuple[int, int]) -> str:
    """Pede ao CDN uma imagem final que já cobre o slide em alta qualidade."""
    if not url:
        return ""
    width, height = target_size
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.update({
        "w": str(max(int(width), 1)),
        "h": str(max(int(height), 1)),
        "fit": "crop",
        "crop": "entropy",
        "q": "85",
        "auto": "format",
    })
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)
    )


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


def media_identity(url: str) -> str:
    """Identidade estável do mesmo arquivo servido em tamanhos diferentes.

    O Pinterest devolve o mesmo pin com IDs distintos entre buscas e caminhos
    `originals/`, `736x/` ou `474x/`. Comparar por `image_id` deixa essas cópias
    passarem por fotos diferentes — tanto na deduplicação de um carrossel quanto
    na memória do que já saiu nos carrosséis anteriores.
    """
    try:
        parts = urlsplit(url or "")
    except ValueError:
        return ""
    host = (parts.hostname or "").lower()
    path = parts.path.rstrip("/")
    if not host or not path:
        return ""
    if host == "i.pinimg.com" or host.endswith(".pinimg.com"):
        pieces = path.split("/")
        if len(pieces) > 2 and (pieces[1] == "originals" or pieces[1].endswith("x")):
            path = "/" + "/".join(pieces[2:])
        if "." in path.rsplit("/", 1)[-1]:
            path = path.rsplit(".", 1)[0]
    return f"{host}{path}".lower()


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


# Quanto o render pode ampliar uma foto antes de o resultado deixar de ser
# aceitável. 1,10× é o degrau que importa no acervo do Pinterest: `1024×1536` e
# `1000×1500`, os dois tamanhos mais comuns, precisam de 1,055× e 1,08× para
# cobrir 1080×1350 — ampliação que não se vê. Entre 1,05 e 1,10 não há nada, e
# acima de 1,10 o ganho de pool vem de arquivos que já chegam macios (medido em
# 2026-08-23: 40 pins usáveis com 1,00×, 69 com 1,10×, 71 com 1,15×).
_MAX_UPSCALE = 1.10


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
    """A foto tem pixel suficiente para preencher o slide sem borrar?

    O render faz `cover` da foto no canvas de 1080×1350: um pin de 474×711 é
    esticado para caber e chega ao feed borrado, com a legenda nítida por cima —
    a assinatura visual de post amador. O VLM não tem como reprovar isso, porque
    ele julga uma thumb de 474px: a resolução da origem não está na imagem que
    ele vê. Por isso o piso é aplicado aqui, na busca, e não no ranking.

    O piso é o **fator de ampliação**, não a medida bruta de cada lado. Exigir
    1080×1350 literais reprovava o formato mais comum do Pinterest por causa de
    56px de largura: medido em 2026-08-23, `1024×1536` é o tamanho nº 1 do
    acervo e precisa de 1,055× para cobrir o slide — ampliação invisível, e o
    corte antigo jogava fora 14 pins de 120 só nesse tamanho, mais 12 em
    `1000×1500`. Com a tolerância de `_MAX_UPSCALE`, o pool usável sobe de
    **40 para 69** dos mesmos 120 pins. Acima dela a foto ainda é recusada: o
    ponto do piso continua sendo não deixar origem pequena virar PNG borrado.

    Medida ausente conta como reprovada: o pool tem 120 pins e sobra material
    para exigir prova em vez de dar o benefício da dúvida.
    """
    min_width, min_height = minimum
    if min_width <= 0 and min_height <= 0:
        return True
    width, height = _resolution(media)
    if width <= 0 or height <= 0:
        return False
    return _cover_upscale(width, height, minimum) <= _MAX_UPSCALE


def _cover_upscale(width: int, height: int, minimum: tuple[int, int]) -> float:
    """Quanto o render precisaria ampliar esta foto para cobrir o slide."""
    min_width, min_height = minimum
    return max(min_width / width, min_height / height)


def _cut_pool(
    medias: list[Any],
    limit: int,
    min_resolution: tuple[int, int],
    *,
    avoid: Iterable[str] = (),
) -> list[Any]:
    """O recorte comum das buscas sem token (Pinterest e Instagram).

    O piso de resolução é estrito. Retrato continua sendo preferência, mas uma
    foto pequena nunca substitui uma foto grande: se o acervo não atingir o
    piso, a fonte devolve menos resultados ou cai no fallback.

    A escolha dentro do pool filtrado é uma **amostra aleatória**, não uma
    janela contígua. A janela era a correção original para o determinismo da
    busca (a API devolve a mesma ordem de relevância toda vez), e ela não
    funcionava: medido em 2026-08-22 na query "morning routine aesthetic", só
    **11 dos 40** pins passavam o piso de 1080×1350, então uma janela de 10
    tinha três posições possíveis e duas gerações repetiam **9,4 de 10** fotos.
    Amostrar do pool inteiro derruba a sobreposição para ~2,8 de 10; o resto
    quem resolve é `avoid`. A ordem de relevância é preservada na saída — o
    sorteio decide *quais* pins entram, não em que ordem.

    `avoid` são as identidades (`media_identity`) que já saíram em carrosséis
    recentes: elas vão para o fim da fila em vez de serem descartadas, porque
    um acervo pequeno não pode ficar sem foto só por já ter sido usado.
    """
    sharp = [m for m in medias if _covers_slide(m, min_resolution)]
    portrait = [m for m in sharp if _is_portrait(m)]
    pool = portrait if len(portrait) >= limit else sharp
    if len(pool) <= limit:
        return pool

    seen = frozenset(avoid)
    fresh, stale = [], []
    for index, media in enumerate(pool):
        identity = media_identity(str(getattr(media, "src", "") or ""))
        (stale if identity and identity in seen else fresh).append(index)
    if len(fresh) >= limit:
        picked = random.sample(fresh, limit)
    else:
        picked = fresh + random.sample(stale, limit - len(fresh))
    return [pool[index] for index in sorted(picked)]


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

    # Quantos pins pedir por busca. A biblioteca pagina sozinha (50 por
    # requisição, `delay` de 0,2s entre elas) até fechar o número — o custo
    # medido de 40 → 120 foi 3,0s → 4,8s, dentro do POST /generate.
    #
    # 40 era o número de quando o piso de resolução ainda cedia. Com o piso
    # estrito da v0.21 ele virou o gargalo dos dois sintomas: medido em
    # 2026-08-22 ("morning routine aesthetic"), 40 pins deixavam **11** acima
    # de 1080×1350 e 120 deixam **40**. Com 11 não há o que sortear (as fotos
    # se repetiam entre gerações) nem o que oferecer na galeria da prévia.
    _POOL_SIZE = 120

    def __init__(
        self,
        timeout: int = 20,
        min_resolution: tuple[int, int] = (0, 0),
        avoid_media: Iterable[str] = (),
    ):
        self._timeout = timeout
        # Piso de resolução: o tamanho do slide, para a foto não ser ampliada no
        # render. Filtrado aqui e não no parâmetro `min_resolution` da
        # biblioteca porque lá o corte acontece ANTES da contagem: para fechar
        # os pins pedidos ela pagina de novo, com um `sleep` a cada página,
        # dentro do POST /generate. Filtrando o pool já recebido, a busca
        # continua custando o mesmo número de requisições.
        self._min_resolution = min_resolution
        # O que já saiu em carrosséis recentes — vai para o fim do sorteio.
        self._avoid_media = frozenset(avoid_media)
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
            medias = self._pins_for(pinterest_dl, query)
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
            logger.info("Pinterest (scraping) sem resultados para query=%r.", query[:120])
            self.last_fallback_reason = (
                "A busca sem token no Pinterest não retornou pins nem com a "
                "query encurtada. Termos demais no tema e nas palavras-chave "
                "derrubam a relevância a zero."
            )
            return MockPinterestClient().search(query, limit)

        selected = self._select(medias, limit)
        if not selected:
            self.last_fallback_reason = (
                "O Pinterest não retornou fotos com resolução suficiente para "
                f"o slide ({self._min_resolution[0]}x{self._min_resolution[1]})."
            )
            logger.warning(self.last_fallback_reason)
            return MockPinterestClient().search(query, limit)
        logger.info(
            "Pinterest (scraping) retornou %d imagens para query=%r "
            "(pool de %d, %d acima do piso de %dx%d)",
            len(selected), query[:80], len(medias),
            sum(1 for m in medias if _covers_slide(m, self._min_resolution)),
            self._min_resolution[0], self._min_resolution[1],
        )
        return [self._to_image(media, query) for media in selected]

    def _pins_for(self, pinterest_dl: Any, query: str) -> list[Any]:
        """Os pins da busca, encurtando a query enquanto ela vier vazia.

        Uma busca por palavra-chave devolve zero quando a query é longa demais,
        e aí o carrossel cai no mock — cujos gradientes são deterministas por
        query, o que parece cache forçado. Uma busca por `bellebres` acha pins
        no site e não achava nada aqui só por causa da companhia. Os degraus
        vêm de `_query_attempts`.
        """
        scraper = pinterest_dl.with_api(timeout=self._timeout)
        for attempt, texto in enumerate(_query_attempts(query)):
            medias = scraper.search(texto, num=self._POOL_SIZE, min_resolution=(0, 0))
            if medias:
                if attempt:
                    logger.info(
                        "Pinterest: query encurtada para %r depois de 0 pins.", texto
                    )
                return list(medias)
        return []

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
        """Recorta o pool: alta resolução e retrato primeiro, sorteando quais.

        Três correções do mesmo pool. **Resolução** porque o slide tem 1080×1350
        e uma foto menor é ampliada no render — sai borrada com o texto nítido
        por cima. **Retrato** porque uma foto deitada perde metade da cena no
        recorte de cover; o Unsplash resolve isso com `orientation=portrait`, que
        a API interna não oferece. **Sorteio** porque a busca vem ordenada por
        relevância e essa ordem é estável: sem isso o mesmo tema devolveria as
        mesmas fotos toda vez, o que parece cache do app e não é.

        A orientação pode ceder quando não há retratos suficientes; o piso de
        resolução não cede, porque ampliar uma origem pequena degrada o PNG final.
        """
        return _cut_pool(medias, limit, self._min_resolution, avoid=self._avoid_media)

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

# Apify — `run-sync-get-dataset-items` roda o actor e devolve os itens na MESMA
# resposta, sem precisar de polling do run nem de uma segunda chamada ao
# dataset. É o que torna viável chamar de dentro do POST /generate. O teto
# desse endpoint é 300s (depois disso ele responde 408), mas o nosso teto é
# bem menor — ver `_APIFY_MIN_TIMEOUT`.
_APIFY_ENDPOINT = "https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items"
# O actor tem cold start (a máquina dele sobe antes de raspar), então o timeout
# dimensionado para um GET de JSON cancelaria quase toda chamada no meio. 90s
# fica acima do cold start típico e ainda abaixo do `--timeout 180` do gunicorn,
# que precisa sobrar para o fallback acontecer (a mesma conta do VISION_TIMEOUT).
_APIFY_MIN_TIMEOUT = 90


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


def _ig_entry_from_apify(item: Any) -> SimpleNamespace | None:
    """Item do dataset da Apify → a MESMA entrada comum das outras duas formas.

    Aqui está a diferença de fundo entre os dois serviços pagos: o Scrape.do é
    transporte — devolve o payload do próprio Instagram, então o parser dele é
    o mesmo de sempre. A Apify roda um *actor*, que raspa por conta própria e
    devolve o dataset **dele**, com nomes de campo próprios. Convertendo aqui,
    na fronteira, todo o resto do caminho (`_cut_pool`, o piso de resolução, o
    casting por metadado, `_to_image`) continua valendo sem saber de onde veio.

    Vídeo/reel fica de fora (o slide é uma foto) e o carrossel entra pela capa,
    as mesmas regras de `_ig_entry_from_v1`.
    """
    if not isinstance(item, dict):
        return None
    post_type = str(item.get("type") or "").lower()
    if post_type == "video" or (
        post_type != "sidecar" and (item.get("videoUrl") or item.get("isVideo"))
    ):
        return None

    # O schema atual publica `images` e `childPosts` para sidecars. Actors
    # alternativos costumam preencher apenas um deles, então a capa aceita as
    # duas formas sem transformar cada filho do mesmo post numa foto repetida.
    images = [str(u) for u in (item.get("images") or []) if isinstance(u, str) and u]
    children = [child for child in (item.get("childPosts") or []) if isinstance(child, dict)]
    photo_child = next(
        (
            child
            for child in children
            if str(child.get("type") or "").lower() != "video"
            and child.get("displayUrl")
        ),
        {},
    )
    src = (
        str(item.get("displayUrl") or "")
        or str(photo_child.get("displayUrl") or "")
        or (images[0] if images else "")
    )
    if not src:
        return None
    try:
        resolution = (
            int(
                item.get("dimensionsWidth")
                or item.get("originalWidth")
                or photo_child.get("dimensionsWidth")
                or photo_child.get("originalWidth")
                or 0
            ),
            int(
                item.get("dimensionsHeight")
                or item.get("originalHeight")
                or photo_child.get("dimensionsHeight")
                or photo_child.get("originalHeight")
                or 0
            ),
        )
    except (TypeError, ValueError):
        resolution = (0, 0)
    code = str(item.get("shortCode") or item.get("shortcode") or "")
    owner = item.get("owner") if isinstance(item.get("owner"), dict) else {}
    return SimpleNamespace(
        media_id=str(item.get("id") or item.get("pk") or code or src),
        code=code,
        src=src,
        # O actor não publica uma thumb reduzida; sem ela, a visão baixa a
        # foto cheia — custa mais token, mas é o que existe.
        thumb="",
        resolution=resolution,
        # `alt` do actor é o accessibility caption do Instagram ("May be an
        # image of 1 person…") — o mesmo sinal que alimenta o casting por
        # metadado nas outras duas formas. Sem ele, a legenda serve.
        alt=str(item.get("alt") or "") or str(item.get("caption") or ""),
        username=str(
            item.get("ownerUsername")
            or item.get("username")
            or owner.get("username")
            or ""
        ),
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
            "site libera e bloqueia por IP. Configure APIFY_TOKEN (raspa com "
            "sessão própria) ou troque a fonte das fotos para o Pinterest."
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


def _apify_reason(response: requests.Response) -> str:
    """Motivo legível de um HTTP de erro vindo da Apify.

    Os códigos são DELES (token, créditos, actor inexistente, run estourado),
    não do Instagram — pela mesma razão do `_scrapedo_reason`: "Instagram
    bloqueou" mandaria investigar o lugar errado.
    """
    code = response.status_code
    if code in (401, 403):
        return (
            f"A Apify recusou o token (HTTP {code}) — token errado, expirado "
            "ou sem permissão para rodar o actor. Confira APIFY_TOKEN no "
            "painel da Apify."
        )
    if code == 404:
        return (
            "A Apify não encontrou o actor (HTTP 404) — confira APIFY_ACTOR. "
            "O id vai com til no lugar da barra: `apify~instagram-scraper`."
        )
    if code == 402:
        return (
            "A Apify recusou o run por falta de crédito (HTTP 402) — confira "
            "o saldo/plano na conta."
        )
    if code == 408:
        return (
            "O actor da Apify não terminou a tempo (HTTP 408) — costuma ser "
            "cold start somado a uma busca grande; gerar de novo com o actor "
            "já aquecido costuma resolver."
        )
    if code == 429:
        return (
            "A Apify limitou a taxa de runs (HTTP 429) — tente gerar de novo "
            "em alguns segundos."
        )
    return f"A Apify respondeu HTTP {code}."


class InstagramScrapeClient:
    """Instagram sem token — os endpoints web anônimos do próprio site.

    São os mesmos endpoints que o `instagram-php-scraper` usa: o perfil em
    `/api/v1/users/web_profile_info/` e a hashtag em `/api/v1/tags/web_info/`,
    ambos com o header `x-ig-app-id` do site. Não há credencial.

    **O endpoint de hashtag deixou de ser anônimo** (medido em 2026-08-16):
    ele responde `302 → /accounts/login/` em toda saída testada — datacenter
    (Render), IP residencial doméstico e os exits residenciais do ScrapeOps,
    os três no mesmo 302, com e sem bootstrap de cookie (`csrftoken`). O HTML
    de `/explore/tags/<tag>/` também não traz mais os posts embutidos. Ou
    seja: o muro é gate do **endpoint**, não do IP, e nenhum proxy passa por
    ele — o que resta é o motivo escrito na prévia (ver `_wall_reason`) e o
    modo `instagram_pinterest`, onde o Pinterest preenche o carrossel.

    `proxy` (`INSTAGRAM_PROXY`) foi **removido** por isso: ele custava dinheiro
    e não mudava a resposta. Sobraram dois serviços pagos, que não são a mesma
    coisa e por isso têm caminhos diferentes no código:

    * `apify_token` (`APIFY_TOKEN`) — **não é proxy**: roda um actor que raspa
      com sessão própria e devolve dataset estruturado (`_ig_entry_from_apify`).
      É o único dos dois com chance real na hashtag, então **vence** quando os
      dois estão configurados.
    * `scrapedo_token` (`SCRAPEDO_TOKEN`) — transporte: as MESMAS chamadas da
      API web saem pelo gateway deles (`super=true`). Payload e parse não
      mudam. Contra o muro da hashtag não passa; serve ao caminho `@perfil`,
      cujo `429` é cota por IP de verdade.

    Sem nenhum dos dois, a chamada sai direta — o que ainda funciona para
    `@perfil` até a cota do IP estourar. Os downloads do CDN seguem sempre
    diretos, porque as URLs assinadas não são presas ao IP.

    A query vira **uma hashtag**: o Instagram não busca texto livre sem login.
    As palavras das queries de casting (HOOK/SCENE_QUERY_HINTS) são removidas
    antes — "#rotinamatinalwomanportrait" não existe — e um `@perfil` ou
    `#hashtag` digitados no tema/palavras-chave vencem a derivação.
    """

    name = "instagram_scrape"
    _BASE = "https://www.instagram.com"

    def __init__(
        self,
        timeout: int = 20,
        min_resolution: tuple[int, int] = (0, 0),
        hint_words: Iterable[str] = (),
        scrapedo_token: str = "",
        apify_token: str = "",
        apify_actor: str = "apify~instagram-scraper",
    ):
        self._scrapedo_token = scrapedo_token
        self._apify_token = apify_token
        self._apify_actor = apify_actor or "apify~instagram-scraper"
        # Os dois serviços tentam vários IPs por dentro antes de responder (a
        # Apify ainda sobe uma máquina antes disso), então os 20s dimensionados
        # para a chamada direta cancelariam metade das chamadas no meio dos
        # retries deles — a mesma lição do VISION_TIMEOUT.
        if apify_token:
            self._timeout = max(timeout, _APIFY_MIN_TIMEOUT)
        elif scrapedo_token:
            self._timeout = max(timeout, 60)
        else:
            self._timeout = timeout
        # O mesmo piso do pinterest_scrape: foto menor que o slide é ampliada
        # no render e chega ao feed borrada.
        self._min_resolution = min_resolution
        self._hint_words = {w.strip().lower() for w in hint_words if w.strip()}
        # O casting faz buscas por pessoa, comida e cenário, mas @perfil e
        # hashtag resolvem para a mesma URL da Apify. Reusar o dataset evita
        # pagar e esperar runs idênticos dentro da mesma geração.
        self._apify_cache: dict[str, list[Any]] = {}
        # Por que a última busca caiu no mock. Vazio = não caiu.
        self.last_fallback_reason = ""

    def search(self, query: str, limit: int = 8) -> list[PinterestImage]:
        return self._search(query, limit=limit, exact_apify_limit=False)

    def search_exact(self, query: str, limit: int = 8) -> list[PinterestImage]:
        """Busca com cota exata na Apify, usada pelo modo combinado.

        O `search()` normal mantém a folga para resolução/casting. Quando o
        usuário escolhe quantas fotos quer do Instagram, `resultsLimit`,
        `maxItems` e o limite do dataset precisam refletir exatamente essa
        escolha, sem o piso antigo de 12 itens pagos.
        """
        return self._search(query, limit=limit, exact_apify_limit=True)

    def _search(
        self,
        query: str,
        *,
        limit: int,
        exact_apify_limit: bool,
    ) -> list[PinterestImage]:
        self.last_fallback_reason = ""
        limit = max(int(limit or 0), 0)
        if limit == 0:
            return []
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
            if self._apify_token:
                entries = self._apify_entries(
                    username, tag, limit, exact_limit=exact_apify_limit
                )
            elif username:
                entries = self._profile_entries(username)
            else:
                entries = _ig_tag_entries(
                    self._get_json("/api/v1/tags/web_info/", {"tag_name": tag})
                )
        except requests.Timeout:
            logger.warning("%s timeout — usando fallback mock.", self._transport)
            self.last_fallback_reason = (
                f"{self._transport} não respondeu em {self._timeout}s."
            )
            return MockPinterestClient().search(query, limit)
        except ValueError:
            # HTML (ou redirect) no lugar do JSON: o muro de login do Instagram.
            # O redirect já chega com o motivo preenchido pelo `_get_json`, e a
            # Apify preenche o dela — o muro só é o palpite de último caso.
            if not self.last_fallback_reason:
                logger.warning(
                    "Instagram devolveu HTML (muro de login) — fallback mock."
                )
                self.last_fallback_reason = self._wall_reason()
            return MockPinterestClient().search(query, limit)
        except requests.RequestException as exc:
            logger.warning(
                "%s erro: %s — usando fallback mock.",
                self._transport, type(exc).__name__,
            )
            self.last_fallback_reason = self.last_fallback_reason or (
                f"Falha de rede ao chamar {self._transport} ({type(exc).__name__})."
            )
            return MockPinterestClient().search(query, limit)

        if not entries:
            logger.info("Instagram sem resultados para %s.", scope)
            self.last_fallback_reason = self.last_fallback_reason or (
                f"A busca no Instagram não retornou fotos para {scope}."
            )
            return MockPinterestClient().search(query, limit)

        selected = _cut_pool(entries, limit, self._min_resolution)
        if not selected:
            self.last_fallback_reason = (
                "O Instagram não retornou fotos com resolução suficiente para "
                f"o slide ({self._min_resolution[0]}x{self._min_resolution[1]})."
            )
            logger.warning(self.last_fallback_reason)
            return MockPinterestClient().search(query, limit)
        logger.info(
            "Instagram retornou %d imagens para %s (pool de %d, %d acima do piso)",
            len(selected), scope, len(entries),
            sum(1 for e in entries if _covers_slide(e, self._min_resolution)),
        )
        return [self._to_image(entry, scope) for entry in selected]

    # ---- helpers ----

    @property
    def _transport(self) -> str:
        """Quem atendeu a chamada — o nome que vai no log e no motivo da
        prévia. Um timeout da Apify escrito como "Instagram não respondeu"
        mandaria investigar o Instagram, que nem foi chamado por nós."""
        if self._apify_token:
            return "A Apify"
        if self._scrapedo_token:
            return "O Scrape.do"
        return "O Instagram"

    def _tag_from(self, query: str) -> str:
        tokens = str(query or "").split()
        explicit = next((t for t in tokens if t.startswith("#") and len(t) > 1), "")
        if explicit:
            return _ig_slug(explicit)
        words = [t for t in tokens if t.lower() not in self._hint_words]
        return _ig_slug("".join(words))

    def _wall_reason(self) -> str:
        """O muro de login — e o remédio, que **não** é trocar de proxy.

        Este aviso já mandou "trocar o proxy por um de IP residencial/móvel",
        no diagnóstico de que o muro era gate de IP. O diagnóstico era falso, e
        custou caro: medido em 2026-08-16, o `/api/v1/tags/web_info/` responde
        `302 → /accounts/login/` em TODA saída testada — datacenter (Render),
        IP residencial doméstico e os exits residenciais do ScrapeOps, os três
        no mesmo 302. O gate é do **endpoint**, não do IP: nenhum proxy passa
        por ele, e mandar caçar proxy melhor só queimava tempo e crédito.
        """
        return (
            "O Instagram exige login neste endpoint — a busca anônima devolve "
            "a página de login em QUALQUER IP de saída, então nem proxy nem "
            "SCRAPEDO_TOKEN resolvem (o gate é do endpoint, não do IP). "
            "Configure APIFY_TOKEN, que raspa com sessão própria em vez de só "
            "trocar o IP, ou troque a fonte das fotos para o Pinterest sem "
            "token (pinterest_scrape) ou o modo instagram_pinterest, que "
            "preenche o carrossel com o Pinterest quando o Instagram cai."
        )

    def _get_json(self, path: str, params: dict[str, str]) -> dict[str, Any]:
        if self._scrapedo_token:
            response = self._get_via_scrapedo(path, params)
        else:
            # Sem retry: o IP de saída é sempre o mesmo, então repetir só
            # gastaria latência dentro do POST /generate. (Havia 3 tentativas
            # aqui quando existia o INSTAGRAM_PROXY, sob a teoria de que outro
            # exit do pool rotativo passaria pelo muro — teoria falsificada:
            # o 302 é gate de endpoint. Ver `_wall_reason`.)
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
                # De um IP no balde do muro, a API 302-redireciona para
                # /accounts/login/. O redirect já É a resposta: segui-lo só
                # baixaria o HTML do login para falhar no json() logo adiante.
                allow_redirects=False,
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

    def _apify_entries(
        self,
        username: str,
        tag: str,
        limit: int,
        *,
        exact_limit: bool = False,
    ) -> list[Any]:
        """Roda o actor da Apify e converte o dataset dele nas entradas comuns.

        `run-sync-get-dataset-items` roda e devolve os itens na MESMA resposta:
        sem isso seriam três chamadas (start, polling do run, leitura do
        dataset) dentro do `POST /generate`.

        O pool pedido é 3× o limite (piso de 12) porque o piso de resolução e a
        preferência por retrato descartam parte do resultado — mas nada perto
        dos 40 pins que o Pinterest traz de graça: **cada item do actor é
        pago**, então pool grande aqui é conta maior para jogar a maior parte
        fora.
        """
        scope = f"@{username}" if username else f"#{tag}"
        cache_key = f"{username}|{tag}"
        if cache_key in self._apify_cache:
            logger.info("Reusando dataset da Apify para %s.", scope)
            return self._apify_cache[cache_key]

        wanted = max(limit, 1) if exact_limit else max(limit * 3, 12)
        if username:
            # Para perfil, a URL direta é mais previsível que `searchType=user`,
            # que ainda passaria pela busca do Instagram para achar o mesmo
            # perfil que já sabemos qual é.
            payload = {
                "directUrls": [f"{self._BASE}/{username}/"],
                "resultsType": "posts",
                "resultsLimit": wanted,
            }
        else:
            # A hashtag também vai por URL direta. `search`+`searchType` parou
            # de entregar posts (medido em 2026-08-16): a fase de busca do
            # actor virou uma consulta ao Google, que casa a hashtag errada
            # ("aesthetic" achou #gaesthetic) e devolve como único item do
            # dataset a ENTIDADE do resultado (searchTerm/postsCount), sem
            # raspar post nenhum — "Crawled 0/1 pages" no log do run. A URL
            # de /explore/tags/ pula essa busca e o actor devolve os posts no
            # formato que `_ig_entry_from_apify` espera.
            payload = {
                "directUrls": [f"{self._BASE}/explore/tags/{tag}/"],
                "resultsType": "posts",
                "resultsLimit": wanted,
            }
        response = requests.post(
            _APIFY_ENDPOINT.format(actor=self._apify_actor),
            params={
                "token": self._apify_token,
                # Teto de itens FATURADOS (actors pay-per-result). O
                # `resultsLimit` acima é um pedido ao actor; este é o limite da
                # conta, para um actor que ignore o pedido não virar surpresa
                # na fatura.
                "maxItems": wanted,
                # `maxItems` limita cobrança, não o tamanho da resposta. O
                # endpoint síncrono também aceita os parâmetros do dataset.
                "limit": wanted,
                "clean": "1",
                # Teto do run. Sem ele o actor herda o timeout da configuração
                # DELE (que pode ser minutos): a resposta viria depois de o
                # gunicorn já ter matado o worker, e worker morto não faz
                # fallback. A folga é para o motivo chegar à prévia.
                "timeout": max(self._timeout - 10, 30),
                "format": "json",
            },
            json=payload,
            timeout=self._timeout,
        )
        if response.status_code >= 400:
            logger.warning(
                "Apify HTTP %d: %s", response.status_code, response.text[:200]
            )
            self.last_fallback_reason = _apify_reason(response)
            response.raise_for_status()
        try:
            items = response.json()
        except ValueError:
            # Sem isto, o `except ValueError` do `search` leria a resposta
            # ilegível da Apify como muro de login do Instagram — a pista
            # errada, e o Instagram nem foi chamado por nós.
            self.last_fallback_reason = (
                "A Apify respondeu algo que não é JSON — o actor pode ter "
                "falhado no meio do run. Confira o run no painel da Apify."
            )
            raise
        if not isinstance(items, list):
            self.last_fallback_reason = (
                "A Apify não devolveu uma lista de itens — confira se "
                f"APIFY_ACTOR ({self._apify_actor}) é um actor de Instagram."
            )
            raise ValueError("apify dataset")
        entries = [
            entry
            for entry in (_ig_entry_from_apify(item) for item in items)
            if entry is not None
        ]
        logger.info(
            "Apify devolveu %d itens (%d fotos utilizáveis) para %s.",
            len(items), len(entries), scope,
        )
        if items and not entries:
            # Dataset cheio e nada aproveitável = ou veio só vídeo/reel, ou os
            # nomes de campo do actor não são os que o mapeador espera. A
            # segunda é a hipótese cara de descobrir sem esta pista.
            self.last_fallback_reason = (
                f"A Apify devolveu {len(items)} itens, mas nenhuma foto "
                "utilizável — se a busca não era só de vídeos, o actor "
                f"({self._apify_actor}) usa outros nomes de campo que o "
                "esperado (displayUrl/images, dimensionsWidth/Height)."
            )
        deduped = _ig_dedupe(entries)
        self._apify_cache[cache_key] = deduped
        return deduped

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


def _query_without_instagram_target(query: str) -> str:
    """Remove @perfil e conserva #hashtag como termo para a outra fonte."""
    cleaned = re.sub(r"(?<!\w)@[\w.]+", " ", str(query or ""))
    cleaned = re.sub(r"#([\w]+)", r"\1", cleaned)
    return " ".join(cleaned.split()) or "lifestyle aesthetic"


class CombinedImageClient:
    """Mais de uma busca na mesma geração — duas fontes intercaladas
    (Instagram + Pinterest, Unsplash + Pinterest).

    Cada cliente busca com o MESMO limite e o resultado é intercalado (um de
    cada, na ordem da lista) até fechar o limite: metade de cada fonte quando
    as duas respondem, e uma preenche o que a outra não trouxe. Resultado mock
    de um cliente que caiu no fallback fica de fora — gradiente sintético no
    meio de fotos reais só polui a galeria. Sem NENHUMA foto real, o mock
    volta com os motivos somados, como nos outros clientes.
    """

    def __init__(
        self,
        clients: list[Any],
        name: str = "combined",
        source_limits: dict[str, int] | None = None,
    ):
        self._clients = clients
        self.name = name
        self._source_remaining = {
            source: max(int(limit), 0)
            for source, limit in (source_limits or {}).items()
        }
        # A primeira busca é o hook. Ela extrai a cota inteira da Apify uma vez,
        # devolve uma foto e guarda o restante para o pool de cenário.
        self._source_carryover: dict[str, list[PinterestImage]] = {}
        # Por que a última busca caiu no mock. Vazio = não caiu.
        self.last_fallback_reason = ""

    def search(self, query: str, limit: int = 8) -> list[PinterestImage]:
        return self.search_pool(query, limit=limit, pool="")

    def search_pool(
        self,
        query: str,
        limit: int = 8,
        *,
        pool: str = "",
    ) -> list[PinterestImage]:
        self.last_fallback_reason = ""
        pools: list[list[PinterestImage]] = []
        reasons: list[str] = []
        for client in self._clients:
            client_name = getattr(client, "name", "?")
            client_query = query
            if self.name == "instagram_pinterest" and client_name != "instagram_scrape":
                client_query = _query_without_instagram_target(query)
            try:
                found, attempted = self._search_client(
                    client, client_query, limit=limit, pool=pool
                )
            except Exception as exc:  # pragma: no cover - defensivo
                logger.warning(
                    "Busca combinada: %s falhou (%s).",
                    client_name, type(exc).__name__,
                )
                found = []
                attempted = True
            real = [img for img in found if not is_mock_image(img)]
            if attempted and not real:
                reasons.append(
                    getattr(client, "last_fallback_reason", "")
                    or f"{client_name} não retornou fotos."
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

    def _search_client(
        self,
        client: Any,
        query: str,
        *,
        limit: int,
        pool: str,
    ) -> tuple[list[PinterestImage], bool]:
        name = getattr(client, "name", "?")
        if name not in self._source_remaining:
            return client.search(query, limit=limit), True

        carryover = self._source_carryover.get(name, [])
        if pool and pool != "hook" and carryover:
            found = carryover[:limit]
            self._source_carryover[name] = carryover[len(found):]
            return found, False

        remaining = self._source_remaining[name]
        if remaining <= 0:
            return [], False

        # Sem casting há uma única busca; não extraia mais do que cabe nela.
        target = remaining if pool else min(remaining, limit)
        exact_search = getattr(client, "search_exact", None)
        found = (
            exact_search(query, limit=target)
            if callable(exact_search)
            else client.search(query, limit=target)
        )
        real = [img for img in found if not is_mock_image(img)]
        # A extração exata já foi tentada; repetir o mesmo @perfil só duplicaria
        # posts e cobrança. O que sobrou fica em memória para o segundo pool.
        self._source_remaining[name] = 0
        if pool == "hook":
            for image in real:
                image.pool = image.pool or "hook"
            self._source_carryover[name] = real[1:]
            return real[:1], True
        return real[:limit], True

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

def _pinterest_scrape_client(
    settings: Settings, avoid_media: Iterable[str] = ()
) -> PinterestScrapeClient:
    return PinterestScrapeClient(
        timeout=settings.request_timeout_seconds,
        # O piso de resolução é o próprio slide: exigir mais seria arbitrário
        # e exigir menos deixaria entrar foto que o render precisa ampliar.
        min_resolution=(settings.slide_width, settings.slide_height),
        avoid_media=avoid_media,
    )


def _instagram_scrape_client(settings: Settings) -> InstagramScrapeClient:
    return InstagramScrapeClient(
        timeout=settings.request_timeout_seconds,
        min_resolution=(settings.slide_width, settings.slide_height),
        # As palavras das queries de casting não entram na hashtag derivada.
        hint_words=f"{settings.hook_query_hints} {settings.scene_query_hints}".split(),
        scrapedo_token=settings.scrapedo_token,
        apify_token=settings.apify_token,
        apify_actor=settings.apify_actor,
    )


def build_pinterest_client(
    settings: Settings,
    override: str = "",
    instagram_images_count: int | None = None,
    avoid_media: Iterable[str] = (),
) -> PinterestClient:
    """Cliente de imagens conforme `IMAGE_PROVIDER`.

    `override` é a escolha feita na UI (o seletor de fonte dos formulários):
    vale só para aquela geração e vence o ambiente. Vazio ou desconhecido, o
    `IMAGE_PROVIDER` do ambiente decide, como sempre.

    Em `auto` (default) a escada é: chave do Unsplash → mock. A API oficial v5
    do Pinterest era o primeiro degrau e **foi removida**: o `/search/pins/`
    dela exige Standard Access (aprovação manual da Pinterest) que este projeto
    nunca teve, então o degrau nunca chegou a rodar — e o `pinterest_scrape`,
    que existe desde a v0.7, faz a mesma busca sem token nenhum.

    O scraping (Pinterest sem token, Instagram e o modo combinado) fica **de
    fora** do automático de propósito — ele lê APIs não documentadas e as
    regras de uso dos sites são problema de quem publica (ver README). Entrar
    sozinho num ambiente sem chave transformaria "esqueci de configurar" em
    "estou raspando o Pinterest/Instagram", que não é uma decisão que o app
    deva tomar pelo usuário.

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
        return _pinterest_scrape_client(settings, avoid_media)
    if choice == "instagram_scrape":
        logger.info("Fonte de imagens: Instagram sem token.")
        return _instagram_scrape_client(settings)
    if choice == "instagram_pinterest":
        logger.info("Fonte de imagens: Instagram + Pinterest (sem token).")
        source_limits = None
        if instagram_images_count is not None:
            source_limits = {"instagram_scrape": max(int(instagram_images_count), 1)}
        return CombinedImageClient(
            [
                _instagram_scrape_client(settings),
                _pinterest_scrape_client(settings, avoid_media),
            ],
            name="instagram_pinterest",
            source_limits=source_limits,
        )
    if choice == "unsplash_pinterest":
        # O par entra INTEIRO mesmo sem a chave do Unsplash — a mesma regra do
        # instagram_pinterest, cujo Instagram também pode estar fadado a cair
        # (sem APIFY_TOKEN): a fonte que falha devolve mock com o motivo, o
        # combinado descarta o mock e a outra preenche. Trocar o par por um
        # cliente solo aqui esconderia POR QUE metade das fotos não veio.
        logger.info("Fonte de imagens: Unsplash + Pinterest.")
        return CombinedImageClient(
            [
                UnsplashClient(
                    unsplash_key,
                    timeout=settings.request_timeout_seconds,
                    target_size=(settings.slide_width, settings.slide_height),
                    avoid_media=avoid_media,
                ),
                _pinterest_scrape_client(settings, avoid_media),
            ],
            name="unsplash_pinterest",
        )
    if choice == "unsplash":
        if unsplash_key:
            return UnsplashClient(
                unsplash_key,
                timeout=settings.request_timeout_seconds,
                target_size=(settings.slide_width, settings.slide_height),
                avoid_media=avoid_media,
            )
        logger.warning("IMAGE_PROVIDER=unsplash sem UNSPLASH_ACCESS_KEY.")

    if unsplash_key:
        logger.info("Usando Unsplash.")
        return UnsplashClient(
            access_key=unsplash_key,
            timeout=settings.request_timeout_seconds,
            target_size=(settings.slide_width, settings.slide_height),
            avoid_media=avoid_media,
        )

    logger.info("Nenhuma chave de imagens configurada — usando cliente mock.")
    return MockPinterestClient()
