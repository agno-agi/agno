from unittest.mock import AsyncMock, MagicMock

from agno.agent.agent import Agent
from agno.models.response import ModelResponse
from agno.session import AgentSession
from agno.utils.agent import aset_session_name_util


async def test_agent_agenerate_session_name_uses_async_model_response():
    agent = Agent(id="session-name-agent")
    agent.model = MagicMock()
    agent.model.response = MagicMock(side_effect=AssertionError("sync response should not be called"))
    agent.model.aresponse = AsyncMock(return_value=ModelResponse(content='"Async Session Name"'))

    session_name = await agent.agenerate_session_name(session=AgentSession(session_id="session-1", runs=[]))

    assert session_name == "Async Session Name"
    agent.model.response.assert_not_called()
    agent.model.aresponse.assert_awaited_once()


async def test_aset_session_name_util_autogenerate_uses_async_generator():
    class AsyncSessionNameEntity:
        db = None

        def __init__(self):
            self.session = AgentSession(session_id="session-1", session_data={})
            self.saved_session = None

        async def aget_session(self, session_id: str):
            assert session_id == self.session.session_id
            return self.session

        async def asave_session(self, session: AgentSession):
            self.saved_session = session

        def generate_session_name(self, session: AgentSession):
            raise AssertionError("sync generator should not be called")

        async def agenerate_session_name(self, session: AgentSession):
            return "Generated Async Name"

    entity = AsyncSessionNameEntity()

    session = await aset_session_name_util(entity, session_id="session-1", autogenerate=True)  # type: ignore[arg-type]

    assert session.session_data == {"session_name": "Generated Async Name"}
    assert entity.saved_session is session
