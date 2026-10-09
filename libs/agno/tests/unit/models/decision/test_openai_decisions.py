import json
from typing import Any, Dict, List

import httpx
import pytest

pytest.importorskip("openai.resources.decisions", reason="requires openai>=3.26.0, the first release with Decisions")

from agno.exceptions import ModelAuthenticationError, ModelRateLimitError
from agno.models.decision import Choice, Noul, NoulAnswer, Predicate, PredicateAnswer, RefusalAnswer, Score
from agno.models.openai import OpenAIDecisions

QUESTIONS = {
    "damaged": Noul(instructions="Is the product damaged", yes="Crack, tear or dent", no="Looks intact"),
    "department": Choice(instructions="Who handles it", options={"billing": "Refunds", "technical": None}),
    "severity": Score(instructions="How severe", levels={"Cosmetic": "Looks only", "Blocking": None}),
}

RESPONSE = {
    "model": "gpt-6-luna-2026-09-29",
    "answers": [
        {"type": "predicate", "name": "damaged", "probability": 0.92},
        {
            "type": "choice",
            "name": "department",
            "choice": "billing",
            "probabilities": [{"value": "billing", "probability": 0.95}, {"value": "technical", "probability": 0.05}],
            "confidence": 0.93,
        },
        {
            "type": "score",
            "name": "severity",
            "score": 0.4,
            "probabilities": [
                {"label": "Cosmetic", "value": 0, "probability": 0.6},
                {"label": "Blocking", "value": 1, "probability": 0.4},
            ],
            "confidence": 0.5,
        },
    ],
    "usage": {
        "input_tokens": 100,
        "input_tokens_details": {"cache_write_tokens": 0, "cached_tokens": 40},
        "output_tokens": 3,
        "output_tokens_details": {"reasoning_tokens": 2},
        "total_tokens": 103,
    },
}


def make_model(responses: List[httpx.Response], async_client: bool = False, **kwargs):
    requests: List[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return responses[min(len(requests), len(responses)) - 1]

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport) if async_client else httpx.Client(transport=transport)
    return OpenAIDecisions(api_key="sk-test", http_client=client, max_retries=0, **kwargs), requests


def body(requests: List[httpx.Request]) -> Dict[str, Any]:
    return json.loads(requests[-1].content)


def test_request_translates_to_openai_format():
    model, requests = make_model([httpx.Response(200, json=RESPONSE)])
    model.decide({"order": 42}, QUESTIONS)

    assert requests[0].url.path == "/v1/decisions"
    assert body(requests) == {
        "model": "gpt-6-luna",
        "input": '{\n  "order": 42\n}',
        "questions": [
            {
                "type": "predicate",
                "name": "damaged",
                "instructions": "Is the product damaged\nYes means: Crack, tear or dent\nNo means: Looks intact",
            },
            {
                "type": "choice",
                "name": "department",
                "instructions": "Who handles it",
                "choices": [{"value": "billing", "description": "Refunds"}, {"value": "technical"}],
            },
            {
                "type": "score",
                "name": "severity",
                "instructions": "How severe",
                "levels": [{"label": "Cosmetic", "description": "Looks only"}, {"label": "Blocking"}],
            },
        ],
    }


def test_list_state_becomes_user_message():
    model, requests = make_model([httpx.Response(200, json=RESPONSE)])
    model.decide(["first", "second"], QUESTIONS)
    assert body(requests)["input"] == [
        {
            "role": "user",
            "content": [{"type": "input_text", "text": "first"}, {"type": "input_text", "text": "second"}],
        }
    ]


def test_response_translates_back():
    model, _ = make_model([httpx.Response(200, json=RESPONSE)])
    result = model.decide("x", QUESTIONS)

    assert (result["damaged"].probability, result["damaged"].value) == (0.92, True)
    assert result["department"].value == "billing"
    assert result["department"].probabilities == {"billing": 0.95, "technical": 0.05}
    assert (result["severity"].level, result["severity"].label, result["severity"].value) == (0, "Cosmetic", 0.4)
    assert result["severity"].probabilities == {"Cosmetic": 0.6, "Blocking": 0.4}
    assert result.metrics is not None
    assert (result.metrics.input_tokens, result.metrics.total_tokens, result.metrics.cache_read_tokens) == (
        100,
        103,
        40,
    )
    assert result.metrics.reasoning_tokens == 2


def test_refusal():
    refused = dict(RESPONSE, answers=[*RESPONSE["answers"][1:], {"type": "refusal", "name": "damaged"}])
    model, _ = make_model([httpx.Response(200, json=refused)])
    assert isinstance(model.decide("x", QUESTIONS)["damaged"], RefusalAnswer)


def test_auth_error():
    model, _ = make_model([httpx.Response(401, json={"error": {"message": "Incorrect API key"}})])
    with pytest.raises(ModelAuthenticationError, match="Incorrect API key"):
        model.decide("x", QUESTIONS)


def test_rate_limit_is_retried_by_agno():
    model, requests = make_model(
        [httpx.Response(429, json={"error": {"message": "Rate limit"}})], retries=1, delay_between_retries=0
    )
    with pytest.raises(ModelRateLimitError, match="Rate limit"):
        model.decide("x", QUESTIONS)
    assert len(requests) == 2


async def test_adecide():
    model, requests = make_model([httpx.Response(200, json=RESPONSE)], async_client=True)
    result = await model.adecide("x", QUESTIONS)
    assert result["department"].value == "billing"
    assert body(requests)["questions"][0]["type"] == "predicate"


def test_noul_and_predicate_both_map_to_predicate():
    model, requests = make_model([httpx.Response(200, json=RESPONSE), httpx.Response(200, json=RESPONSE)])
    noul_result = model.decide("x", QUESTIONS)
    predicate_questions = dict(QUESTIONS, damaged=Predicate(instructions="Is the product damaged"))
    predicate_result = model.decide("x", predicate_questions)
    assert body(requests)["questions"][0] == {
        "type": "predicate",
        "name": "damaged",
        "instructions": "Is the product damaged",
    }
    assert noul_result["damaged"] == NoulAnswer(probability=0.92, value=True)
    assert predicate_result["damaged"] == PredicateAnswer(probability=0.92, value=True)
