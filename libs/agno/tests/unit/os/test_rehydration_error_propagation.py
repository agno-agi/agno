"""The OS helpers must not degrade ComponentRehydrationError to None/404."""

import pytest

from agno.agent.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.exceptions import ComponentRehydrationError
from agno.models.openai import OpenAIChat
from agno.os.utils import get_agent_by_id


def _save_agent_with_tools(db):
    def search(query: str) -> str:
        """Search for a query."""
        return f"results for {query}"

    agent = Agent(id="broken-agent", name="Broken Agent", model=OpenAIChat(id="gpt-4o-mini"), tools=[search])
    agent.save(db=db)


def test_get_agent_by_id_propagates_rehydration_error(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "os_agent.db"))
    _save_agent_with_tools(db)

    # No registry: the agent's tools cannot be rehydrated. Broken is not
    # "not found", so the error must propagate instead of returning None.
    with pytest.raises(ComponentRehydrationError):
        get_agent_by_id("broken-agent", agents=None, db=db, registry=None)


def test_resolve_agent_converts_the_refusal_to_a_422_http_error(tmp_path):
    """resolve_agent answers HTTPException with the error's own status, so the
    refusal needs no app-level handler on any deployment shape."""
    import asyncio

    from fastapi import HTTPException

    from agno.os.utils import resolve_agent

    db = SqliteDb(db_file=str(tmp_path / "resolve_strict.db"))
    _save_agent_with_tools(db)

    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(resolve_agent("broken-agent", None, db, None))

    assert excinfo.value.status_code == 422
    assert "registry" in excinfo.value.detail


def test_resolve_agent_strict_false_returns_a_degraded_component(tmp_path):
    """Lenient resolution backs cancel and the MCP cancel_run tool: a drifted
    registry must never make a run uncancellable."""
    import asyncio

    db = SqliteDb(db_file=str(tmp_path / "resolve_lenient.db"))
    _save_agent_with_tools(db)

    from agno.os.utils import resolve_agent

    agent = asyncio.run(resolve_agent("broken-agent", None, db, None, strict=False))

    assert agent is not None
    assert agent.id == "broken-agent"
