from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agno.session.workflow import WorkflowSession
from agno.workflow.workflow import Workflow


def _make_workflow_session(session_id: str, user_id: Optional[str] = None) -> WorkflowSession:
    return WorkflowSession(session_id=session_id, workflow_id="test-workflow", user_id=user_id)


def _scoped_get_session(owner_user_id: str, session: WorkflowSession):
    def _lookup(session_id: str, session_type=None, user_id: Optional[str] = None, **kwargs):
        if session_id == session.session_id:
            if user_id is None or user_id == owner_user_id:
                return session
        return None

    return _lookup


def test_read_session_passes_user_id_to_db():
    wf = Workflow()
    wf.db = MagicMock()
    wf.db.get_session = MagicMock(return_value=None)

    wf._read_session(session_id="s1", user_id="alice")

    wf.db.get_session.assert_called_once()
    call_kwargs = wf.db.get_session.call_args.kwargs
    assert call_kwargs["user_id"] == "alice"


def test_read_session_none_user_id_passes_none():
    wf = Workflow()
    wf.db = MagicMock()
    wf.db.get_session = MagicMock(return_value=None)

    wf._read_session(session_id="s1")

    call_kwargs = wf.db.get_session.call_args.kwargs
    assert call_kwargs["user_id"] is None


@pytest.mark.asyncio
async def test_aread_session_passes_user_id_to_db():
    wf = Workflow()
    wf.db = AsyncMock()
    wf.db.get_session = AsyncMock(return_value=None)

    await wf._aread_session(session_id="s1", user_id="alice")

    wf.db.get_session.assert_called_once()
    call_kwargs = wf.db.get_session.call_args.kwargs
    assert call_kwargs["user_id"] == "alice"


def test_read_or_create_session_passes_user_id_through():
    alice_session = _make_workflow_session("s1", user_id="alice")
    wf = Workflow()
    wf.db = MagicMock()
    wf.db.get_session = MagicMock(side_effect=_scoped_get_session("alice", alice_session))

    # Bob requests Alice's session_id — should NOT get Alice's session
    result = wf.read_or_create_session(session_id="s1", user_id="bob")
    assert result.user_id == "bob"
    assert result.session_id == "s1"

    # Alice requests her own session — should get it back
    result = wf.read_or_create_session(session_id="s1", user_id="alice")
    assert result.user_id == "alice"


@pytest.mark.asyncio
async def test_aread_or_create_session_passes_user_id_through():
    alice_session = _make_workflow_session("s1", user_id="alice")
    wf = Workflow()
    wf.db = AsyncMock()
    wf.db.get_session = AsyncMock(side_effect=_scoped_get_session("alice", alice_session))

    result = await wf.aread_or_create_session(session_id="s1", user_id="bob")
    assert result.user_id == "bob"


def test_cached_workflow_session_not_returned_to_wrong_user():
    wf = Workflow(cache_session=True)
    wf.db = MagicMock()
    wf.db.get_session = MagicMock(return_value=None)

    alice_result = wf.read_or_create_session(session_id="s1", user_id="alice")
    assert alice_result.user_id == "alice"
    assert wf._workflow_session is not None

    bob_result = wf.read_or_create_session(session_id="s1", user_id="bob")
    assert bob_result.user_id == "bob"
    assert bob_result is not alice_result


def test_cached_workflow_session_returned_when_user_id_none():
    wf = Workflow(cache_session=True)
    wf.db = MagicMock()
    wf.db.get_session = MagicMock(return_value=None)

    result1 = wf.read_or_create_session(session_id="s1", user_id=None)
    assert wf._workflow_session is not None

    result2 = wf.read_or_create_session(session_id="s1", user_id=None)
    assert result2 is result1


def test_save_session_warns_on_upsert_rejection():
    wf = Workflow()
    wf.db = MagicMock()
    wf.db.upsert_session = MagicMock(return_value=None)

    session = _make_workflow_session("s1", user_id="alice")
    session.session_data = {"session_state": {}}

    with patch("agno.workflow.workflow.log_warning") as mock_warn:
        wf.save_session(session=session)
        mock_warn.assert_called_once()
        assert "not persisted" in mock_warn.call_args[0][0]
