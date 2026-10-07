import json
import os
from copy import deepcopy
from typing import Any, Callable, Dict, List
from unittest.mock import patch

import httpx
import pytest
from pydantic import ValidationError

from agno.exceptions import ModelAuthenticationError, ModelProviderError, ModelRateLimitError
from agno.models.decision import (
    Choice,
    ChoiceAnswer,
    DecisionModel,
    Noul,
    NoulAnswer,
    RefusalAnswer,
    Score,
    ScoreAnswer,
)
from agno.models.perplexity import PerplexityDecisions
from agno.models.typesafe import Jev

TRIAGE_QUESTIONS = {
    "urgent": Noul(instructions="Customer is losing money", yes="Money or a deadline today", no="Can wait"),
    "area": Choice(instructions="Which team owns this", options={"billing": "Payments", "technical": None}),
    "severity": Score(instructions="How bad", levels={"Cosmetic": "Looks only", "Degraded": None, "Outage": "Down"}),
}

TRIAGE_RESPONSE = {
    "model": "jev-1.13.0",
    "answers": {
        "urgent": {"type": "noul", "noul": 0.93},
        "area": {
            "type": "choice",
            "choice": "technical",
            "probabilities": {"billing": 0.1, "technical": 0.9},
            "confidence": 0.8,
        },
        "severity": {
            "type": "score",
            "score": 1.43,
            "legend": {"0": "Cosmetic: Looks only", "1": "Degraded", "2": "Outage: Down"},
            "probabilities": {"0": 0.0, "1": 0.57, "2": 0.43},
            "confidence": 0.35,
        },
    },
    "usage": {"input_tokens": 210, "output_tokens": 31},
}


class Recorder:
    def __init__(self, responses: List[httpx.Response]):
        self.responses = responses
        self.requests: List[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.responses[min(len(self.requests), len(self.responses)) - 1]

    @property
    def body(self) -> Dict[str, Any]:
        return json.loads(self.requests[-1].content)


def make_model(
    responses: List[httpx.Response], async_client: bool = False, factory: Callable[..., DecisionModel] = Jev, **kwargs
):
    recorder = Recorder(responses)
    transport = httpx.MockTransport(recorder)
    client = httpx.AsyncClient(transport=transport) if async_client else httpx.Client(transport=transport)
    model = factory(api_key="test-key", http_client=client, **kwargs)
    return model, recorder


def ok(body: Dict[str, Any] = TRIAGE_RESPONSE) -> httpx.Response:
    return httpx.Response(200, json=body)


# ---------------------------------------------------------------------------
# Request encoding
# ---------------------------------------------------------------------------


def test_request_encodes_each_question_type():
    model, recorder = make_model([ok()])
    model.decide("Checkout is down", TRIAGE_QUESTIONS)

    request = recorder.requests[0]
    assert str(request.url) == "https://api.typesafe.ai/v1/systemone"
    assert request.headers["Authorization"] == "Bearer test-key"
    assert recorder.body == {
        "model": "jev-latest",
        "state": "Checkout is down",
        "questions": {
            "urgent": {
                "type": "noul",
                "instructions": "Customer is losing money",
                "criteria": {"true": "Money or a deadline today", "false": "Can wait"},
            },
            "area": {
                "type": "choice",
                "instructions": "Which team owns this",
                "criteria": {"billing": "Payments", "technical": None},
            },
            "severity": {
                "type": "score",
                "instructions": "How bad",
                "criteria": ["Cosmetic: Looks only", "Degraded", "Outage: Down"],
            },
        },
    }


def test_noul_without_criteria_omits_criteria():
    model, recorder = make_model([ok({"answers": {"q": {"type": "noul", "noul": 0.2}}})])
    model.decide({"ticket": "hi"}, {"q": Noul(instructions="Is it spam")})
    assert recorder.body["state"] == {"ticket": "hi"}
    assert recorder.body["questions"]["q"] == {"type": "noul", "instructions": "Is it spam"}


def test_choice_options_accept_a_list():
    choice = Choice(instructions="Pick", options=["a", "b"])
    assert choice.options == {"a": None, "b": None}


def test_questions_accept_plain_dicts():
    model, recorder = make_model([ok({"answers": {"q": {"type": "noul", "noul": 0.7}}})])
    result = model.decide("x", {"q": {"type": "noul", "instructions": "Is it spam"}})
    assert result["q"].value is True


# ---------------------------------------------------------------------------
# Response decoding
# ---------------------------------------------------------------------------


def test_response_decodes_each_answer_type():
    model, _ = make_model([ok()])
    result = model.decide("Checkout is down", TRIAGE_QUESTIONS)

    assert result["urgent"] == NoulAnswer(probability=0.93, value=True)
    assert result["area"] == ChoiceAnswer(
        value="technical", probabilities={"billing": 0.1, "technical": 0.9}, confidence=0.8
    )
    assert result["severity"] == ScoreAnswer(
        value=1.43,
        level=1,
        label="Degraded",
        probabilities={"Cosmetic": 0.0, "Degraded": 0.57, "Outage": 0.43},
        confidence=0.35,
    )
    assert result.model == "jev-1.13.0"
    assert result.metrics is not None
    assert (result.metrics.input_tokens, result.metrics.output_tokens, result.metrics.total_tokens) == (210, 31, 241)
    assert result.metrics.duration is not None
    assert set(result) == {"urgent", "area", "severity"}


def test_noul_threshold_sets_value():
    response = ok({"answers": {"q": {"type": "noul", "noul": 0.7}}})
    model, _ = make_model([response, response])
    assert model.decide("x", {"q": Noul(instructions="i")})["q"].value is True
    assert model.decide("x", {"q": Noul(instructions="i", threshold=0.8)})["q"].value is False


def test_refusal_answer():
    model, _ = make_model([ok({"answers": {"q": {"type": "refusal"}}})])
    assert isinstance(model.decide("x", {"q": Noul(instructions="i")})["q"], RefusalAnswer)


def test_missing_answer_raises():
    model, _ = make_model([ok({"answers": {}})])
    with pytest.raises(ModelProviderError, match="no answer for question 'q'"):
        model.decide("x", {"q": Noul(instructions="i")})


def test_malformed_answer_raises():
    model, _ = make_model([ok({"answers": {"q": {"type": "noul"}}})])
    with pytest.raises(ModelProviderError, match="Malformed answer"):
        model.decide("x", {"q": Noul(instructions="i")})


# ---------------------------------------------------------------------------
# Errors and retries
# ---------------------------------------------------------------------------


def test_auth_error_is_not_retried():
    model, recorder = make_model([httpx.Response(401, json={"error": {"message": "bad key"}})], retries=2)
    with pytest.raises(ModelAuthenticationError, match="bad key"):
        model.decide("x", {"q": Noul(instructions="i")})
    assert len(recorder.requests) == 1


def test_server_error_is_retried():
    model, recorder = make_model(
        [httpx.Response(500, text="boom"), ok({"answers": {"q": {"type": "noul", "noul": 0.9}}})],
        retries=1,
        delay_between_retries=0,
    )
    assert model.decide("x", {"q": Noul(instructions="i")})["q"].probability == 0.9
    assert len(recorder.requests) == 2


def test_rate_limit_raises_rate_limit_error_after_retries():
    model, recorder = make_model([httpx.Response(429, json={"error": "slow down"})], retries=1, delay_between_retries=0)
    with pytest.raises(ModelRateLimitError, match="slow down"):
        model.decide("x", {"q": Noul(instructions="i")})
    assert len(recorder.requests) == 2


def test_bad_request_is_not_retried():
    model, recorder = make_model([httpx.Response(400, json={"error": "too many questions"})], retries=2)
    with pytest.raises(ModelProviderError, match="too many questions"):
        model.decide("x", {"q": Noul(instructions="i")})
    assert len(recorder.requests) == 1


def test_connection_error_is_a_provider_error():
    def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    model = Jev(api_key="k", http_client=httpx.Client(transport=httpx.MockTransport(fail)))
    with pytest.raises(ModelProviderError, match="refused"):
        model.decide("x", {"q": Noul(instructions="i")})


# ---------------------------------------------------------------------------
# Async
# ---------------------------------------------------------------------------


async def test_adecide_matches_decide():
    model, recorder = make_model([ok()], async_client=True)
    result = await model.adecide("Checkout is down", TRIAGE_QUESTIONS)
    assert result["severity"].label == "Degraded"
    assert recorder.body["questions"]["area"]["criteria"] == {"billing": "Payments", "technical": None}


async def test_adecide_retries():
    model, recorder = make_model(
        [httpx.Response(503), ok({"answers": {"q": {"type": "noul", "noul": 0.1}}})],
        async_client=True,
        retries=1,
        delay_between_retries=0,
    )
    assert (await model.adecide("x", {"q": Noul(instructions="i")}))["q"].value is False
    assert len(recorder.requests) == 2


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def test_provider_defaults():
    jev = Jev(api_key="k")
    assert (jev.id, jev.name, jev.provider, jev._url()) == (
        "jev-latest",
        "Jev",
        "TypeSafe",
        "https://api.typesafe.ai/v1/systemone",
    )
    perplexity = PerplexityDecisions(api_key="k")
    assert (perplexity.id, perplexity.provider, perplexity._url()) == (
        "pplx-decider-v1.1-27b",
        "Perplexity",
        "https://api.perplexity.ai/v1/decisions",
    )
    assert jev.to_dict() == {"name": "Jev", "id": "jev-latest", "provider": "TypeSafe"}


def test_self_hosted_needs_no_key():
    model, recorder = make_model(
        [ok({"answers": {"q": {"type": "noul", "noul": 0.5}}})],
        factory=DecisionModel,
        id="pplx-decider-v1-27b",
        base_url="http://localhost:30000/",
    )
    model.api_key = None
    model.decide("x", {"q": Noul(instructions="i")})
    assert str(recorder.requests[0].url) == "http://localhost:30000/v1/systemone"
    assert "Authorization" not in recorder.requests[0].headers
    assert model.provider == "DecisionModel (pplx-decider-v1-27b)"


def test_missing_base_url_raises():
    with pytest.raises(ValueError, match="base_url"):
        DecisionModel(id="m").decide("x", {"q": Noul(instructions="i")})


def test_api_key_from_env():
    with patch.dict(os.environ, {"TYPESAFE_API_KEY": "env-key"}):
        assert Jev()._headers()["Authorization"] == "Bearer env-key"


def test_missing_api_key_raises():
    with patch.dict(os.environ, {}, clear=True):
        with pytest.raises(ModelAuthenticationError, match="TYPESAFE_API_KEY"):
            Jev()._headers()


def test_client_is_cached_and_rebuilt_after_close():
    model = Jev(api_key="k")
    client = model.get_client()
    assert model.get_client() is client
    client.close()
    assert model.get_client() is not client


def test_deepcopy_drops_cached_clients():
    model = Jev(api_key="k")
    model.get_client()
    copied = deepcopy(model)
    assert copied.client is None
    assert copied.api_key == "k"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "build",
    [
        lambda: Choice(instructions="i", options=["only"]),
        lambda: Choice(instructions="i", options=["a", "a"]),
        lambda: Score(instructions="i", levels=["one"]),
        lambda: Score(instructions="i", levels=[str(n) for n in range(11)]),
        lambda: Noul(instructions="i", threshold=1.0),
        lambda: Noul(instructions="i", yes="only yes"),
    ],
)
def test_invalid_questions_raise(build):
    with pytest.raises(ValidationError):
        build()


def test_decide_rejects_empty_questions_and_bad_state():
    model = Jev(api_key="k")
    with pytest.raises(ValueError, match="at least one question"):
        model.decide("x", {})
    with pytest.raises(TypeError, match="state must be"):
        model.decide(42, {"q": Noul(instructions="i")})  # type: ignore[arg-type]
