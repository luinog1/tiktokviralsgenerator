"""Testes do ranking por visão (VLM) e do auto-posicionamento do texto."""

from __future__ import annotations

import base64
import json

import pytest
import requests

from app.adapters.pinterest_client import PinterestImage
from app.adapters.vision_provider import (
    VisionRankingProvider,
    VisionVerdict,
    build_vision_provider,
)
from app.config import Settings
from app.services.generation import GenerationService


def _settings(**over) -> Settings:
    env = {
        "VISION_ENABLED": "true",
        "VISION_API_BASE_URL": "https://api-inference.modelscope.cn/v1",
        "VISION_API_KEY": "ms-fake-key",
        "VISION_MODEL": "Qwen/Qwen3-VL-235B-A22B-Instruct",
        "REQUEST_TIMEOUT_SECONDS": "5",
    }
    env.update(over)
    return Settings.from_env(env)


def _photos(n: int = 2) -> list[PinterestImage]:
    return [
        PinterestImage(
            image_id=f"ph{i}",
            image_url=f"https://images.unsplash.com/full-{i}",
            thumb_url=f"https://images.unsplash.com/small-{i}",
            source_url="https://unsplash.com/p",
            title="",
        )
        for i in range(n)
    ]


class _Resp:
    def __init__(self, payload, status=200, text=""):
        self._payload = payload
        self.status_code = status
        self.text = text or json.dumps(payload)

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


def _reply(content: str, status: int = 200) -> _Resp:
    return _Resp({"choices": [{"message": {"content": content}}]}, status=status)


class _ThumbResp:
    """Resposta fake do GET da thumb — o que `_download_as_data_uri` consome."""

    def __init__(self, body=b"fake-jpeg-bytes", status=200, content_type="image/jpeg"):
        self.content = body
        self.status_code = status
        self.headers = {"Content-Type": content_type}


_FAKE_THUMB_DATA_URI = (
    "data:image/jpeg;base64," + base64.b64encode(b"fake-jpeg-bytes").decode()
)


@pytest.fixture(autouse=True)
def thumb_downloads(monkeypatch):
    """Toda thumb "baixa" bytes fake — nenhum teste sai para a rede.

    Devolve a lista de URLs baixadas, para os testes que afirmam sobre elas.
    Um teste que precise de outro comportamento re-monkeypatcha `requests.get`.
    """
    calls: list[str] = []

    def fake_get(url, **kwargs):
        calls.append(url)
        return _ThumbResp()

    monkeypatch.setattr(requests, "get", fake_get)
    return calls


# ---------------------------------------------------------------- configuração
def test_vision_off_by_default():
    assert build_vision_provider(Settings.from_env({})) is None


def test_vision_needs_model_id():
    """Sem VISION_MODEL não há default seguro — 404 só gastaria tempo."""
    assert build_vision_provider(_settings(VISION_MODEL="")) is None


def test_vision_inherits_llm_credentials():
    """Quem usa o mesmo endpoint para texto e visão não repete a chave."""
    settings = Settings.from_env({
        "LLM_API_BASE_URL": "https://api-inference.modelscope.cn/v1",
        "LLM_API_KEY": "ms-key",
        "VISION_ENABLED": "true",
        "VISION_MODEL": "PaddlePaddle/ERNIE-4.5-VL-28B-A3B-Paddle",
    })
    assert settings.vision_configured
    assert settings.vision_api_key == "ms-key"


def test_vision_enabled_alone_is_not_configured():
    assert not Settings.from_env({"VISION_ENABLED": "true"}).vision_configured


# --------------------------------------------------------------- chamada feita
def test_downloads_the_thumb_and_sends_the_bytes(monkeypatch, thumb_downloads):
    """A thumb é baixada pelo app e vai como data URI — a URL não serve.

    Mandar a URL deixava o download por conta do endpoint: o servidor da
    ModelScope (na China) não alcança o i.pinimg.com e a chamada inteira
    voltava HTTP 400 "context deadline exceeded". A versão pequena continua
    sendo a que vai: basta para julgar composição e corta tokens de visão.
    """
    captured = {}

    def fake_post(url, **kwargs):
        captured["json"] = kwargs["json"]
        captured["headers"] = kwargs["headers"]
        return _reply('{"results":[{"image_id":"ph0","score":0.9,"anchor":"top"}]}')

    monkeypatch.setattr(requests, "post", fake_post)
    VisionRankingProvider(_settings()).rank({"theme": "café"}, _photos(1))

    assert thumb_downloads == ["https://images.unsplash.com/small-0"]
    content = captured["json"]["messages"][1]["content"]
    urls = [p["image_url"]["url"] for p in content if p["type"] == "image_url"]
    assert urls == [_FAKE_THUMB_DATA_URI]
    assert captured["headers"]["Authorization"] == "Bearer ms-fake-key"
    schema = captured["json"]["response_format"]["json_schema"]["schema"]
    item_schema = schema["properties"]["results"]["items"]
    assert "subject" in item_schema["required"]
    assert item_schema["properties"]["subject"]["enum"] == [
        "woman", "man", "person", "food", "scene"
    ]


@pytest.mark.parametrize("failure", ["conexao", "http-403", "grande-demais"])
def test_unfetchable_thumb_stays_out_of_the_call(monkeypatch, failure, caplog):
    """Thumb que não baixa fica FORA — como URL ela derrubaria a chamada inteira.

    O endpoint baixa cada URL do lado de lá: UMA inalcançável (o 403 do caminho
    474x para .png, por exemplo) devolve 400 para a requisição toda, levando
    junto os veredictos das fotos que estavam boas.
    """
    def fake_get(url, **kwargs):
        if url.endswith("small-1"):
            if failure == "conexao":
                raise requests.ConnectionError()
            if failure == "http-403":
                return _ThumbResp(status=403)
            return _ThumbResp(body=b"x" * (2 * 1024 * 1024 + 1))
        return _ThumbResp()

    captured = {}

    def fake_post(url, **kwargs):
        captured["json"] = kwargs["json"]
        return _reply('{"results":[]}')

    monkeypatch.setattr(requests, "get", fake_get)
    monkeypatch.setattr(requests, "post", fake_post)
    with caplog.at_level("WARNING"):
        VisionRankingProvider(_settings()).rank({}, _photos(3))

    content = captured["json"]["messages"][1]["content"]
    images = [p for p in content if p["type"] == "image_url"]
    assert len(images) == 2
    sent = content[0]["text"]
    assert "ph0" in sent and "ph2" in sent and "ph1" not in sent
    assert "1 de 3 thumbs" in caplog.text


def test_no_downloadable_thumb_skips_the_call(monkeypatch):
    """Sem nenhuma foto baixada não há o que perguntar — ranking textual."""
    def fake_get(url, **kwargs):
        raise requests.ConnectionError()

    def boom(*a, **k):
        pytest.fail("não deveria chamar o endpoint de visão sem nenhuma foto")

    monkeypatch.setattr(requests, "get", fake_get)
    monkeypatch.setattr(requests, "post", boom)
    assert VisionRankingProvider(_settings()).rank({}, _photos(2)) == []


@pytest.mark.parametrize("content_type,expected_mime", [
    ("image/png", "image/png"),
    ("image/jpeg; charset=binary", "image/jpeg"),
    ("application/octet-stream", "image/jpeg"),
])
def test_data_uri_carries_the_content_type(monkeypatch, content_type, expected_mime):
    """PNG continua PNG; content-type que não é imagem cai no JPEG do CDN."""
    monkeypatch.setattr(
        requests, "get", lambda url, **k: _ThumbResp(content_type=content_type)
    )
    captured = {}

    def fake_post(url, **kwargs):
        captured["json"] = kwargs["json"]
        return _reply('{"results":[]}')

    monkeypatch.setattr(requests, "post", fake_post)
    VisionRankingProvider(_settings()).rank({}, _photos(1))

    content = captured["json"]["messages"][1]["content"]
    urls = [p["image_url"]["url"] for p in content if p["type"] == "image_url"]
    assert urls[0].startswith(f"data:{expected_mime};base64,")


def test_mock_gradients_skip_the_call(monkeypatch):
    """Gradiente sintético não tem o que julgar visualmente."""
    def boom(*a, **k):
        pytest.fail("não deveria chamar o endpoint de visão")

    monkeypatch.setattr(requests, "post", boom)
    mock_img = PinterestImage(
        image_id="mock-1-abc",
        image_url="data:image/svg+xml;utf8,<svg/>",
        source_url="",
        title="",
    )
    assert VisionRankingProvider(_settings()).rank({}, [mock_img]) == []


def test_caps_images_per_call(monkeypatch):
    captured = {}

    def fake_post(url, **kwargs):
        captured["json"] = kwargs["json"]
        return _reply('{"results":[]}')

    monkeypatch.setattr(requests, "post", fake_post)
    VisionRankingProvider(_settings()).rank({}, _photos(20))

    content = captured["json"]["messages"][1]["content"]
    images = [p for p in content if p["type"] == "image_url"]
    assert len(images) == VisionRankingProvider.MAX_IMAGES


# ------------------------------------------------------------------- parsing
def test_parses_score_and_anchor(monkeypatch):
    monkeypatch.setattr(requests, "post", lambda *a, **k: _reply(
        '{"results":[{"image_id":"ph0","score":0.82,"anchor":"bottom-left",'
        '"reason":"topo tem o rosto"}]}'
    ))
    verdicts = VisionRankingProvider(_settings()).rank({}, _photos(1))
    assert len(verdicts) == 1
    assert verdicts[0].score == pytest.approx(0.82)
    assert verdicts[0].position == (0.34, 0.76)


def test_strips_thinking_block_and_markdown_fence(monkeypatch):
    """Qwen3-VL thinking e ERNIE abrem com <think>; o JSON vem depois."""
    monkeypatch.setattr(requests, "post", lambda *a, **k: _reply(
        '<think>A foto 0 tem espaço no topo...</think>\n'
        '```json\n{"results":[{"image_id":"ph0","score":0.7,"anchor":"top"}]}\n```'
    ))
    verdicts = VisionRankingProvider(_settings()).rank({}, _photos(1))
    assert [v.anchor for v in verdicts] == ["top"]


def test_reads_json_from_reasoning_content(monkeypatch):
    """A ModelScope devolve o texto em `reasoning_content` com `content` vazio.

    Era o caminho do "Vision não devolveu JSON utilizável" com HTTP 200: a
    resposta estava completa, só não no campo em que o parser olhava.
    """
    monkeypatch.setattr(requests, "post", lambda *a, **k: _Resp({"choices": [{
        "message": {
            "content": "",
            "reasoning_content":
                'Olhando a foto: há espaço no topo.\n'
                '{"results":[{"image_id":"ph0","score":0.8,"anchor":"top",'
                '"subject":"woman"}]}',
        },
    }]}))
    verdicts = VisionRankingProvider(_settings()).rank({}, _photos(1))
    assert [(v.image_id, v.subject) for v in verdicts] == [("ph0", "woman")]


def test_reads_content_returned_as_parts(monkeypatch):
    """Alguns endpoints devolvem `content` como lista, no formato do request."""
    monkeypatch.setattr(requests, "post", lambda *a, **k: _Resp({"choices": [{
        "message": {"content": [
            {"type": "text", "text": '{"results":[{"image_id":"ph0",'},
            {"type": "text", "text": '"score":0.6,"anchor":"bottom"}]}'},
        ]},
    }]}))
    verdicts = VisionRankingProvider(_settings()).rank({}, _photos(1))
    assert verdicts[0].position == (0.5, 0.76)


def test_salvages_verdicts_from_a_truncated_response(monkeypatch):
    """Resposta cortada no limite de tokens não pode zerar o que já chegou.

    Com 8 imagens a lista é longa; o item cortado se perde, os completos valem.
    """
    monkeypatch.setattr(requests, "post", lambda *a, **k: _reply(
        '{"results":[{"image_id":"ph0","score":0.9,"anchor":"top","subject":"woman"},'
        '{"image_id":"ph1","score":0.4,"anchor":"bottom","subject":"scene"},'
        '{"image_id":"ph2","score":0.7,"anch'
    ))
    verdicts = VisionRankingProvider(_settings()).rank({}, _photos(3))
    assert [v.image_id for v in verdicts] == ["ph0", "ph1"]


def test_truncated_reason_with_braces_does_not_break_the_salvage(monkeypatch):
    """Uma chave dentro de uma string não pode fechar o objeto cedo demais."""
    monkeypatch.setattr(requests, "post", lambda *a, **k: _reply(
        '{"results":[{"image_id":"ph0","score":0.5,"anchor":"top",'
        '"reason":"chave } e aspas \\" no meio"},{"image_id":"ph1","sco'
    ))
    verdicts = VisionRankingProvider(_settings()).rank({}, _photos(2))
    assert [v.image_id for v in verdicts] == ["ph0"]
    assert verdicts[0].reason == 'chave } e aspas " no meio'


def test_asks_the_provider_to_skip_the_reasoning(monkeypatch):
    """Numa variante Thinking o raciocínio come o orçamento e o JSON nem começa.

    `chat_template_kwargs.enable_thinking=false` é o parâmetro documentado do
    vLLM (o servidor da ModelScope API-Inference) para a série Qwen3.
    """
    captured = {}

    def fake_post(url, **kwargs):
        captured["json"] = kwargs["json"]
        return _reply('{"results":[]}')

    monkeypatch.setattr(requests, "post", fake_post)
    VisionRankingProvider(_settings()).rank({}, _photos(1))

    assert captured["json"]["chat_template_kwargs"] == {"enable_thinking": False}


def test_retries_without_the_thinking_flag_when_the_gateway_rejects_it(monkeypatch):
    """Gateway que não conhece o parâmetro devolve 400 — não pode virar fallback.

    O 400 volta na hora, então repetir sem o campo não ameaça o timeout do
    worker, e quem já funcionava continua funcionando.
    """
    calls = []

    def fake_post(url, **kwargs):
        calls.append(kwargs["json"])
        if "chat_template_kwargs" in kwargs["json"]:
            return _Resp({"error": "unknown field"}, status=400)
        return _reply('{"results":[{"image_id":"ph0","score":0.7,"anchor":"top"}]}')

    monkeypatch.setattr(requests, "post", fake_post)
    verdicts = VisionRankingProvider(_settings()).rank({}, _photos(1))

    assert len(calls) == 2
    assert "chat_template_kwargs" not in calls[1]
    assert [v.image_id for v in verdicts] == ["ph0"]


def test_retries_without_json_schema_when_an_older_gateway_rejects_it(monkeypatch):
    calls = []

    def fake_post(url, **kwargs):
        calls.append(dict(kwargs["json"]))
        if "response_format" in kwargs["json"]:
            return _Resp({"error": "unsupported response_format"}, status=400)
        return _reply(
            '{"results":[{"image_id":"ph0","score":0.7,'
            '"anchor":"top","subject":"scene"}]}'
        )

    monkeypatch.setattr(requests, "post", fake_post)
    verdicts = VisionRankingProvider(_settings()).rank({}, _photos(1))

    assert len(calls) == 3
    assert "chat_template_kwargs" not in calls[1]
    assert "response_format" not in calls[2]
    assert verdicts[0].subject == "scene"


def test_truncated_reply_without_json_names_the_cause(monkeypatch, caplog):
    """`finish_reason=length` com só raciocínio: o log tem de dizer o porquê."""
    monkeypatch.setattr(requests, "post", lambda *a, **k: _Resp({"choices": [{
        "message": {"content": "The user wants me to evaluate 8 images for a "
                               "TikTok carousel. The criteria are: 1. score"},
        "finish_reason": "length",
    }]}))
    with caplog.at_level("WARNING"):
        assert VisionRankingProvider(_settings()).rank({}, _photos(1)) == []
    assert "finish_reason=length" in caplog.text
    assert "Instruct" in caplog.text


def test_token_budget_grows_with_the_number_of_images(monkeypatch):
    """8 imagens não cabiam nos 900 tokens fixos — a resposta vinha cortada."""
    captured = {}

    def fake_post(url, **kwargs):
        captured.setdefault("max_tokens", []).append(kwargs["json"]["max_tokens"])
        return _reply('{"results":[]}')

    monkeypatch.setattr(requests, "post", fake_post)
    provider = VisionRankingProvider(_settings())
    provider.rank({}, _photos(1))
    provider.rank({}, _photos(8))
    one, eight = captured["max_tokens"]
    assert eight > one
    assert eight >= 8 * 200


def test_unusable_response_is_logged_with_what_came_back(monkeypatch, caplog):
    """"Não devolveu JSON" sem o conteúdo é indiagnosticável em produção."""
    monkeypatch.setattr(requests, "post", lambda *a, **k: _Resp({"choices": [{
        "message": {"content": "Desculpe, não consigo analisar estas imagens."},
        "finish_reason": "stop",
    }]}))
    with caplog.at_level("WARNING"):
        assert VisionRankingProvider(_settings()).rank({}, _photos(1)) == []
    assert "Desculpe, não consigo analisar" in caplog.text
    assert "finish_reason=stop" in caplog.text


def test_clamps_out_of_range_scores(monkeypatch):
    monkeypatch.setattr(requests, "post", lambda *a, **k: _reply(
        '{"results":[{"image_id":"ph0","score":7.5,"anchor":"top"},'
        '{"image_id":"ph1","score":"abc","anchor":"top"}]}'
    ))
    verdicts = VisionRankingProvider(_settings()).rank({}, _photos(2))
    assert [v.score for v in verdicts] == [1.0, 0.0]


def test_unknown_anchor_leaves_position_unset(monkeypatch):
    """Âncora inventada não vira coordenada — o papel do slide decide."""
    monkeypatch.setattr(requests, "post", lambda *a, **k: _reply(
        '{"results":[{"image_id":"ph0","score":0.5,"anchor":"nordeste"}]}'
    ))
    verdicts = VisionRankingProvider(_settings()).rank({}, _photos(1))
    assert verdicts[0].position is None


def test_ignores_hallucinated_and_duplicate_ids(monkeypatch):
    monkeypatch.setattr(requests, "post", lambda *a, **k: _reply(
        '{"results":[{"image_id":"ph0","score":0.9,"anchor":"top"},'
        '{"image_id":"ph0","score":0.1,"anchor":"bottom"},'
        '{"image_id":"nao-existe","score":0.99,"anchor":"top"}]}'
    ))
    verdicts = VisionRankingProvider(_settings()).rank({}, _photos(2))
    assert [(v.image_id, v.score) for v in verdicts] == [("ph0", 0.9)]


# ----------------------------------------------- assunto da foto (casting)
def test_parses_the_subject_of_each_photo(monkeypatch):
    """O casting precisa saber o que tem na foto — o metadado do Unsplash não
    diz de forma confiável."""
    monkeypatch.setattr(requests, "post", lambda *a, **k: _reply(
        '{"results":[{"image_id":"ph0","score":0.8,"anchor":"top","subject":"woman"},'
        '{"image_id":"ph1","score":0.7,"anchor":"top","subject":"scene"}]}'
    ))
    verdicts = VisionRankingProvider(_settings()).rank({}, _photos(2))
    assert [v.subject for v in verdicts] == ["woman", "scene"]


@pytest.mark.parametrize("raw,expected", [
    ("female", "woman"), ("girl", "woman"), ("mulher", "woman"),
    ("male", "man"), ("people", "person"), ("portrait", "person"),
    ("food", "food"), ("smoothie", "food"), ("fruit", "food"),
    ("landscape", "scene"), ("no-person", "scene"),
    ("WOMAN", "woman"), (" woman ", "woman"),
])
def test_accepts_the_synonyms_vlms_actually_return(monkeypatch, raw, expected):
    """Um "female" correto virando "" faria o casting perder o único sinal
    confiável que tinha sobre aquela foto."""
    monkeypatch.setattr(requests, "post", lambda *a, **k: _reply(
        '{"results":[{"image_id":"ph0","score":0.5,"anchor":"top",'
        f'"subject":"{raw}"}}]}}'
    ))
    verdicts = VisionRankingProvider(_settings()).rank({}, _photos(1))
    assert verdicts[0].subject == expected


def test_unknown_subject_is_dropped_not_guessed(monkeypatch):
    """Assunto inventado vira "" e o casting cai no sinal do pool."""
    monkeypatch.setattr(requests, "post", lambda *a, **k: _reply(
        '{"results":[{"image_id":"ph0","score":0.5,"anchor":"top","subject":"alienígena"}]}'
    ))
    verdicts = VisionRankingProvider(_settings()).rank({}, _photos(1))
    assert verdicts[0].subject == ""


def test_missing_subject_does_not_break_the_verdict(monkeypatch):
    """Modelo antigo (ou que ignorou o campo) ainda serve para nota e âncora."""
    monkeypatch.setattr(requests, "post", lambda *a, **k: _reply(
        '{"results":[{"image_id":"ph0","score":0.6,"anchor":"bottom"}]}'
    ))
    verdicts = VisionRankingProvider(_settings()).rank({}, _photos(1))
    assert verdicts[0].subject == ""
    assert verdicts[0].position == (0.5, 0.76)


def test_cap_keeps_both_pools_represented(monkeypatch):
    """Com casting, a lista chega como [retratos] + [cenários]. Um corte cru
    gastaria a cota toda no primeiro pool e o casting classificaria metade das
    fotos no escuro."""
    captured = {}

    def fake_post(url, **kwargs):
        captured["json"] = kwargs["json"]
        return _reply('{"results":[]}')

    monkeypatch.setattr(requests, "post", fake_post)
    hook_photos = _photos(6)
    scene_photos = _photos(6)
    for i, img in enumerate(hook_photos):
        img.image_id, img.pool = f"hook{i}", "hook"
    for i, img in enumerate(scene_photos):
        img.image_id, img.pool = f"scene{i}", "scene"

    VisionRankingProvider(_settings()).rank({}, hook_photos + scene_photos)

    sent = captured["json"]["messages"][1]["content"][0]["text"]
    assert "hook0" in sent and "scene0" in sent


def test_cap_covers_every_requested_quota_before_spending_slack(monkeypatch):
    captured = {}

    def fake_post(url, **kwargs):
        captured["json"] = kwargs["json"]
        return _reply('{"results":[]}')

    monkeypatch.setattr(requests, "post", fake_post)
    hook_photos = _photos(6)
    food_photos = _photos(8)
    scene_photos = _photos(10)
    for i, image in enumerate(hook_photos):
        image.image_id, image.pool = f"hook{i}", "hook"
    for i, image in enumerate(food_photos):
        image.image_id, image.pool = f"food{i}", "food"
    for i, image in enumerate(scene_photos):
        image.image_id, image.pool = f"scene{i}", "scene"

    VisionRankingProvider(_settings()).rank(
        {
            "slides_count": 8,
            "person_images_count": 1,
            "food_images_count": 2,
        },
        hook_photos + food_photos + scene_photos,
    )

    sent = captured["json"]["messages"][1]["content"][0]["text"]
    for image_id in ["hook0", "food0", "food1", *[f"scene{i}" for i in range(5)]]:
        assert image_id in sent
    assert len(captured["json"]["messages"][1]["content"]) == 13


# ------------------------------------------------------------------ fallbacks
@pytest.mark.parametrize("content", ["desculpe, não consigo", "", "{quebrado"])
def test_unusable_answer_falls_back(monkeypatch, content):
    monkeypatch.setattr(requests, "post", lambda *a, **k: _reply(content))
    assert VisionRankingProvider(_settings()).rank({}, _photos(1)) == []


def test_timeout_falls_back(monkeypatch):
    def timeout(*a, **k):
        raise requests.Timeout()

    monkeypatch.setattr(requests, "post", timeout)
    assert VisionRankingProvider(_settings()).rank({}, _photos(1)) == []


def test_vision_uses_its_own_timeout_not_the_http_one(monkeypatch):
    """O VLM olha até 8 fotos por chamada — é a parte lenta do POST /generate.

    Enquanto os dois compartilhavam `REQUEST_TIMEOUT_SECONDS`, o número que
    servia para o Unsplash (20s) cancelava a visão antes da primeira resposta e
    o carrossel caía no ranking textual sem nada estar configurado errado.
    """
    seen = {}

    def capture(*a, **kwargs):
        seen["timeout"] = kwargs.get("timeout")
        return _reply('{"results":[]}')

    monkeypatch.setattr(requests, "post", capture)
    settings = _settings(REQUEST_TIMEOUT_SECONDS="20", VISION_TIMEOUT_SECONDS="90")
    VisionRankingProvider(settings).rank({}, _photos(1))
    assert seen["timeout"] == 90


def test_vision_timeout_defaults_above_the_http_timeout():
    """Sem VISION_TIMEOUT_SECONDS no ambiente, o default não pode ser o antigo.

    O log do Render mostrava "não respondeu em 20s" — que é o DEFAULT do
    timeout HTTP no código, ou seja, a variável do blueprint não chegava à
    aplicação. O default da visão precisa dar folga sozinho.
    """
    settings = Settings.from_env({})
    assert settings.vision_timeout_seconds >= 60
    assert settings.vision_timeout_seconds > settings.request_timeout_seconds


def test_http_error_falls_back(monkeypatch):
    """404 no ModelScope é quase sempre model id sem o prefixo da org."""
    monkeypatch.setattr(requests, "post", lambda *a, **k: _Resp(
        {"error": "model not found"}, status=404
    ))
    assert VisionRankingProvider(_settings()).rank({}, _photos(1)) == []


# -------------------------------------------- posição aplicada nos slides
def test_positions_land_on_slides_by_image_rotation():
    """Slide i usa a imagem i % len — a mesma rotação do renderer e da prévia."""
    slides = [{"headline": f"s{i}"} for i in range(3)]
    images = _photos(2)
    verdicts = [
        VisionVerdict(image_id="ph0", score=0.9, anchor="top"),
        VisionVerdict(image_id="ph1", score=0.8, anchor="bottom"),
    ]
    GenerationService._apply_vision_positions(slides, images, verdicts)

    assert (slides[0]["pos_x"], slides[0]["pos_y"]) == (0.5, 0.22)
    assert (slides[1]["pos_x"], slides[1]["pos_y"]) == (0.5, 0.76)
    assert (slides[2]["pos_x"], slides[2]["pos_y"]) == (0.5, 0.22)


def test_unjudged_image_keeps_role_anchor():
    """Sem veredicto utilizável, o slide não ganha pos_* e o papel decide."""
    slides = [{"headline": "s0"}]
    GenerationService._apply_vision_positions(
        slides, _photos(1), [VisionVerdict(image_id="ph0", score=0.5, anchor="")]
    )
    assert "pos_y" not in slides[0]


def test_position_follows_the_image_the_casting_chose():
    """Depois do casting o slide tem image_id próprio — a posição tem que vir
    da foto que está de fato no slide, não da rotação."""
    slides = [
        {"headline": "s0", "image_id": "ph1"},
        {"headline": "s1", "image_id": "ph0"},
    ]
    verdicts = [
        VisionVerdict(image_id="ph0", score=0.9, anchor="top"),
        VisionVerdict(image_id="ph1", score=0.8, anchor="bottom"),
    ]
    GenerationService._apply_vision_positions(slides, _photos(2), verdicts)

    assert (slides[0]["pos_x"], slides[0]["pos_y"]) == (0.5, 0.76)
    assert (slides[1]["pos_x"], slides[1]["pos_y"]) == (0.5, 0.22)
