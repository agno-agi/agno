"""Reject malformed run inputs before dispatch, including streaming/background requests."""

import json
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from agno.agents.claude import ClaudeAgent
from agno.agents.codex import CodexAgent
from agno.os import AgentOS
from agno.os.utils import get_request_kwargs


@pytest.fixture(params=[ClaudeAgent, CodexAgent])
def harness_client(request, monkeypatch):
    agent = request.param(id="test-inputs")
    run = AsyncMock(side_effect=AssertionError("Invalid input reached the harness"))
    monkeypatch.setattr(agent, "arun", run)
    app = AgentOS(agents=[agent]).get_app()
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, run


@pytest.mark.parametrize("mode", [{"stream": "false"}, {"stream": "true"}, {"background": "true"}])
@pytest.mark.parametrize("field", ["images", "audio", "videos", "input_files"])
@pytest.mark.parametrize("value", ["not json", "123", "[1,2]", "null", "{}", ""])
def test_invalid_media_rejected_before_dispatch(harness_client, mode, field, value):
    client, run = harness_client
    response = client.post("/agents/test-inputs/runs", data={"message": "hi", field: value, **mode})
    assert response.status_code == 422, response.text
    assert field in response.json()["detail"]
    run.assert_not_called()


@pytest.mark.parametrize(
    "value",
    [
        "{not json",
        "123",
        "null",
        "[]",
        '{"type":"string"}',
        "",
        '{"type":"object","properties":{"answer":"bad"}}',
        '{"type":"object","properties":{"answer":{"type":"bogus"}}}',
        '{"type":"object","required":"answer"}',
        '{"allOf":[{"type":"string"}]}',
        '{"properties":{"answer":{"type":"string"}}}',
    ],
)
@pytest.mark.parametrize("raw_schema", ["true", "false"])
def test_invalid_schema_rejected_before_dispatch(harness_client, value, raw_schema):
    client, run = harness_client
    response = client.post(
        "/agents/test-inputs/runs",
        data={"message": "hi", "stream": "false", "output_schema": value, "use_json_schema": raw_schema},
    )
    assert response.status_code == 422, response.text
    assert "output_schema" in response.json()["detail"]
    run.assert_not_called()


@pytest.fixture
def parser_client():
    app = FastAPI()

    @app.post("/parse")
    async def parse(request: Request):
        kwargs = await get_request_kwargs(request, parse)
        schema = kwargs.pop("output_schema", None)
        return {
            "media": {key: [item.to_dict() for item in value] for key, value in kwargs.items()},
            "schema": schema if isinstance(schema, dict) else schema.model_json_schema() if schema else None,
        }

    return TestClient(app)


@pytest.mark.parametrize("field", ["images", "audio", "videos", "input_files"])
def test_empty_media_array_is_valid(parser_client, field):
    response = parser_client.post("/parse", data={field: "[]"})
    assert response.status_code == 200
    assert response.json()["media"]["files" if field == "input_files" else field] == []


def test_valid_media_retains_bytes_but_drops_untrusted_storage_reference(parser_client):
    from agno.media import Image

    image = Image(content=b"image bytes", mime_type="image/png").to_dict()
    image["media_reference"] = {"storage_key": "another-users-file"}
    response = parser_client.post("/parse", data={"images": json.dumps([image])})
    assert response.status_code == 200
    reconstructed = response.json()["media"]["images"][0]
    assert reconstructed["content"] == image["content"]
    assert not reconstructed.get("media_reference")


@pytest.mark.parametrize("raw_schema", ["true", "false"])
def test_valid_object_schema_preserves_required_field(parser_client, raw_schema):
    schema = {"type": "object", "properties": {"answer": {"type": "integer"}}, "required": ["answer"]}
    response = parser_client.post("/parse", data={"output_schema": json.dumps(schema), "use_json_schema": raw_schema})
    assert response.status_code == 200
    assert response.json()["schema"]["properties"]["answer"]["type"] == "integer"
    assert response.json()["schema"]["required"] == ["answer"]


def test_bad_media_item_does_not_silently_disappear(parser_client):
    response = parser_client.post("/parse", data={"images": '[{"url":123}]'})
    assert response.status_code == 422
    assert "reconstruct" in response.json()["detail"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("images", "[" * 20_000 + "]" * 20_000),
        ("output_schema", '{"a":' * 20_000 + "1" + "}" * 20_000),
    ],
    ids=["media-json", "schema-json"],
)
def test_deeply_nested_input_is_rejected_not_crashed(parser_client, field, value):
    response = parser_client.post("/parse", data={field: value})
    assert response.status_code == 422, response.text
    assert field in response.json()["detail"]


@pytest.mark.parametrize(
    "value",
    [
        '{"type":"object","properties":{"x":' + '{"items":' * 5_000 + "{}" + "}" * 5_000 + "}}",
        '{"type":"object","allOf":[' * 100 + '{"type":"object"}' + "]}" * 100,
    ],
    ids=["items", "allof"],
)
def test_deeply_nested_valid_schema_does_not_crash(parser_client, value):
    # Whether validation recurses past the stack limit depends on the jsonschema version; either outcome is controlled
    response = parser_client.post("/parse", data={"output_schema": value})
    assert response.status_code in (200, 422), response.text
    if response.status_code == 422:
        assert "output_schema" in response.json()["detail"]


RAW_JSON_SCHEMA = {
    "type": "json_schema",
    "json_schema": {"name": "Person", "schema": {"type": "object", "properties": {"name": {"type": "string"}}}},
}


@pytest.mark.parametrize("schema", [{"type": "json_object"}, RAW_JSON_SCHEMA], ids=["json_object", "json_schema"])
def test_raw_response_formats_pass_through(parser_client, schema):
    response = parser_client.post("/parse", data={"output_schema": json.dumps(schema), "use_json_schema": "true"})
    assert response.status_code == 200, response.text
    assert response.json()["schema"] == schema


@pytest.mark.parametrize(
    "schema,raw_schema",
    [
        ({"type": "json_object"}, "false"),
        (RAW_JSON_SCHEMA, "false"),
        ({"type": "json_schema"}, "true"),
        ({"type": "json_schema", "json_schema": {"name": "P", "schema": {"type": "string"}}}, "true"),
        ({"type": "json_schema", "json_schema": {"name": "P", "schema": {"allOf": [{"type": "string"}]}}}, "true"),
        (
            {
                "type": "json_schema",
                "json_schema": {"name": "P", "schema": {"type": "object", "properties": {"a": "bad"}}},
            },
            "true",
        ),
    ],
    ids=["json_object-model", "json_schema-model", "missing-inner", "scalar-inner", "untyped-inner", "malformed-inner"],
)
def test_invalid_raw_response_formats_rejected(parser_client, schema, raw_schema):
    response = parser_client.post("/parse", data={"output_schema": json.dumps(schema), "use_json_schema": raw_schema})
    assert response.status_code == 422, response.text
    assert "output_schema" in response.json()["detail"]
