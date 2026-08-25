"""Orquestração: text composer + Pinterest + ranking.

Mudança v0.3: o usuário cola o texto do goviral.ai (URL externa, sem API/token).
A função deste serviço é estruturar o texto em slides, buscar imagens no Pinterest,
ranquear por relevância e preparar a estrutura para o SlideRenderer.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from app.adapters import (
    PinterestClient,
    PinterestImage,
    RankingProvider,
    TextComposer,
    build_pinterest_client,
    build_ranking_provider,
    build_text_composer,
)
from app.adapters.pinterest_client import is_mock_image, media_identity
from app.adapters.goviral_parser import goviral_blocks
from app.adapters.script_parser import compose_from_blocks, labeled_blocks
from app.adapters.vision_provider import VisionRankingProvider, build_vision_provider
from app.config import Settings
from app.services.casting import (
    MIN_IMAGE_OPTIONS,
    POOL_FOOD,
    POOL_HOOK,
    POOL_SCENE,
    apply_casting,
    cast_carousel,
)
from app.services.goviral_assets import assign_promo_slide
from app.services.pinned_person import load_pinned
from app.services.recent_media import load_recent, remember
from app.services.session_store import SessionStore, StoredProject, get_store

logger = logging.getLogger(__name__)


def _media_identity(image: PinterestImage) -> str:
    """Identidade estável do mesmo arquivo servido em tamanhos diferentes.

    A regra mora no adapter porque a busca usa a mesma para não repetir, entre
    gerações, as fotos que já saíram (ver `recent_media.py`) — duas cópias dela
    divergiriam em silêncio.
    """
    return media_identity(image.image_url)


@dataclass
class GenerationOutcome:
    """Resultado da execução do fluxo de geração."""

    project: StoredProject
    warnings: list[str]

    @property
    def project_id(self) -> str:
        return self.project.project_id


class GenerationService:
    """Ponto único de orquestração do carrossel."""

    # Piso de fotos por categoria. Cada pool precisa cobrir a cota pedida
    # **mais** as alternativas da galeria: buscar só o que entra no carrossel
    # deixava a prévia sem troca real, que era o sintoma de "as imagens estão
    # escassas". Nem toda foto da query de retrato traz alguém em cena, então o
    # piso é maior que o mínimo da galeria.
    HOOK_POOL_SIZE = 14
    FOOD_POOL_SIZE = 14
    SCENE_POOL_SIZE = 14
    FOOD_QUERY_HINTS = "food meal smoothie fruit breakfast healthy dish beverage"

    def __init__(
        self,
        settings: Settings,
        image_source: str = "",
        instagram_images_count: int | None = None,
    ):
        self._settings = settings
        self._image_source = (image_source or "").strip()
        self._instagram_images_count = instagram_images_count
        self._composer: TextComposer = build_text_composer(settings)
        # `image_source` é a escolha da UI (o seletor de fonte): vale para esta
        # geração e vence o IMAGE_PROVIDER do ambiente. Vazio = ambiente manda.
        # `avoid_media` são as fotos dos carrosséis recentes: o sorteio da busca
        # as deixa por último para a mesma hashtag não devolver o mesmo carrossel.
        self._pinterest: PinterestClient = build_pinterest_client(
            settings,
            override=image_source,
            instagram_images_count=instagram_images_count,
            avoid_media=load_recent(),
        )
        self._ranking: RankingProvider = build_ranking_provider(settings)
        self._vision: VisionRankingProvider | None = build_vision_provider(settings)
        self._store: SessionStore = get_store(settings.session_ttl_minutes)

    # ---- getters de diagnóstico ----
    @property
    def composer_name(self) -> str:
        return getattr(self._composer, "name", "unknown")

    @property
    def pinterest_provider_name(self) -> str:
        return getattr(self._pinterest, "name", "unknown")

    @property
    def ranking_provider_name(self) -> str:
        return getattr(self._ranking, "name", "unknown")

    @property
    def vision_provider_name(self) -> str:
        return self._vision.name if self._vision else "off"

    def store(self) -> SessionStore:
        return self._store

    # ---- fluxo principal ----
    def run(
        self,
        *,
        raw_text: str,
        theme: str,
        niche: str = "",
        keywords: list[str] | None = None,
        style: str = "quote",
        slides_count: int = 6,
        language: str = "pt-BR",
        script_blocks: list[str] | None = None,
        use_pinned_person: bool = False,
        person_images_count: int = 1,
        food_images_count: int = 0,
    ) -> GenerationOutcome:
        """Gera o carrossel.

        `script_blocks` é o modo manual: um bloco de texto por imagem, na ordem
        em que o usuário quer as imagens. Preenchido, ele manda — o texto já é a
        decisão do usuário e nenhum LLM reescreve por cima.

        `use_pinned_person` troca a busca de retrato do hook pelos pins
        relacionados à pessoa fixada na prévia (ver `pinned_person.py`). É
        opt-in por carrossel, e qualquer falha volta para a busca de sempre
        com o motivo nos avisos.

        O texto corrido segue a mesma regra quando ele PRÓPRIO traz os rótulos
        "Imagem N:". Escrever o rótulo é dizer em qual foto cada trecho entra;
        mandar isso para um LLM redistribuir só cria a chance de ele redistribuir
        diferente — e o sintoma disso é o hook aparecendo colado no texto de
        outro slide.

        O painel do goviral colado inteiro (Hook + Script N + Paragraph 1/2) é
        lido pelo mesmo princípio: os rótulos do painel já dizem o que é hook e o
        que são as duas caixas de cada imagem, então não há o que redistribuir.
        """
        warnings: list[str] = []
        if (
            self._instagram_images_count is not None
            and self.pinterest_provider_name == "instagram_pinterest"
        ):
            warnings.append(
                f"Instagram limitado a {self._instagram_images_count} foto(s): "
                "uma é priorizada para o hook e o restante do carrossel é "
                "preenchido pelo Pinterest usando os termos da busca."
            )
        manual = [b for b in (script_blocks or []) if b and b.strip()]

        if not manual:
            manual = goviral_blocks(raw_text)
            if manual:
                logger.info(
                    "Texto colado é o painel do goviral (hook + %d scripts) — "
                    "composição determinística, sem LLM.",
                    len(manual) - 1,
                )
                warnings.append(
                    f"Painel do goviral reconhecido: o hook e {len(manual) - 1} "
                    "script(s) viraram as imagens, sem LLM no caminho."
                )

        if not manual:
            manual = labeled_blocks(raw_text)
            if manual:
                logger.info(
                    "Texto colado traz rótulos de imagem (%d blocos) — "
                    "composição determinística, sem LLM.",
                    len(manual),
                )
                warnings.append(
                    f"O texto colado já indicava as imagens ({len(manual)} "
                    "rótulos): os blocos foram usados como escritos, sem LLM."
                )

        if manual:
            # 1a. Modo manual — determinístico, sem chamada de LLM.
            carousel = compose_from_blocks(manual, slides_count=slides_count)
            slides_count = len(carousel.slides) or slides_count
        else:
            if self._settings.llm_provider == "mock":
                warnings.append("Composição em modo mock — sem chamada real ao LLM.")

            # 1b. Compor carrossel a partir do texto colado
            carousel = self._composer.compose(
                raw_text,
                style=style,
                slides_count=slides_count,
                extra={"theme": theme, "language": language},
            )

        if not carousel.slides:
            warnings.append("Nenhum slide gerado — texto colado está vazio ou inválido.")

        person_images_count = min(max(int(person_images_count or 1), 1), slides_count)
        food_images_count = min(
            max(int(food_images_count or 0), 0),
            max(slides_count - person_images_count, 0),
        )
        if person_images_count > 1 or food_images_count:
            if self._settings.casting_enabled:
                warnings.append(
                    f"Cotas visuais: {person_images_count} pessoa(s), "
                    f"{food_images_count} foto(s) de comida e o restante em cenário geral."
                )
            else:
                warnings.append(
                    "As cotas de pessoas e comida precisam do casting ligado; "
                    "HOOK_SUBJECT=off manteve uma busca única sem restrição por assunto."
                )

        # 2. Buscar imagens
        query = self._build_query(theme, niche, keywords, raw_text)
        images = self._search_images(
            query,
            slides_count,
            warnings,
            use_pinned_person=use_pinned_person,
            person_images_count=person_images_count,
            food_images_count=food_images_count,
        )

        # 3. Ranking — visão primeiro (olha a foto), texto como fallback
        briefing = {
            "theme": theme,
            "niche": niche,
            "keywords": keywords or [],
            "raw_text": raw_text[:600],
            "style": style,
            "slides_count": slides_count,
            "image_source": self._image_source,
            "instagram_images_count": self._instagram_images_count,
            "person_images_count": person_images_count,
            "food_images_count": food_images_count,
        }
        vision_verdicts = self._see_safely(briefing, images, warnings)
        if vision_verdicts:
            ranking_results = vision_verdicts
        else:
            ranking_results = self._rank_safely(briefing, images, warnings)
        ordered_images = self._merge_ranking(images, ranking_results)

        carousel_dict = carousel.to_dict()

        # 4. Casting — o slide de hook fica com uma foto de pessoa, os demais
        # com cenário. Roda antes das posições porque é o casting que decide
        # qual foto está em qual slide.
        if self._settings.casting_enabled and ordered_images:
            preferred_hook_ids: set[str] = set()
            if (
                self._instagram_images_count is not None
                and self.pinterest_provider_name == "instagram_pinterest"
            ):
                preferred_hook_ids = {
                    image.image_id
                    for image in ordered_images
                    if image.pool == POOL_HOOK and image.image_id.startswith("ig-")
                }
            casting = cast_carousel(
                carousel_dict["slides"],
                ordered_images,
                vision_verdicts,
                hook_subject=self._settings.hook_subject,
                preferred_hook_ids=preferred_hook_ids,
                person_images_count=person_images_count,
                food_images_count=food_images_count,
            )
            apply_casting(carousel_dict["slides"], casting)
            warnings.extend(casting.warnings)

        if vision_verdicts:
            # A visão diz onde a foto tem espaço limpo; o slide guarda isso nos
            # mesmos pos_x/pos_y que o arraste na prévia grava, então o usuário
            # ainda corrige por cima se discordar.
            self._apply_vision_positions(
                carousel_dict["slides"], ordered_images, vision_verdicts
            )

        # 4b. O slide de fecho mostra o GoViral app — depois do casting, para os
        # prints não entrarem no pool de cenário dos outros slides.
        assign_promo_slide(carousel_dict["slides"], ordered_images, warnings)

        # 4c. Guardar o que ENTROU nos slides, para a próxima geração com a
        # mesma hashtag sortear outras fotos. Só os slides: marcar também as
        # alternativas da galeria esgotaria a memória em duas rodadas.
        self._remember_used(carousel_dict["slides"], ordered_images)

        # 5. Persistir
        project = self._store.create(
            briefing=briefing,
            carousel=carousel_dict,
            images=[img.to_dict() for img in ordered_images],
            ranking=[r.to_dict() for r in ranking_results],
            style=style,
            slides_count=slides_count,
            raw_text=raw_text,
        )
        return GenerationOutcome(project=project, warnings=warnings)

    # ---- helpers ----
    @staticmethod
    def _remember_used(
        slides: list[dict[str, Any]], ordered_images: list[PinterestImage]
    ) -> None:
        """Marca como "já usadas" as fotos que foram parar nos slides.

        A resolução da foto de cada slide é a mesma da prévia e do renderer:
        `image_id` quando o casting escolheu, e a rotação `i % len` quando não.
        Gradiente mock e os prints promocionais ficam de fora — um não é foto de
        acervo e o outro é sorteado de uma pasta local, não da busca.
        """
        if not ordered_images:
            return
        by_id = {img.image_id: img for img in ordered_images}
        identities: list[str] = []
        for index, slide in enumerate(slides):
            image_id = str(slide.get("image_id") or "")
            if image_id:
                image = by_id.get(image_id)
            elif "image_category" in slide:
                continue  # slot neutro — o VLM não confirmou categoria segura
            else:
                image = ordered_images[index % len(ordered_images)]
            if image is None or is_mock_image(image):
                continue
            identity = _media_identity(image)
            if identity:
                identities.append(identity)
        remember(identities)

    def _search_images(
        self,
        query: str,
        slides_count: int,
        warnings: list[str],
        use_pinned_person: bool = False,
        person_images_count: int = 1,
        food_images_count: int = 0,
    ) -> list[PinterestImage]:
        """Busca as fotos do carrossel em pools de pessoa, comida e cenário.

        Uma query só devolve o que o tema pede, e "rotina matinal" raramente
        devolve retrato na primeira página. Com casting ligado, cada assunto
        pedido ganha uma busca própria e cada foto carrega o pool de origem,
        que é o sinal que sobrevive mesmo sem VLM configurado.

        Com a pessoa fixada ligada, o pool de retrato vem dos pins relacionados
        ao pin fixado em vez da query — mais fotos da mesma pessoa. O pool de
        cenário não muda: a pessoa fixada é do hook, o resto continua b-roll.
        """
        if not self._settings.casting_enabled:
            if use_pinned_person:
                warnings.append(
                    "A pessoa fixada precisa do casting ligado (HOOK_SUBJECT) — "
                    "opção ignorada."
                )
            # Sem casting há uma busca só, então ela carrega o carrossel e a
            # galeria inteira: `slides × MIN_IMAGE_OPTIONS` fotos distintas.
            return self._search_pool(
                query,
                max(max(slides_count, 1) * MIN_IMAGE_OPTIONS, 6),
                "",
                warnings,
            )

        person_images_count = min(max(person_images_count, 1), slides_count)
        food_images_count = min(
            max(food_images_count, 0),
            max(slides_count - person_images_count, 0),
        )
        general_count = max(slides_count - person_images_count - food_images_count, 0)
        # Quantas buscas esta geração vai fazer. O total de fotos distintas que
        # a galeria precisa é repartido entre elas.
        active_pools = 1 + bool(food_images_count) + bool(general_count)

        hook_images: list[PinterestImage] = []
        if use_pinned_person:
            hook_images = self._pinned_person_pool(warnings)
        if not hook_images:
            hook_images = self._search_pool(
                f"{query} {self._settings.hook_query_hints}".strip(),
                self._pool_size(
                    self.HOOK_POOL_SIZE, person_images_count, slides_count, active_pools
                ),
                POOL_HOOK,
                warnings,
            )
        food_images: list[PinterestImage] = []
        if food_images_count:
            food_images = self._search_pool(
                f"{query} {self.FOOD_QUERY_HINTS}".strip(),
                self._pool_size(
                    self.FOOD_POOL_SIZE, food_images_count, slides_count, active_pools
                ),
                POOL_FOOD,
                warnings,
            )
        scene_images: list[PinterestImage] = []
        if general_count:
            scene_images = self._search_pool(
                f"{query} {self._settings.scene_query_hints}".strip(),
                self._pool_size(
                    self.SCENE_POOL_SIZE, general_count, slides_count, active_pools
                ),
                POOL_SCENE,
                warnings,
            )

        # As buscas se sobrepõem ("café mulher" e "café estética" trazem a
        # mesma foto às vezes). Sem deduplicar, a mesma foto apareceria várias
        # vezes na galeria e os mapas por image_id ficariam ambíguos. A primeira
        # ocorrência ganha, então o pool de hook mantém o rótulo.
        images: list[PinterestImage] = []
        seen: set[str] = set()
        seen_media: set[str] = set()
        for img in hook_images + food_images + scene_images:
            media_key = _media_identity(img)
            if img.image_id in seen or (media_key and media_key in seen_media):
                continue
            seen.add(img.image_id)
            if media_key:
                seen_media.add(media_key)
            images.append(img)

        if not images:
            warnings.append("Nenhuma imagem retornada pela busca.")
        elif any(is_mock_image(img) for img in images):
            self._warn_mock_images(warnings)
        return images

    @staticmethod
    def _pool_size(
        floor: int, quota: int, slides_count: int, active_pools: int = 1
    ) -> int:
        """Quantas fotos pedir a uma das buscas do casting.

        A cota é o que entra no carrossel; o resto é a galeria. Como
        `_deal_options` reparte as alternativas entre os slides em vez de dar o
        mesmo pool a todos, o acervo inteiro precisa de `slides ×
        MIN_IMAGE_OPTIONS` fotos distintas — 36 num carrossel de 6, 72 num de
        12. `active_pools` divide esse total entre as buscas que vão rodar.

        O piso continua valendo para o caso oposto: uma cota de 1 foto num
        carrossel curto ainda pede pool suficiente para a busca ter o que
        sortear e não repetir a geração anterior.
        """
        pools = max(int(active_pools or 0), 1)
        wanted = max(int(slides_count or 0), 1) * MIN_IMAGE_OPTIONS
        share = -(-wanted // pools)
        return max(int(floor), max(int(quota or 0), 0) + share)

    def _search_pool(
        self,
        query: str,
        limit: int,
        pool: str,
        warnings: list[str],
    ) -> list[PinterestImage]:
        try:
            search_pool = getattr(self._pinterest, "search_pool", None)
            if callable(search_pool):
                images = search_pool(query, limit=limit, pool=pool)
            else:
                images = self._pinterest.search(query, limit=limit)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Busca de imagens falhou: %s", type(exc).__name__)
            warnings.append("Busca de imagens falhou — sem resultados.")
            return []

        for img in images:
            if not img.pool:
                img.pool = pool

        # Sem casting, os avisos saem aqui; com casting, quem avisa é o
        # `_search_images`, senão o mesmo aviso apareceria duas vezes.
        if not pool:
            if not images:
                warnings.append("Nenhuma imagem retornada pela busca.")
            elif any(is_mock_image(img) for img in images):
                self._warn_mock_images(warnings)
        return images

    def _pinned_person_pool(self, warnings: list[str]) -> list[PinterestImage]:
        """Pool de retrato via pins relacionados à pessoa fixada. [] = fallback.

        Cada saída sem foto explica o motivo no aviso: a opção foi marcada de
        propósito, e um hook com outra pessoa sem explicação pareceria bug.
        """
        pinned = load_pinned()
        if not pinned:
            warnings.append(
                "Nenhuma pessoa fixada — fixe uma pela prévia (imagem 1). "
                "A busca de retrato de sempre foi usada."
            )
            return []
        related = getattr(self._pinterest, "related", None)
        if not callable(related):
            warnings.append(
                "A pessoa fixada usa os pins relacionados do Pinterest e só "
                "funciona com IMAGE_PROVIDER=pinterest_scrape — a busca de "
                "retrato de sempre foi usada."
            )
            return []
        try:
            images = related(pinned["pin_url"], limit=self.HOOK_POOL_SIZE)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(
                "Pins relacionados à pessoa fixada falharam: %s", type(exc).__name__
            )
            images = []
        if not images:
            warnings.append(
                "Os pins relacionados à pessoa fixada não retornaram fotos — "
                "a busca de retrato de sempre foi usada."
            )
            return []
        for img in images:
            img.pool = POOL_HOOK
        title = str(pinned.get("title") or "").strip()
        warnings.append(
            "A imagem 1 buscou pins relacionados à pessoa fixada"
            + (f" ({title[:60]})" if title else "")
            + " — confira na galeria se a pessoa é a mesma."
        )
        return images

    def _warn_mock_images(self, warnings: list[str]) -> None:
        # Cuidado: um cliente real que caiu no fallback continua se chamando
        # "unsplash"/"pinterest_scrape" — por isso a checagem é no resultado.
        reason = getattr(self._pinterest, "last_fallback_reason", "")
        detail = reason or (
            "Nenhuma fonte de imagens configurada — defina UNSPLASH_ACCESS_KEY "
            "ou escolha IMAGE_PROVIDER=pinterest_scrape (sem token)."
        )
        message = f"Imagens em modo mock (gradientes sintéticos). Motivo: {detail}"
        if message not in warnings:
            warnings.append(message)
        logger.warning("Carrossel gerado com imagens mock. Motivo: %s", detail)

    @staticmethod
    def _build_query(
        theme: str,
        niche: str,
        keywords: list[str] | None,
        raw_text: str,
    ) -> str:
        parts: list[str] = []
        if theme:
            parts.append(theme.strip())
        if niche:
            parts.append(niche.strip())
        if keywords:
            parts.extend(str(k).strip() for k in keywords if str(k).strip())
        # Adicionar primeiras 3 palavras significativas do raw_text
        if raw_text and not parts:
            for word in raw_text.split()[:5]:
                word = word.strip(".,;:!?\"'()[]")
                if len(word) >= 4:
                    parts.append(word)
                if len(parts) >= 3:
                    break
        query = " ".join(p for p in parts if p)
        return query or "viral"

    def _see_safely(
        self,
        briefing: dict[str, Any],
        images: list[PinterestImage],
        warnings: list[str],
    ) -> list[Any]:
        """Ranking por visão. [] significa "siga com o ranking textual"."""
        if not self._vision or not self._settings.ranking_enabled or not images:
            return []
        try:
            verdicts = self._vision.rank(briefing, images)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Vision falhou (%s) — caindo no ranking textual.", type(exc).__name__)
            return []
        if not verdicts:
            warnings.append(
                "Análise visual indisponível — ranking por texto foi usado."
            )
        return verdicts

    @staticmethod
    def _apply_vision_positions(
        slides: list[dict[str, Any]],
        ordered_images: list[PinterestImage],
        verdicts: list[Any],
    ) -> None:
        """Grava a posição sugerida em cada slide, in place.

        O slide usa a foto do seu `image_id` quando o casting já escolheu uma, e
        cai na rotação `i % len` (a mesma do renderer e da prévia) quando não.
        Slide cuja imagem a visão não avaliou fica com a âncora do papel.
        """
        if not ordered_images:
            return
        anchors = {
            v.image_id: v.position for v in verdicts if v.position is not None
        }
        if not anchors:
            return
        for i, slide in enumerate(slides):
            image_id = slide.get("image_id")
            if not image_id and "image_category" not in slide:
                image_id = ordered_images[i % len(ordered_images)].image_id
            if not image_id and "image_category" in slide:
                continue
            position = anchors.get(image_id)
            if position is None:
                continue
            slide["pos_x"], slide["pos_y"] = position

    def _rank_safely(
        self,
        briefing: dict[str, Any],
        images: list[PinterestImage],
        warnings: list[str],
    ) -> list[Any]:
        if not self._settings.ranking_enabled:
            warnings.append("Ranking desativado — ordem original mantida.")
            return []
        try:
            return self._ranking.rank(briefing, images)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Ranking falhou (%s) — usando ordem original.", type(exc).__name__)
            warnings.append("Ranking indisponível — ordem original mantida.")
            return []

    @staticmethod
    def _merge_ranking(
        images: list[PinterestImage], ranking: list[Any]
    ) -> list[PinterestImage]:
        if not ranking:
            return images
        score_map = {r.image_id: r.score for r in ranking}
        return sorted(images, key=lambda img: score_map.get(img.image_id, 0.0), reverse=True)
