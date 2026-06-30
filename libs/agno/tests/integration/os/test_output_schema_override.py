"""
Integration tests for AgentOS dynamic output_schema.

Tests passing output_schema as JSON schema string via AgentOS API endpoints.
"""

import json

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.team import Team


@pytest.fixture(autouse=True)
def reset_async_client():
    """Reset global async HTTP client between tests to avoid event loop conflicts."""
    import agno.utils.http as http_utils

    # Reset before test
    http_utils._global_async_client = None
    yield
    # Reset after test
    http_utils._global_async_client = None


class MovieScript(BaseModel):
    title: str = Field(..., description="Movie title")
    genre: str = Field(..., description="Movie genre")


def test_agent_with_output_schema(test_os_client: TestClient, test_agent: Agent):
    """Test agent run with simple output schema passed as JSON string."""
    schema = {
        "title": "MovieScript",
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "genre": {"type": "string"},
        },
        "required": ["title", "genre"],
    }

    response = test_os_client.post(
        f"/agents/{test_agent.id}/runs",
        data={
            "message": "Write a movie about AI",
            "output_schema": json.dumps(schema),
            "stream": "false",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    assert response.status_code == 200
    data = response.json()
    assert "content" in data
    assert isinstance(data["content"], dict)
    assert "title" in data["content"]
    assert "genre" in data["content"]
    assert isinstance(data["content"]["title"], str)
    assert isinstance(data["content"]["genre"], str)
    assert data["content_type"] == "MovieScript"


def test_agent_with_nested_schema(test_os_client: TestClient, test_agent: Agent):
    """Test agent run with nested object in output schema."""
    schema = {
        "title": "Product",
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "price": {"type": "number"},
            "in_stock": {"type": "boolean"},
            "supplier": {
                "type": "object",
                "title": "Supplier",
                "properties": {
                    "name": {"type": "string"},
                    "country": {"type": "string"},
                },
                "required": ["name", "country"],
            },
        },
        "required": ["name", "price", "in_stock", "supplier"],
    }

    response = test_os_client.post(
        f"/agents/{test_agent.id}/runs",
        data={
            "message": "Create a product: laptop from a tech supplier in USA",
            "output_schema": json.dumps(schema),
            "stream": "false",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    assert response.status_code == 200
    data = response.json()
    assert "content" in data
    assert isinstance(data["content"], dict)
    assert "supplier" in data["content"]
    assert isinstance(data["content"]["supplier"], dict)
    assert "name" in data["content"]["supplier"]
    assert "country" in data["content"]["supplier"]


def test_agent_with_array_schema(test_os_client: TestClient, test_agent: Agent):
    """Test agent run with array fields in output schema."""
    schema = {
        "title": "Recipe",
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "ingredients": {
                "type": "array",
                "items": {"type": "string"},
            },
            "prep_time": {"type": "integer"},
        },
        "required": ["name", "ingredients"],
    }

    response = test_os_client.post(
        f"/agents/{test_agent.id}/runs",
        data={
            "message": "Give me a simple pasta recipe",
            "output_schema": json.dumps(schema),
            "stream": "false",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    assert response.status_code == 200
    data = response.json()
    assert "content" in data
    assert isinstance(data["content"], dict)
    assert "ingredients" in data["content"]
    assert isinstance(data["content"]["ingredients"], list)
    assert len(data["content"]["ingredients"]) > 0


def test_agent_with_optional_fields(test_os_client: TestClient, test_agent: Agent):
    """Test agent run with optional fields in output schema."""
    schema = {
        "title": "Config",
        "type": "object",
        "properties": {
            "host": {"type": "string"},
            "port": {"type": "integer"},
            "username": {"type": "string"},
            "password": {"type": "string"},
        },
        "required": ["host", "port"],
    }

    response = test_os_client.post(
        f"/agents/{test_agent.id}/runs",
        data={
            "message": "Create a server config for localhost:8080",
            "output_schema": json.dumps(schema),
            "stream": "false",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    assert response.status_code == 200
    data = response.json()
    assert "content" in data
    assert isinstance(data["content"], dict)
    assert "host" in data["content"]
    assert "port" in data["content"]


def test_agent_streaming_with_schema(test_os_client: TestClient, test_agent: Agent):
    """Test agent streaming run with output schema."""
    schema = {
        "title": "Answer",
        "type": "object",
        "properties": {
            "answer": {"type": "string"},
            "confidence": {"type": "number"},
        },
        "required": ["answer"],
    }

    response = test_os_client.post(
        f"/agents/{test_agent.id}/runs",
        data={
            "message": "What is 2+2?",
            "output_schema": json.dumps(schema),
            "stream": "true",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    assert response.status_code == 200
    assert "text/event-stream" in response.headers.get("content-type", "")


def test_agent_with_invalid_schema(test_os_client: TestClient, test_agent: Agent):
    """Test agent run handles invalid output schema gracefully."""
    response = test_os_client.post(
        f"/agents/{test_agent.id}/runs",
        data={
            "message": "Write a story",
            "output_schema": "not valid json{",
            "stream": "false",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    assert response.status_code == 200
    data = response.json()
    assert "content" in data
    assert isinstance(data["content"], str)


def test_agent_with_array_of_objects(test_os_client: TestClient, test_agent: Agent):
    """Test agent run with array of objects in output schema."""
    schema = {
        "title": "MovieCast",
        "type": "object",
        "properties": {
            "movie": {"type": "string"},
            "actors": {
                "type": "array",
                "items": {
                    "type": "object",
                    "title": "Actor",
                    "properties": {
                        "name": {"type": "string"},
                        "role": {"type": "string"},
                    },
                    "required": ["name", "role"],
                },
            },
        },
        "required": ["movie", "actors"],
    }

    response = test_os_client.post(
        f"/agents/{test_agent.id}/runs",
        data={
            "message": "Create a cast for a space movie with 2 actors",
            "output_schema": json.dumps(schema),
            "stream": "false",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    assert response.status_code == 200
    data = response.json()
    assert "content" in data
    assert isinstance(data["content"], dict)
    assert "actors" in data["content"]
    assert isinstance(data["content"]["actors"], list)
    if len(data["content"]["actors"]) > 0:
        assert "name" in data["content"]["actors"][0]
        assert "role" in data["content"]["actors"][0]


def test_agent_preconfigured_vs_dynamic_schema(test_os_client: TestClient, test_agent: Agent):
    """Compare agent with pre-configured schema vs dynamic schema passed via API."""
    agent_with_schema = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        output_schema=MovieScript,
        telemetry=False,
        markdown=False,
    )
    agent_os1 = AgentOS(agents=[agent_with_schema])
    app1 = agent_os1.get_app()

    with TestClient(app1) as client1:
        response1 = client1.post(
            f"/agents/{agent_with_schema.id}/runs",
            data={"message": "Write a sci-fi movie about AI", "stream": "false"},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

    schema = {
        "title": "MovieScript",
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "genre": {"type": "string"},
        },
        "required": ["title", "genre"],
    }

    response2 = test_os_client.post(
        f"/agents/{test_agent.id}/runs",
        data={
            "message": "Write a sci-fi movie about AI",
            "output_schema": json.dumps(schema),
            "stream": "false",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    assert response1.status_code == 200
    assert response2.status_code == 200

    data1 = response1.json()
    data2 = response2.json()

    assert isinstance(data1["content"], dict)
    assert isinstance(data2["content"], dict)
    assert set(data1["content"].keys()) == set(data2["content"].keys())
    assert data1["content_type"] == data2["content_type"] == "MovieScript"


def test_team_with_output_schema(test_os_client: TestClient, test_team: Team):
    """Test team run with simple output schema passed as JSON string."""
    schema = {
        "title": "Report",
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "recommendation": {"type": "string"},
        },
        "required": ["summary", "recommendation"],
    }

    response = test_os_client.post(
        f"/teams/{test_team.id}/runs",
        data={
            "message": "Analyze the benefits of remote work",
            "output_schema": json.dumps(schema),
            "stream": "false",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    assert response.status_code == 200
    data = response.json()
    assert "content" in data
    assert isinstance(data["content"], dict)
    assert "summary" in data["content"]
    assert "recommendation" in data["content"]
    assert data["content_type"] == "Report"


def test_team_with_nested_schema(test_os_client: TestClient, test_team: Team):
    """Test team run with nested objects in output schema."""
    schema = {
        "title": "Analysis",
        "type": "object",
        "properties": {
            "topic": {"type": "string"},
            "findings": {
                "type": "object",
                "title": "Findings",
                "properties": {
                    "pros": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "cons": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": ["pros", "cons"],
            },
        },
        "required": ["topic", "findings"],
    }

    response = test_os_client.post(
        f"/teams/{test_team.id}/runs",
        data={
            "message": "Analyze electric vehicles",
            "output_schema": json.dumps(schema),
            "stream": "false",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    assert response.status_code == 200
    data = response.json()
    assert "content" in data
    assert isinstance(data["content"], dict)
    assert "findings" in data["content"]
    assert isinstance(data["content"]["findings"], dict)
    assert "pros" in data["content"]["findings"]
    assert "cons" in data["content"]["findings"]


def test_team_streaming_with_schema(test_os_client: TestClient, test_team: Team):
    """Test team streaming run with output schema."""
    schema = {
        "title": "Result",
        "type": "object",
        "properties": {
            "output": {"type": "string"},
            "status": {"type": "string"},
        },
        "required": ["output"],
    }

    response = test_os_client.post(
        f"/teams/{test_team.id}/runs",
        data={
            "message": "Write a tagline for a tech startup",
            "output_schema": json.dumps(schema),
            "stream": "true",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    assert response.status_code == 200
    assert "text/event-stream" in response.headers.get("content-type", "")


def test_team_without_schema(test_os_client: TestClient, test_team: Team):
    """Test team run without output schema returns plain string."""
    response = test_os_client.post(
        f"/teams/{test_team.id}/runs",
        data={"message": "Hello", "stream": "false"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    assert response.status_code == 200
    data = response.json()
    assert "content" in data
    assert isinstance(data["content"], str)


def test_team_with_array_schema(test_os_client: TestClient, test_team: Team):
    """Test team run with array fields in output schema."""
    schema = {
        "title": "Recipe",
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "ingredients": {
                "type": "array",
                "items": {"type": "string"},
            },
            "prep_time": {"type": "integer"},
        },
        "required": ["name", "ingredients"],
    }

    response = test_os_client.post(
        f"/teams/{test_team.id}/runs",
        data={
            "message": "Give me a simple pasta recipe",
            "output_schema": json.dumps(schema),
            "stream": "false",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    assert response.status_code == 200
    data = response.json()
    assert "content" in data
    assert isinstance(data["content"], dict)
    assert "ingredients" in data["content"]
    assert isinstance(data["content"]["ingredients"], list)
    assert len(data["content"]["ingredients"]) > 0


def test_team_with_optional_fields(test_os_client: TestClient, test_team: Team):
    """Test team run with optional fields in output schema."""
    schema = {
        "title": "Config",
        "type": "object",
        "properties": {
            "host": {"type": "string"},
            "port": {"type": "integer"},
            "username": {"type": "string"},
            "password": {"type": "string"},
        },
        "required": ["host", "port"],
    }

    response = test_os_client.post(
        f"/teams/{test_team.id}/runs",
        data={
            "message": "Create a server config for localhost:8080",
            "output_schema": json.dumps(schema),
            "stream": "false",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    assert response.status_code == 200
    data = response.json()
    assert "content" in data
    assert isinstance(data["content"], dict)
    assert "host" in data["content"]
    assert "port" in data["content"]


def test_team_with_invalid_schema(test_os_client: TestClient, test_team: Team):
    """Test team run handles invalid output schema gracefully."""
    response = test_os_client.post(
        f"/teams/{test_team.id}/runs",
        data={
            "message": "Write a story",
            "output_schema": "not valid json{",
            "stream": "false",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    assert response.status_code == 200
    data = response.json()
    assert "content" in data
    assert isinstance(data["content"], str)


def test_team_with_array_of_objects(test_os_client: TestClient, test_team: Team):
    """Test team run with array of objects in output schema."""
    schema = {
        "title": "MovieCast",
        "type": "object",
        "properties": {
            "movie": {"type": "string"},
            "actors": {
                "type": "array",
                "items": {
                    "type": "object",
                    "title": "Actor",
                    "properties": {
                        "name": {"type": "string"},
                        "role": {"type": "string"},
                    },
                    "required": ["name", "role"],
                },
            },
        },
        "required": ["movie", "actors"],
    }

    response = test_os_client.post(
        f"/teams/{test_team.id}/runs",
        data={
            "message": "Create a cast for a space movie with 2 actors",
            "output_schema": json.dumps(schema),
            "stream": "false",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    assert response.status_code == 200
    data = response.json()
    assert "content" in data
    assert isinstance(data["content"], dict)
    assert "actors" in data["content"]
    assert isinstance(data["content"]["actors"], list)
    if len(data["content"]["actors"]) > 0:
        assert "name" in data["content"]["actors"][0]
        assert "role" in data["content"]["actors"][0]


def test_team_preconfigured_vs_dynamic_schema(test_os_client: TestClient, test_team: Team):
    """Compare team with pre-configured schema vs dynamic schema passed via API."""
    team_with_schema = Team(
        name="Writing Team",
        members=[
            Agent(
                name="Writer",
                model=OpenAIChat(id="gpt-4o-mini"),
                telemetry=False,
            )
        ],
        output_schema=MovieScript,
        telemetry=False,
        markdown=False,
    )
    agent_os1 = AgentOS(teams=[team_with_schema])
    app1 = agent_os1.get_app()

    with TestClient(app1) as client1:
        response1 = client1.post(
            f"/teams/{team_with_schema.id}/runs",
            data={"message": "Write a sci-fi movie about AI", "stream": "false"},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

    schema = {
        "title": "MovieScript",
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "genre": {"type": "string"},
        },
        "required": ["title", "genre"],
    }

    response2 = test_os_client.post(
        f"/teams/{test_team.id}/runs",
        data={
            "message": "Write a sci-fi movie about AI",
            "output_schema": json.dumps(schema),
            "stream": "false",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    assert response1.status_code == 200
    assert response2.status_code == 200

    data1 = response1.json()
    data2 = response2.json()

    assert isinstance(data1["content"], dict)
    assert isinstance(data2["content"], dict)
    assert set(data1["content"].keys()) == set(data2["content"].keys())
    assert data1["content_type"] == data2["content_type"] == "MovieScript"


def test_agent_use_json_schema_true_keeps_dict(test_os_client: TestClient, test_agent: Agent):
    """Test use_json_schema=true keeps output_schema as dict for direct pass-through."""
    schema = {
        "type": "json_schema",
        "json_schema": {
            "name": "Person",
            "schema": {
                "type": "object",
                "properties": {"name": {"type": "string"}, "age": {"type": "integer"}},
                "required": ["name", "age"],
                "additionalProperties": False,
            },
        },
    }

    response = test_os_client.post(
        f"/agents/{test_agent.id}/runs",
        data={
            "message": "Person named Alice age 30",
            "output_schema": json.dumps(schema),
            "use_json_schema": "true",
            "stream": "false",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data.get("content"), dict)
    assert "name" in data["content"]
    assert "age" in data["content"]


def test_agent_use_json_schema_false_converts_to_pydantic(test_os_client: TestClient, test_agent: Agent):
    """Test use_json_schema=false converts to Pydantic model."""
    schema = {
        "type": "object",
        "properties": {"city": {"type": "string"}, "country": {"type": "string"}},
        "required": ["city", "country"],
    }

    response = test_os_client.post(
        f"/agents/{test_agent.id}/runs",
        data={
            "message": "City: Paris, Country: France",
            "output_schema": json.dumps(schema),
            "use_json_schema": "false",
            "stream": "false",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data.get("content"), dict)
    assert "city" in data["content"]


def test_agent_json_object_format_passthrough(test_os_client: TestClient, test_agent: Agent):
    """Test json_object format passes through with use_json_schema=true."""
    schema = {"type": "json_object"}

    response = test_os_client.post(
        f"/agents/{test_agent.id}/runs",
        data={
            "message": "Return JSON with name=Charlie and age=35",
            "output_schema": json.dumps(schema),
            "use_json_schema": "true",
            "stream": "false",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data.get("content"), dict)


def test_team_use_json_schema_true_keeps_dict(test_os_client: TestClient, test_team: Team):
    """Test team with use_json_schema=true keeps output_schema as dict."""
    schema = {
        "type": "json_schema",
        "json_schema": {
            "name": "Report",
            "schema": {
                "type": "object",
                "properties": {"summary": {"type": "string"}, "score": {"type": "integer"}},
                "required": ["summary", "score"],
                "additionalProperties": False,
            },
        },
    }

    response = test_os_client.post(
        f"/teams/{test_team.id}/runs",
        data={
            "message": "Write a report summary with score 85",
            "output_schema": json.dumps(schema),
            "use_json_schema": "true",
            "stream": "false",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data.get("content"), dict)
    assert "summary" in data["content"]
    assert "score" in data["content"]


def test_team_use_json_schema_false_converts_to_pydantic(test_os_client: TestClient, test_team: Team):
    """Test team with use_json_schema=false converts to Pydantic model."""
    schema = {
        "type": "object",
        "properties": {"city": {"type": "string"}, "country": {"type": "string"}},
        "required": ["city", "country"],
    }

    response = test_os_client.post(
        f"/teams/{test_team.id}/runs",
        data={
            "message": "City: Tokyo, Country: Japan",
            "output_schema": json.dumps(schema),
            "use_json_schema": "false",
            "stream": "false",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data.get("content"), dict)
    assert "city" in data["content"]


def test_team_json_object_format_passthrough(test_os_client: TestClient, test_team: Team):
    """Test team with json_object format passes through with use_json_schema=true."""
    schema = {"type": "json_object"}

    response = test_os_client.post(
        f"/teams/{test_team.id}/runs",
        data={
            "message": "Return JSON with product=phone and price=999",
            "output_schema": json.dumps(schema),
            "use_json_schema": "true",
            "stream": "false",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data.get("content"), dict)


def test_agent_streaming_use_json_schema_true(test_os_client: TestClient, test_agent: Agent):
    """Test agent streaming with use_json_schema=true passes through dict schema."""
    schema = {
        "type": "json_schema",
        "json_schema": {
            "name": "Answer",
            "schema": {
                "type": "object",
                "properties": {"answer": {"type": "string"}},
                "required": ["answer"],
            },
        },
    }

    with test_os_client.stream(
        "POST",
        f"/agents/{test_agent.id}/runs",
        data={
            "message": "What is 2+2? Answer in JSON.",
            "output_schema": json.dumps(schema),
            "use_json_schema": "true",
            "stream": "true",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    ) as response:
        assert response.status_code == 200
        assert "text/event-stream" in response.headers.get("content-type", "")

        # Collect streaming chunks
        chunks = []
        for line in response.iter_lines():
            if line.startswith("data: "):
                data = line[6:]
                if data != "[DONE]":
                    chunks.append(json.loads(data))

        # Verify we received data
        assert len(chunks) > 0

        # Check first chunk has expected fields
        first_chunk = chunks[0]
        assert first_chunk.get("run_id") is not None
        assert first_chunk.get("agent_id") == test_agent.id

        # Verify content across chunks
        content_chunks = [chunk.get("content") for chunk in chunks if chunk.get("content")]
        assert len(content_chunks) > 0

        # Verify final content is dict with expected keys
        last_chunk = chunks[-1]
        if last_chunk.get("content"):
            assert isinstance(last_chunk["content"], dict)
            assert "answer" in last_chunk["content"]


def test_agent_streaming_json_object_passthrough(test_os_client: TestClient, test_agent: Agent):
    """Test agent streaming with json_object format passes through."""
    schema = {"type": "json_object"}

    with test_os_client.stream(
        "POST",
        f"/agents/{test_agent.id}/runs",
        data={
            "message": "Return JSON with x=1 and y=2",
            "output_schema": json.dumps(schema),
            "use_json_schema": "true",
            "stream": "true",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    ) as response:
        assert response.status_code == 200
        assert "text/event-stream" in response.headers.get("content-type", "")

        # Collect streaming chunks
        chunks = []
        for line in response.iter_lines():
            if line.startswith("data: "):
                data = line[6:]
                if data != "[DONE]":
                    chunks.append(json.loads(data))

        # Verify we received data
        assert len(chunks) > 0

        # Check first chunk has expected fields
        first_chunk = chunks[0]
        assert first_chunk.get("run_id") is not None
        assert first_chunk.get("agent_id") == test_agent.id

        # Verify content across chunks
        content_chunks = [chunk.get("content") for chunk in chunks if chunk.get("content")]
        assert len(content_chunks) > 0

        # Verify final content is dict
        last_chunk = chunks[-1]
        if last_chunk.get("content"):
            assert isinstance(last_chunk["content"], dict)


def test_team_streaming_use_json_schema_true(test_os_client: TestClient, test_team: Team):
    """Test team streaming with use_json_schema=true passes through dict schema."""
    schema = {
        "type": "json_schema",
        "json_schema": {
            "name": "Result",
            "schema": {
                "type": "object",
                "properties": {"result": {"type": "string"}},
                "required": ["result"],
            },
        },
    }

    with test_os_client.stream(
        "POST",
        f"/teams/{test_team.id}/runs",
        data={
            "message": "Give me a result in JSON format.",
            "output_schema": json.dumps(schema),
            "use_json_schema": "true",
            "stream": "true",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    ) as response:
        assert response.status_code == 200
        assert "text/event-stream" in response.headers.get("content-type", "")

        # Collect streaming chunks
        chunks = []
        for line in response.iter_lines():
            if line.startswith("data: "):
                data = line[6:]
                if data != "[DONE]":
                    chunks.append(json.loads(data))

        # Verify we received data
        assert len(chunks) > 0

        # Check first chunk has expected fields
        first_chunk = chunks[0]
        assert first_chunk.get("run_id") is not None
        assert first_chunk.get("team_id") == test_team.id

        # Verify content across chunks
        content_chunks = [chunk.get("content") for chunk in chunks if chunk.get("content")]
        assert len(content_chunks) > 0

        # Verify final content is dict with expected keys
        last_chunk = chunks[-1]
        if last_chunk.get("content"):
            assert isinstance(last_chunk["content"], dict)
            assert "result" in last_chunk["content"]


def test_team_streaming_json_object_passthrough(test_os_client: TestClient, test_team: Team):
    """Test team streaming with json_object format passes through."""
    schema = {"type": "json_object"}

    with test_os_client.stream(
        "POST",
        f"/teams/{test_team.id}/runs",
        data={
            "message": "Return JSON with a=1 and b=2",
            "output_schema": json.dumps(schema),
            "use_json_schema": "true",
            "stream": "true",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    ) as response:
        assert response.status_code == 200
        assert "text/event-stream" in response.headers.get("content-type", "")

        # Collect streaming chunks
        chunks = []
        for line in response.iter_lines():
            if line.startswith("data: "):
                data = line[6:]
                if data != "[DONE]":
                    chunks.append(json.loads(data))

        # Verify we received data
        assert len(chunks) > 0

        # Check first chunk has expected fields
        first_chunk = chunks[0]
        assert first_chunk.get("run_id") is not None
        assert first_chunk.get("team_id") == test_team.id

        # Verify content across chunks
        content_chunks = [chunk.get("content") for chunk in chunks if chunk.get("content")]
        assert len(content_chunks) > 0

        # Verify final content is dict
        last_chunk = chunks[-1]
        if last_chunk.get("content"):
            assert isinstance(last_chunk["content"], dict)
