"""Agent sessions belong to their owner and are shared with other users only explicitly."""

from typing import Any, AsyncIterator, Iterator, List

import pytest

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.db.sqlite.async_sqlite import AsyncSqliteDb
from agno.models.base import Model
from agno.models.response import ModelResponse
from agno.run.base import RunStatus
from agno.session.sharing import ashare_session


class RecordingModel(Model):
    """Replies "ok" and records the user messages each call saw."""

    def __init__(self, seen: List[List[str]]) -> None:
        super().__init__(id="recording", name="recording", provider="test")
        self.seen = seen

    def __deepcopy__(self, memo: Any) -> "RecordingModel":
        return type(self)(self.seen)

    def _reply(self, messages: Any = None, **kwargs: Any) -> ModelResponse:
        self.seen.append([m.content for m in messages or [] if m.role == "user"])
        return ModelResponse(role="assistant", content="ok")

    def invoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return self._reply(**kwargs)

    async def ainvoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return self._reply(**kwargs)

    def invoke_stream(self, *args: Any, **kwargs: Any) -> Iterator[ModelResponse]:
        yield self._reply(**kwargs)

    async def ainvoke_stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[ModelResponse]:
        yield self._reply(**kwargs)

    def _parse_provider_response(self, response: Any, **kwargs: Any) -> ModelResponse:
        return response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response


async def assert_refused(agent: Agent, message: str, session_id: str, user_id: str) -> None:
    """Sync databases raise; async runs report the refusal as an error run. Neither writes."""
    try:
        run = await agent.arun(message, session_id=session_id, user_id=user_id)
    except ValueError as error:
        assert "belongs to another user" in str(error)
        return
    assert run.status == RunStatus.error and "belongs to another user" in str(run.content)


@pytest.fixture(params=[False, True], ids=["sqlite", "async-sqlite"])
def setup(request, tmp_path):
    seen: List[List[str]] = []
    cls = AsyncSqliteDb if request.param else SqliteDb
    db = cls(db_file=str(tmp_path / "sessions.db"))
    agent = Agent(id="native", model=RecordingModel(seen), db=db, add_history_to_context=True)
    return agent, db, seen


@pytest.mark.asyncio
async def test_another_users_session_is_refused_without_writing(setup):
    agent, db, _ = setup
    await agent.arun("a1", session_id="s", user_id="alice")
    await assert_refused(agent, "b1", "s", "bob")
    session = await agent.aget_session("s")
    assert session.user_id == "alice"
    assert [run.input.input_content for run in session.runs] == ["a1"]
    assert await agent.aget_session("s", user_id="bob") is None


@pytest.mark.asyncio
async def test_members_share_history_in_order(setup):
    agent, db, seen = setup
    await agent.arun("a1", session_id="team", user_id="alice")
    await ashare_session(db, "team", ["bob"], user_id="alice")
    await agent.arun("b1", session_id="team", user_id="bob")
    await agent.arun("a2", session_id="team", user_id="alice")
    assert seen == [["a1"], ["a1", "b1"], ["a1", "b1", "a2"]]
    session = await agent.aget_session("team", user_id="bob")
    assert session.user_id == "alice"
    assert [(run.user_id, run.input.input_content) for run in session.runs] == [
        ("alice", "a1"),
        ("bob", "b1"),
        ("alice", "a2"),
    ]


@pytest.mark.asyncio
async def test_unowned_session_is_claimed_with_its_history(setup):
    agent, db, seen = setup
    await agent.arun("open", session_id="s")
    await agent.arun("a1", session_id="s", user_id="alice")
    assert seen[-1] == ["open", "a1"]
    assert (await agent.aget_session("s")).user_id == "alice"


@pytest.mark.asyncio
async def test_only_owner_or_admin_changes_sharing(setup):
    agent, db, _ = setup
    await agent.arun("a1", session_id="team", user_id="alice")
    await ashare_session(db, "team", ["bob"], user_id="alice")
    with pytest.raises(PermissionError):
        await ashare_session(db, "team", ["bob", "carol"], user_id="bob")
    await ashare_session(db, "team", [], is_admin=True)
    await assert_refused(agent, "b1", "team", "bob")


@pytest.mark.asyncio
async def test_caller_without_user_id_is_not_restricted(setup):
    agent, db, _ = setup
    await agent.arun("a1", session_id="s", user_id="alice")
    await agent.arun("trusted", session_id="s")
    assert (await agent.aget_session("s")).user_id == "alice"


@pytest.mark.asyncio
async def test_unowned_session_is_not_readable_by_identified_users(setup):
    agent, db, _ = setup
    run = await agent.arun("anonymous", session_id="anon")
    assert await agent.aget_session("anon", user_id="mallory") is None
    assert await agent.aget_run_output(run.run_id, "anon", user_id="mallory") is None
    assert await agent.aget_session("anon") is not None
