"""Integration tests for AgentOS lifespan-based initialization."""

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from agno.agent.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.db.sqlite import SqliteDb
from agno.knowledge.knowledge import Knowledge
from agno.os import AgentOS
from agno.team.team import Team
from agno.tools.mcp import MCPTools
from agno.vectordb.lancedb import LanceDb
from agno.workflow.workflow import Workflow


def test_agents_teams_workflows_initialized():
    """Agents, teams, and workflows should be fully initialized after server starts."""
    # Create entities
    agent = Agent(name="test-agent", telemetry=False)
    team = Team(name="test-team", members=[Agent(name="team-member", telemetry=False)])
    workflow = Workflow(name="test-workflow")

    # Create AgentOS
    agent_os = AgentOS(
        agents=[agent],
        teams=[team],
        workflows=[workflow],
        telemetry=False,
    )

    # Before server starts, store_events should not be set
    assert agent.store_events is False
    assert team.store_events is False
    assert workflow.store_events is False

    # Get app and start server (TestClient triggers lifespan)
    app = agent_os.get_app()

    with TestClient(app):
        # After lifespan runs, store_events should be True
        assert agent.store_events is True, "Agent should be initialized after server start"
        assert team.store_events is True, "Team should be initialized after server start"
        assert workflow.store_events is True, "Workflow should be initialized after server start"


def test_databases_discovered_in_lifespan():
    """Databases should be discovered and registered during lifespan startup."""
    # Create entities with databases
    agent_db = SqliteDb("tmp/test_lifespan_agent.db", id="agent-db")
    team_db = SqliteDb("tmp/test_lifespan_team.db", id="team-db")
    workflow_db = SqliteDb("tmp/test_lifespan_workflow.db", id="workflow-db")

    agent = Agent(name="db-agent", db=agent_db, telemetry=False)
    team = Team(
        name="db-team",
        members=[Agent(name="team-member", telemetry=False)],
        db=team_db,
    )
    workflow = Workflow(name="db-workflow", db=workflow_db)

    agent_os = AgentOS(
        agents=[agent],
        teams=[team],
        workflows=[workflow],
        telemetry=False,
    )

    app = agent_os.get_app()

    # Before lifespan, dbs should be empty
    assert len(agent_os.dbs) == 0, "DBs should be empty before server starts"

    with TestClient(app):
        # After lifespan, dbs should be discovered
        assert len(agent_os.dbs) == 3, f"Expected 3 DBs, got {len(agent_os.dbs)}"
        assert "agent-db" in agent_os.dbs
        assert "team-db" in agent_os.dbs
        assert "workflow-db" in agent_os.dbs


def test_knowledge_instances_discovered_in_lifespan(tmp_path):
    """Knowledge instances should be discovered during lifespan startup."""
    # Create knowledge with a contents_db
    contents_db = SqliteDb(str(tmp_path / "knowledge.db"), id="knowledge-db")
    vector_db = LanceDb(
        uri=str(tmp_path / "lancedb"),
        table_name="test_vectors",
    )
    knowledge = Knowledge(
        vector_db=vector_db,
        contents_db=contents_db,
    )

    agent = Agent(
        name="knowledge-agent",
        knowledge=knowledge,
        db=InMemoryDb(),
        telemetry=False,
    )

    agent_os = AgentOS(agents=[agent], telemetry=False)
    app = agent_os.get_app()

    # Before lifespan
    assert len(agent_os.knowledge_instances) == 0

    with TestClient(app):
        # After lifespan, knowledge should be discovered
        assert len(agent_os.knowledge_instances) == 1
        assert agent_os.knowledge_instances[0] is knowledge


def test_mcp_tools_collected_in_lifespan():
    """MCP tools should be collected from agents during lifespan initialization."""
    # Create mock MCP tools
    mcp_tools = MCPTools("npm fake-command")

    # Mock connect/close to avoid actual MCP server interaction
    mcp_tools.connect = AsyncMock()
    mcp_tools.close = AsyncMock()

    agent = Agent(name="mcp-agent", tools=[mcp_tools], db=InMemoryDb(), telemetry=False)

    agent_os = AgentOS(agents=[agent], telemetry=False)

    # MCP tools list should be empty before lifespan (populated during async init)
    assert len(agent_os.mcp_tools) == 0

    app = agent_os.get_app()

    with TestClient(app):
        # After lifespan, MCP tools should be collected
        assert len(agent_os.mcp_tools) == 1
        assert agent_os.mcp_tools[0] is mcp_tools

        # Verify connect was called (may be called multiple times due to lifespan chaining)
        assert mcp_tools.connect.called, "MCP tools connect should be called during lifespan"

    # Verify close was called on shutdown
    assert mcp_tools.close.called, "MCP tools close should be called during shutdown"


def test_tracing_setup_in_lifespan():
    """Tracing should be set up during lifespan when tracing=True."""
    agent = Agent(
        name="traced-agent",
        db=SqliteDb("tmp/test_tracing.db", id="tracing-db"),
        telemetry=False,
    )

    with patch("agno.os.app.setup_tracing_for_os") as mock_setup_tracing:
        agent_os = AgentOS(
            agents=[agent],
            tracing=True,
            telemetry=False,
        )

        # Tracing should NOT be set up yet (deferred to lifespan)
        mock_setup_tracing.assert_not_called()

        app = agent_os.get_app()

        with TestClient(app):
            # After lifespan, tracing should be set up
            mock_setup_tracing.assert_called_once()
