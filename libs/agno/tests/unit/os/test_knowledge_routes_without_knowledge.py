"""The knowledge routes on an AgentOS that has no knowledge base.

The routes stay mounted -- a knowledge base can appear after construction, via resync,
via an agent, or via the registry -- so the honest answer has to come from the resolver
rather than from whether the router was built.
"""

from pathlib import Path
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from agno.agent.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.knowledge.knowledge import Knowledge
from agno.os import AgentOS


def _build_client(**kwargs) -> TestClient:
    agent = Agent(name="No KB Agent", id="no-kb-agent", telemetry=False)
    return TestClient(AgentOS(agents=[agent], telemetry=False, **kwargs).get_app())


def test_knowledge_config_returns_503_when_no_knowledge_base_is_configured():
    response = _build_client().get("/knowledge/config")

    assert response.status_code == 503
    assert "No knowledge base is available" in response.json()["detail"]


def test_knowledge_content_returns_503_when_no_knowledge_base_is_configured():
    """The fix belongs to the shared resolver, so every knowledge route answers the same."""
    response = _build_client().get("/knowledge/content")

    assert response.status_code == 503
    assert "No knowledge base is available" in response.json()["detail"]


def test_the_no_knowledge_base_error_does_not_blame_the_caller():
    response = _build_client().get("/knowledge/config")

    assert "multiple knowledge bases" not in response.json()["detail"]
    assert "contents_db" in response.json()["detail"]


def test_a_named_identifier_still_answers_not_found():
    """A caller that named an id gets the precise answer; only the empty no-identifier case moved."""
    response = _build_client().get("/knowledge/config", params={"knowledge_id": "does-not-exist"})

    assert response.status_code == 404
    assert "does-not-exist" in response.json()["detail"]


def test_knowledge_routes_stay_mounted_without_a_knowledge_base():
    paths = _build_client().get("/openapi.json").json()["paths"]

    assert "/knowledge/config" in paths
    assert "/knowledge/content" in paths


def test_a_knowledge_base_without_a_contents_db_is_not_served():
    """It is a working knowledge base for agent search, just not one the routes can serve."""
    agent = Agent(name="KB Agent", id="kb-agent", knowledge=Knowledge(name="No DB KB"), telemetry=False)
    client = TestClient(AgentOS(agents=[agent], telemetry=False).get_app())

    response = client.get("/knowledge/config")

    assert response.status_code == 503
    # The one place it is worth saying so is the request that went looking for it.
    assert "contents_db" in response.json()["detail"]


def test_single_knowledge_base_still_resolves_without_an_identifier(tmp_path: Path):
    """Guards the new early return against shadowing the single-instance path."""
    knowledge = Knowledge(
        name="Solo KB",
        contents_db=SqliteDb(db_file=str(tmp_path / "kb.db")),
        # A bare MagicMock here fails VectorDbSchema's string fields inside get_config.
        vector_db=None,
    )
    agent = Agent(name="Solo Agent", id="solo-agent", telemetry=False)
    client = TestClient(AgentOS(agents=[agent], knowledge=[knowledge], telemetry=False).get_app())

    response = client.get("/knowledge/config")

    assert response.status_code == 200
    assert response.json()["readers"]


def test_multiple_knowledge_bases_still_require_an_identifier(tmp_path: Path):
    """The message the empty case borrowed still belongs to the case it describes."""
    knowledge_bases = [
        Knowledge(name=f"KB {index}", contents_db=SqliteDb(db_file=str(tmp_path / f"kb{index}.db")), vector_db=None)
        for index in range(2)
    ]
    agent = Agent(name="Multi Agent", id="multi-agent", telemetry=False)
    client = TestClient(AgentOS(agents=[agent], knowledge=knowledge_bases, telemetry=False).get_app())

    response = client.get("/knowledge/config")

    assert response.status_code == 400
    assert "multiple knowledge bases" in response.json()["detail"]


def test_a_mocked_knowledge_instance_is_untouched_by_the_empty_check():
    """A non-empty list never reaches the new branch, whatever it holds."""
    from agno.os.utils import get_knowledge_instance

    knowledge = MagicMock()

    assert get_knowledge_instance([knowledge]) is knowledge
