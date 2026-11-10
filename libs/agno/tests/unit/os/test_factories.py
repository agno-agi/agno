"""Tests for Agent/Team/Workflow factories."""

import json
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel

from agno.agent.factory import AgentFactory
from agno.factory import (
    FactoryContextRequired,
    FactoryError,
    FactoryPermissionError,
    FactoryValidationError,
    RequestContext,
    TrustedContext,
)
from agno.team.factory import TeamFactory
from agno.workflow.factory import WorkflowFactory

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class SampleInput(BaseModel):
    persona: str = "default"
    depth: int = 3


def _make_ctx(**kwargs) -> RequestContext:
    return RequestContext(**kwargs)


def _make_mock_db():
    db = MagicMock()
    db.id = "test-db"
    return db


_mock_db = _make_mock_db()


def _make_mock_agent(agent_id: str = "produced-agent"):
    agent = MagicMock()
    agent.id = agent_id
    agent.db = None
    agent.knowledge = None
    agent.tools = None
    return agent


def _make_mock_team(team_id: str = "produced-team"):
    team = MagicMock()
    team.id = team_id
    team.db = None
    team.knowledge = None
    return team


def _make_mock_workflow(workflow_id: str = "produced-workflow"):
    wf = MagicMock()
    wf.id = workflow_id
    wf.db = None
    return wf


# ---------------------------------------------------------------------------
# AgentFactory
# ---------------------------------------------------------------------------


class TestAgentFactory:
    def test_basic_construction(self):
        factory = AgentFactory(
            db=_mock_db,
            id="test-factory",
            factory=lambda ctx: _make_mock_agent(),
            name="Test Factory",
            description="A test factory",
        )
        assert factory.id == "test-factory"
        assert factory.name == "Test Factory"
        assert factory.db == _mock_db
        assert factory.input_schema is None

    def test_db_required(self):
        with pytest.raises(ValueError, match="requires a 'db'"):
            AgentFactory(id="f1", db=None, factory=lambda ctx: None)

    def test_invoke_sync(self):
        def build(ctx):
            return _make_mock_agent(f"agent-{ctx.user_id}")

        factory = AgentFactory(db=_mock_db, id="f1", factory=build)
        ctx = _make_ctx(user_id="user-123")
        result = factory.invoke(ctx)
        assert result.id == "agent-user-123"

    @pytest.mark.asyncio
    async def test_invoke_async_with_sync_factory(self):
        def build(ctx):
            return _make_mock_agent(f"agent-{ctx.user_id}")

        factory = AgentFactory(db=_mock_db, id="f1", factory=build)
        ctx = _make_ctx(user_id="user-456")
        result = await factory.invoke_async(ctx)
        assert result.id == "agent-user-456"

    @pytest.mark.asyncio
    async def test_invoke_async_with_async_factory(self):
        async def build(ctx):
            return _make_mock_agent(f"async-agent-{ctx.user_id}")

        factory = AgentFactory(db=_mock_db, id="f1", factory=build)
        assert factory.is_async()
        ctx = _make_ctx(user_id="user-789")
        result = await factory.invoke_async(ctx)
        assert result.id == "async-agent-user-789"

    def test_invoke_sync_rejects_async(self):
        async def build(ctx):
            return _make_mock_agent()

        factory = AgentFactory(db=_mock_db, id="f1", factory=build)
        ctx = _make_ctx()
        with pytest.raises(FactoryError, match="async"):
            factory.invoke(ctx)


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


class TestInputValidation:
    def test_no_schema_passthrough(self):
        factory = AgentFactory(db=_mock_db, id="f1", factory=lambda ctx: None)
        assert factory.validate_input({"key": "val"}) == {"key": "val"}
        assert factory.validate_input(None) is None

    def test_schema_validates_dict(self):
        factory = AgentFactory(db=_mock_db, id="f1", factory=lambda ctx: None, input_schema=SampleInput)
        result = factory.validate_input({"persona": "analyst", "depth": 5})
        assert isinstance(result, SampleInput)
        assert result.persona == "analyst"
        assert result.depth == 5

    def test_schema_validates_json_string(self):
        factory = AgentFactory(db=_mock_db, id="f1", factory=lambda ctx: None, input_schema=SampleInput)
        result = factory.validate_input(json.dumps({"persona": "skeptic"}))
        assert isinstance(result, SampleInput)
        assert result.persona == "skeptic"
        assert result.depth == 3  # default

    def test_schema_defaults_when_none(self):
        factory = AgentFactory(db=_mock_db, id="f1", factory=lambda ctx: None, input_schema=SampleInput)
        result = factory.validate_input(None)
        assert isinstance(result, SampleInput)
        assert result.persona == "default"

    def test_invalid_json_raises(self):
        factory = AgentFactory(db=_mock_db, id="f1", factory=lambda ctx: None, input_schema=SampleInput)
        with pytest.raises(FactoryValidationError, match="not valid JSON"):
            factory.validate_input("{bad json")

    def test_wrong_type_raises(self):
        factory = AgentFactory(db=_mock_db, id="f1", factory=lambda ctx: None, input_schema=SampleInput)
        with pytest.raises(FactoryValidationError, match="JSON object"):
            factory.validate_input(42)

    def test_validation_failure_raises(self):
        class StrictInput(BaseModel):
            required_field: str

        factory = AgentFactory(db=_mock_db, id="f1", factory=lambda ctx: None, input_schema=StrictInput)
        with pytest.raises(FactoryValidationError, match="validation failed"):
            factory.validate_input({})


# ---------------------------------------------------------------------------
# RequestContext
# ---------------------------------------------------------------------------


class TestRequestContext:
    def test_defaults(self):
        ctx = RequestContext()
        assert ctx.user_id is None
        assert ctx.session_id is None
        assert ctx.request is None
        assert ctx.input is None
        assert ctx.trusted.claims == {}
        assert ctx.trusted.scopes == frozenset()

    def test_with_values(self):
        trusted = TrustedContext(claims={"role": "admin"}, scopes=frozenset(["read", "write"]))
        ctx = RequestContext(
            user_id="u1",
            session_id="s1",
            input={"key": "val"},
            trusted=trusted,
        )
        assert ctx.user_id == "u1"
        assert ctx.trusted.claims["role"] == "admin"
        assert "write" in ctx.trusted.scopes

    def test_frozen(self):
        ctx = RequestContext(user_id="u1")
        with pytest.raises(Exception):
            ctx.user_id = "u2"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# get_agent_by_id with factories
# ---------------------------------------------------------------------------


class TestGetAgentByIdWithFactories:
    def test_factory_invoked_with_context(self):
        from agno.os.utils import get_agent_by_id

        mock_agent = MagicMock(spec_set=["id", "db", "knowledge", "tools", "team_id", "workflow_id"])
        mock_agent.id = "produced"

        # Need to make isinstance(result, Agent) pass — use a real-ish mock
        from agno.agent.agent import Agent

        def build(ctx):
            agent = MagicMock(spec=Agent)
            agent.id = f"agent-{ctx.user_id}"
            return agent

        factory = AgentFactory(db=_mock_db, id="my-factory", factory=build)
        ctx = _make_ctx(user_id="user-1")
        result = get_agent_by_id("my-factory", agents=[factory], ctx=ctx)
        assert result is not None
        # Factory-produced agent's ID is overridden to match the factory's registration ID
        assert result.id == "my-factory"

    def test_factory_without_context_raises(self):
        from agno.os.utils import get_agent_by_id

        factory = AgentFactory(db=_mock_db, id="my-factory", factory=lambda ctx: None)
        with pytest.raises(FactoryContextRequired):
            get_agent_by_id("my-factory", agents=[factory])

    def test_factory_wrong_return_type_raises(self):
        from agno.os.utils import get_agent_by_id

        factory = AgentFactory(db=_mock_db, id="my-factory", factory=lambda ctx: "not-an-agent")
        ctx = _make_ctx()
        with pytest.raises(FactoryError, match="expected Agent"):
            get_agent_by_id("my-factory", agents=[factory], ctx=ctx)


# ---------------------------------------------------------------------------
# Exception types
# ---------------------------------------------------------------------------


class TestExceptions:
    def test_hierarchy(self):
        assert issubclass(FactoryValidationError, FactoryError)
        assert issubclass(FactoryPermissionError, FactoryError)
        assert issubclass(FactoryContextRequired, FactoryError)

    def test_permission_error_usable_in_factory(self):
        def build(ctx):
            raise FactoryPermissionError("User not authorized for this agent")

        factory = AgentFactory(db=_mock_db, id="f1", factory=build)
        ctx = _make_ctx()
        with pytest.raises(FactoryPermissionError, match="not authorized"):
            factory.invoke(ctx)


# ---------------------------------------------------------------------------
# TeamFactory and WorkflowFactory
# ---------------------------------------------------------------------------


class TestTeamFactory:
    def test_basic(self):
        factory = TeamFactory(db=_mock_db, id="tf1", factory=lambda ctx: _make_mock_team(), name="Team Factory")
        assert factory.id == "tf1"
        ctx = _make_ctx()
        result = factory.invoke(ctx)
        assert result.id == "produced-team"


class TestWorkflowFactory:
    def test_basic(self):
        factory = WorkflowFactory(db=_mock_db, id="wf1", factory=lambda ctx: _make_mock_workflow(), name="WF Factory")
        assert factory.id == "wf1"
        ctx = _make_ctx()
        result = factory.invoke(ctx)
        assert result.id == "produced-workflow"
