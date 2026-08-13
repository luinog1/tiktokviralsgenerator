"""goviral_assets/ — os prints do GoViral app que fecham o carrossel.

Os photo posts de referência terminam mostrando o app na tela do celular ("i
use this app called Go Viral…"). A pasta `goviral_assets/` na raiz do repo
guarda essas fotos; a geração sorteia um punhado delas para a galeria e coloca
uma no ÚLTIMO slide (o CTA) — a mesma mecânica das fotos de busca: um palpite
inicial, trocável na galeria da prévia com um clique.

A pasta é o próprio liga/desliga: sem ela (ou vazia), nada acontece — nenhuma
variável de ambiente nova. As imagens são servidas por `GET /goviral-assets/…`
(rota no blueprint goviral) e o renderer as abre direto do disco, porque um
`requests.get` numa URL relativa não tem para onde ir.
"""

from __future__ import annotations

import os
import random

from app.adapters.pinterest_client import PinterestImage

# Raiz do repo: app/services/ → app/ → raiz.
GOVIRAL_ASSETS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "goviral_assets",
)

GOVIRAL_IMAGE_ID_PREFIX = "goviral-"
GOVIRAL_URL_PREFIX = "/goviral-assets/"

# Quantas alternativas entram na galeria da prévia. A primeira vira o slide;
# as outras existem para a troca ser um clique, como nas fotos de busca.
GALLERY_SIZE = 5

_IMAGE_EXTENSIONS = {".webp", ".png", ".jpg", ".jpeg"}


def list_asset_files() -> list[str]:
    """Nomes das imagens da pasta, ordenados. `[]` se a pasta não existe."""
    try:
        names = os.listdir(GOVIRAL_ASSETS_DIR)
    except OSError:
        return []
    return sorted(
        n for n in names
        if os.path.splitext(n)[1].lower() in _IMAGE_EXTENSIONS
    )


def resolve_asset(filename: str) -> str | None:
    """Caminho absoluto de um asset, ou None. `basename` barra path traversal."""
    name = os.path.basename(str(filename or ""))
    path = os.path.join(GOVIRAL_ASSETS_DIR, name)
    return path if name and os.path.isfile(path) else None


def pick_gallery(k: int = GALLERY_SIZE) -> list[PinterestImage]:
    """Sorteia até `k` prints como imagens no formato que o app já usa.

    O sorteio é o que evita todo carrossel sair com o mesmo print — o mesmo
    motivo do ponto de corte sorteado na busca do Pinterest.
    """
    files = list_asset_files()
    if not files:
        return []
    chosen = random.sample(files, min(k, len(files)))
    return [
        PinterestImage(
            image_id=f"{GOVIRAL_IMAGE_ID_PREFIX}{os.path.splitext(name)[0]}",
            image_url=f"{GOVIRAL_URL_PREFIX}{name}",
            source_url="https://content.goviralai.app/",
            title="GoViral app",
            description="print do GoViral app para o slide de fecho",
            attribution_text="GoViral",
            pool="goviral",
        )
        for name in chosen
    ]


def assign_promo_slide(
    slides: list[dict],
    images: list[PinterestImage],
    warnings: list[str],
) -> None:
    """Última imagem do carrossel = print do GoViral app, in place.

    Roda DEPOIS do casting (senão os prints entrariam no pool de cenário dos
    outros slides) e só quando há pelo menos 2 slides — com um só, o "último"
    seria o hook, e o hook é da foto com pessoa.
    """
    gallery = pick_gallery()
    if not gallery or len(slides) < 2:
        return
    images.extend(gallery)
    slides[-1]["image_id"] = gallery[0].image_id
    warnings.append(
        "A última imagem recebeu um print do GoViral app — há mais "
        f"{len(gallery) - 1} alternativa(s) na galeria da prévia."
    )


__all__ = [
    "GOVIRAL_ASSETS_DIR",
    "GOVIRAL_IMAGE_ID_PREFIX",
    "GOVIRAL_URL_PREFIX",
    "GALLERY_SIZE",
    "list_asset_files",
    "resolve_asset",
    "pick_gallery",
    "assign_promo_slide",
]
