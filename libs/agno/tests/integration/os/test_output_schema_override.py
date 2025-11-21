"""
Integration tests for AgentOS dynamic output_schema.

Tests passing output_schema as JSON schema string via AgentOS API endpoints.
"""

import json

from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.team import Team


class MovieScript(BaseModel):
    title: str = Field(..., description="Movie title")
    genre: str = Field(..., description="Movie genre")


def test_agent_with_output_schema():
    """Test agent run with simple output schema passed as JSON string."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        telemetry=False,
        markdown=False,
    )
    agent_os = AgentOS(agents=[agent])
    app = agent_os.get_app()
    client = TestClient(app)

    schema = {
        "title": "MovieScript",
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "genre": {"type": "string"},
        },
        "required": ["title", "genre"],
    }

    response = client.post(
        f"/agents/{agent.id}/runs",
        data={
            "message": "Write a movie about AI",
            "output_schema": json.dumps(schema),
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


def test_agent_with_nested_schema():
    """Test agent run with nested object in output schema."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        telemetry=False,
        markdown=False,
    )
    agent_os = AgentOS(agents=[agent])
    app = agent_os.get_app()
    client = TestClient(app)

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

    response = client.post(
        f"/agents/{agent.id}/runs",
        data={
            "message": "Create a product: laptop from a tech supplier in USA",
            "output_schema": json.dumps(schema),
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


def test_agent_with_array_schema():
    """Test agent run with array fields in output schema."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        telemetry=False,
        markdown=False,
    )
    agent_os = AgentOS(agents=[agent])
    app = agent_os.get_app()
    client = TestClient(app)

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

    response = client.post(
        f"/agents/{agent.id}/runs",
        data={
            "message": "Give me a simple pasta recipe",
            "output_schema": json.dumps(schema),
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


def test_agent_with_optional_fields():
    """Test agent run with optional fields in output schema."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        telemetry=False,
        markdown=False,
    )
    agent_os = AgentOS(agents=[agent])
    app = agent_os.get_app()
    client = TestClient(app)

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

    response = client.post(
        f"/agents/{agent.id}/runs",
        data={
            "message": "Create a server config for localhost:8080",
            "output_schema": json.dumps(schema),
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    assert response.status_code == 200
    data = response.json()
    assert "content" in data
    assert isinstance(data["content"], dict)
    assert "host" in data["content"]
    assert "port" in data["content"]


def test_agent_streaming_with_schema():
    """Test agent streaming run with output schema."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        telemetry=False,
        markdown=False,
    )
    agent_os = AgentOS(agents=[agent])
    app = agent_os.get_app()
    client = TestClient(app)

    schema = {
        "title": "Answer",
        "type": "object",
        "properties": {
            "answer": {"type": "string"},
            "confidence": {"type": "number"},
        },
        "required": ["answer"],
    }

    response = client.post(
        f"/agents/{agent.id}/runs",
        data={
            "message": "What is 2+2?",
            "output_schema": json.dumps(schema),
            "stream": "true",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    assert response.status_code == 200
    assert "text/event-stream" in response.headers.get("content-type", "")


def test_agent_with_invalid_schema():
    """Test agent run handles invalid output schema gracefully."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        telemetry=False,
        markdown=False,
    )
    agent_os = AgentOS(agents=[agent])
    app = agent_os.get_app()
    client = TestClient(app)

    response = client.post(
        f"/agents/{agent.id}/runs",
        data={
            "message": "Write a story",
            "output_schema": "not valid json{",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    assert response.status_code == 200
    data = response.json()
    assert "content" in data
    assert isinstance(data["content"], str)


def test_agent_with_array_of_objects():
    """Test agent run with array of objects in output schema."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        telemetry=False,
        markdown=False,
    )
    agent_os = AgentOS(agents=[agent])
    app = agent_os.get_app()
    client = TestClient(app)

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

    response = client.post(
        f"/agents/{agent.id}/runs",
        data={
            "message": "Create a cast for a space movie with 2 actors",
            "output_schema": json.dumps(schema),
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


def test_agent_preconfigured_vs_dynamic_schema():
    """Compare agent with pre-configured schema vs dynamic schema passed via API."""
    agent_with_schema = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        output_schema=MovieScript,
        telemetry=False,
        markdown=False,
    )
    agent_os1 = AgentOS(agents=[agent_with_schema])
    app1 = agent_os1.get_app()
    client1 = TestClient(app1)

    response1 = client1.post(
        f"/agents/{agent_with_schema.id}/runs",
        data={"message": "Write a sci-fi movie about AI"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    agent_without_schema = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        telemetry=False,
        markdown=False,
    )
    agent_os2 = AgentOS(agents=[agent_without_schema])
    app2 = agent_os2.get_app()
    client2 = TestClient(app2)

    schema = {
        "title": "MovieScript",
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "genre": {"type": "string"},
        },
        "required": ["title", "genre"],
    }

    response2 = client2.post(
        f"/agents/{agent_without_schema.id}/runs",
        data={
            "message": "Write a sci-fi movie about AI",
            "output_schema": json.dumps(schema),
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


def test_team_with_output_schema():
    """Test team run with simple output schema passed as JSON string."""
    agent1 = Agent(
        name="Writer",
        model=OpenAIChat(id="gpt-4o-mini"),
        telemetry=False,
    )
    agent2 = Agent(
        name="Editor",
        model=OpenAIChat(id="gpt-4o-mini"),
        telemetry=False,
    )
    team = Team(
        name="Content Team",
        members=[agent1, agent2],
        telemetry=False,
        markdown=False,
    )
    agent_os = AgentOS(teams=[team])
    app = agent_os.get_app()
    client = TestClient(app)

    schema = {
        "title": "Report",
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "recommendation": {"type": "string"},
        },
        "required": ["summary", "recommendation"],
    }

    response = client.post(
        f"/teams/{team.id}/runs",
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


def test_team_with_nested_schema():
    """Test team run with nested objects in output schema."""
    agent1 = Agent(
        name="Analyst",
        model=OpenAIChat(id="gpt-4o-mini"),
        telemetry=False,
    )
    team = Team(
        name="Analysis Team",
        members=[agent1],
        telemetry=False,
        markdown=False,
    )
    agent_os = AgentOS(teams=[team])
    app = agent_os.get_app()
    client = TestClient(app)

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

    response = client.post(
        f"/teams/{team.id}/runs",
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


def test_team_streaming_with_schema():
    """Test team streaming run with output schema."""
    agent1 = Agent(
        name="Writer",
        model=OpenAIChat(id="gpt-4o-mini"),
        telemetry=False,
    )
    team = Team(
        name="Writing Team",
        members=[agent1],
        telemetry=False,
        markdown=False,
    )
    agent_os = AgentOS(teams=[team])
    app = agent_os.get_app()
    client = TestClient(app)

    schema = {
        "title": "Result",
        "type": "object",
        "properties": {
            "output": {"type": "string"},
            "status": {"type": "string"},
        },
        "required": ["output"],
    }

    response = client.post(
        f"/teams/{team.id}/runs",
        data={
            "message": "Write a tagline for a tech startup",
            "output_schema": json.dumps(schema),
            "stream": "true",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    assert response.status_code == 200
    assert "text/event-stream" in response.headers.get("content-type", "")


def test_team_without_schema():
    """Test team run without output schema returns plain string."""
    agent1 = Agent(
        name="Agent1",
        model=OpenAIChat(id="gpt-4o-mini"),
        telemetry=False,
    )
    team = Team(
        name="Test Team",
        members=[agent1],
        telemetry=False,
        markdown=False,
    )
    agent_os = AgentOS(teams=[team])
    app = agent_os.get_app()
    client = TestClient(app)

    response = client.post(
        f"/teams/{team.id}/runs",
        data={"message": "Hello", "stream": "false"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    assert response.status_code == 200
    data = response.json()
    assert "content" in data
    assert isinstance(data["content"], str)


def test_team_with_array_schema():
    """Test team run with array fields in output schema."""
    agent1 = Agent(
        name="Chef",
        model=OpenAIChat(id="gpt-4o-mini"),
        telemetry=False,
    )
    team = Team(
        name="Recipe Team",
        members=[agent1],
        telemetry=False,
        markdown=False,
    )
    agent_os = AgentOS(teams=[team])
    app = agent_os.get_app()
    client = TestClient(app)

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

    response = client.post(
        f"/teams/{team.id}/runs",
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


def test_team_with_optional_fields():
    """Test team run with optional fields in output schema."""
    agent1 = Agent(
        name="SysAdmin",
        model=OpenAIChat(id="gpt-4o-mini"),
        telemetry=False,
    )
    team = Team(
        name="Config Team",
        members=[agent1],
        telemetry=False,
        markdown=False,
    )
    agent_os = AgentOS(teams=[team])
    app = agent_os.get_app()
    client = TestClient(app)

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

    response = client.post(
        f"/teams/{team.id}/runs",
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


def test_team_with_invalid_schema():
    """Test team run handles invalid output schema gracefully."""
    agent1 = Agent(
        name="Writer",
        model=OpenAIChat(id="gpt-4o-mini"),
        telemetry=False,
    )
    team = Team(
        name="Story Team",
        members=[agent1],
        telemetry=False,
        markdown=False,
    )
    agent_os = AgentOS(teams=[team])
    app = agent_os.get_app()
    client = TestClient(app)

    response = client.post(
        f"/teams/{team.id}/runs",
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


def test_team_with_array_of_objects():
    """Test team run with array of objects in output schema."""
    agent1 = Agent(
        name="Casting Director",
        model=OpenAIChat(id="gpt-4o-mini"),
        telemetry=False,
    )
    team = Team(
        name="Casting Team",
        members=[agent1],
        telemetry=False,
        markdown=False,
    )
    agent_os = AgentOS(teams=[team])
    app = agent_os.get_app()
    client = TestClient(app)

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

    response = client.post(
        f"/teams/{team.id}/runs",
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


def test_team_preconfigured_vs_dynamic_schema():
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
    client1 = TestClient(app1)

    response1 = client1.post(
        f"/teams/{team_with_schema.id}/runs",
        data={"message": "Write a sci-fi movie about AI", "stream": "false"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    team_without_schema = Team(
        name="Writing Team",
        members=[
            Agent(
                name="Writer",
                model=OpenAIChat(id="gpt-4o-mini"),
                telemetry=False,
            )
        ],
        telemetry=False,
        markdown=False,
    )
    agent_os2 = AgentOS(teams=[team_without_schema])
    app2 = agent_os2.get_app()
    client2 = TestClient(app2)

    schema = {
        "title": "MovieScript",
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "genre": {"type": "string"},
        },
        "required": ["title", "genre"],
    }

    response2 = client2.post(
        f"/teams/{team_without_schema.id}/runs",
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
