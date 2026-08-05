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
