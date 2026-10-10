from unittest.mock import AsyncMock, Mock

import pytest

from agno.session.agent import AgentSession
from agno.utils.agent import aupdate_session_state_util, update_session_state_util


def test_update_session_state_initializes_missing_session_data():
    session = AgentSession(session_id="session-1", session_data=None)
    entity = Mock(db=None)
    entity.get_session.return_value = session

    result = update_session_state_util(entity, {"counter": 1}, session.session_id)

    assert result == {"counter": 1}
    entity.save_session.assert_called_once_with(session=session)


@pytest.mark.asyncio
async def test_aupdate_session_state_initializes_missing_session_data():
    session = AgentSession(session_id="session-1", session_data=None)
    entity = Mock(db=None)
    entity.aget_session = AsyncMock(return_value=session)
    entity.asave_session = AsyncMock()

    result = await aupdate_session_state_util(entity, {"counter": 1}, session.session_id)

    assert result == {"counter": 1}
    entity.asave_session.assert_awaited_once_with(session=session)
