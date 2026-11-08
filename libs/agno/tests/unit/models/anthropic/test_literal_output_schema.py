"""Singleton Literal constraints must survive Claude's native output schema conversion."""

import json
from importlib import import_module
from typing import Any, Dict, List, Literal, Optional, Union

import anthropic
import pytest
from pydantic import BaseModel, Field, RootModel

from agno.agent import Agent
from agno.models.anthropic.claude import Claude
from agno.utils.models.claude import sdk_http_client_type


class Invoice(BaseModel):
    kind: Literal["invoice"]
    count: Literal[3]


@pytest.fixture(params=[False, True], ids=["sdk", "fallback"])
def model(request, monkeypatch):
    if request.param:
        # Actually exercise the ImportError branch, rather than calling the SDK again.
        monkeypatch.delattr(anthropic, "transform_schema")
    return Claude(id="claude-sonnet-4-5")


def test_singleton_literals_keep_their_types_and_values(model):
    class Values(Invoice):
        enabled: Literal[True]
        empty: Literal[None]
        choice: Literal["a", "b"]

    original = Values.model_json_schema()
    properties = model._build_output_format(Values)["schema"]["properties"]
    for name, expected_type, expected_values in [
        ("kind", "string", ["invoice"]),
        ("count", "integer", [3]),
        ("enabled", "boolean", [True]),
        ("empty", "null", [None]),
        ("choice", "string", ["a", "b"]),
    ]:
        assert properties[name]["type"] == expected_type
        assert properties[name]["enum"] == expected_values
        assert "const" not in properties[name]
    assert Values.model_json_schema() == original


def test_literals_in_definitions_arrays_and_unions(model):
    class Envelope(BaseModel):
        invoices: List[Invoice]
        status: Optional[Literal["pending"]]
        code: Union[Literal[7], Literal["unknown"]]

    schema = model._build_output_format(Envelope)["schema"]
    assert schema["$defs"]["Invoice"]["properties"]["kind"]["enum"] == ["invoice"]
    assert schema["$defs"]["Invoice"]["properties"]["count"]["enum"] == [3]
    assert schema["properties"]["invoices"]["items"]["$ref"] == "#/$defs/Invoice"
    assert schema["properties"]["status"]["anyOf"] == [
        {"type": "string", "enum": ["pending"]},
        {"type": "null"},
    ]
    assert schema["properties"]["code"]["anyOf"] == [
        {"type": "integer", "enum": [7]},
        {"type": "string", "enum": ["unknown"]},
    ]


def test_root_literal(model):
    schema = model._build_output_format(RootModel[Literal["fixed"]])["schema"]
    assert schema["type"] == "string"
    assert schema["enum"] == ["fixed"]
    assert "const" not in schema


def test_const_is_also_a_valid_property_name(model):
    class NamedConst(BaseModel):
        const: Literal["value"]

    properties = model._build_output_format(NamedConst)["schema"]["properties"]
    assert set(properties) == {"const"}
    assert properties["const"]["enum"] == ["value"]
    assert properties["const"]["type"] == "string"


def test_defaults_and_examples_are_data(monkeypatch):
    # The SDK moves these annotations into descriptions. Capture its input to
    # verify the normalization itself does not rewrite user-provided JSON data.
    monkeypatch.setattr(anthropic, "transform_schema", lambda schema: schema)
    example = {"const": "data", "nested": {"const": 3}}

    class AnnotatedInvoice(Invoice):
        payload: Dict[str, Any] = Field(default=example, examples=[example])

    schema = Claude()._build_output_format(AnnotatedInvoice)["schema"]
    assert schema["properties"]["kind"]["enum"] == ["invoice"]
    assert schema["properties"]["payload"]["default"] == example
    assert schema["properties"]["payload"]["examples"] == [example]


def test_dict_output_format_is_unchanged(model):
    output_format = {"type": "json_schema", "schema": Invoice.model_json_schema()}
    assert model._build_output_format(output_format) is output_format


@pytest.mark.parametrize("is_async", [False, True], ids=["sync", "async"])
async def test_agent_sends_literal_constraints_through_the_sdk(is_async):
    # Anthropic SDK releases use either httpx or httpx2; use their own transport.
    http = import_module(sdk_http_client_type().__module__.split(".")[0])
    captured = []

    def handle(request):
        payload = json.loads(request.content)
        captured.append(payload["output_config"]["format"]["schema"])
        return http.Response(
            200,
            json={
                "id": "msg_offline",
                "type": "message",
                "role": "assistant",
                "model": payload["model"],
                "content": [{"type": "text", "text": '{"kind":"invoice","count":3}'}],
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "usage": {"input_tokens": 10, "output_tokens": 8},
            },
        )

    if is_async:
        async with anthropic.AsyncAnthropic(
            api_key="offline-test-key", http_client=http.AsyncClient(transport=http.MockTransport(handle))
        ) as client:
            agent = Agent(model=Claude(async_client=client), output_schema=Invoice, telemetry=False)
            result = await agent.arun("Return an invoice.")
    else:
        with anthropic.Anthropic(
            api_key="offline-test-key", http_client=http.Client(transport=http.MockTransport(handle))
        ) as client:
            agent = Agent(model=Claude(client=client), output_schema=Invoice, telemetry=False)
            result = agent.run("Return an invoice.")

    assert result.content == Invoice(kind="invoice", count=3)
    assert len(captured) == 1
    properties = captured[0]["properties"]
    assert properties["kind"]["type"] == "string"
    assert properties["kind"]["enum"] == ["invoice"]
    assert properties["count"]["type"] == "integer"
    assert properties["count"]["enum"] == [3]
