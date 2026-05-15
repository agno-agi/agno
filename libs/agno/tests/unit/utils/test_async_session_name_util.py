from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from agno.utils.agent import aset_session_name_util


@pytest.mark.asyncio
async def test_aset_session_name_util_uses_async_generator():
    session = SimpleNamespace(session_data={})

    entity = SimpleNamespace()
    entity.aget_session = AsyncMock(return_value=session)
    entity.agenerate_session_name = AsyncMock(return_value="Async Session Name")
    entity.generate_session_name = MagicMock(side_effect=AssertionError("sync generator should not be called"))
    entity.asave_session = AsyncMock()

    updated = await aset_session_name_util(
        entity=entity,
        session_id="session-1",
        autogenerate=True,
    )

    assert updated is session
    assert session.session_data["session_name"] == "Async Session Name"
    entity.agenerate_session_name.assert_awaited_once_with(session=session)
    entity.generate_session_name.assert_not_called()
    entity.asave_session.assert_awaited_once_with(session=session)
