"""Team-level result offloading against SQLite and PostgreSQL.

A member's answer reaches the leader as the result of the delegation tool, so
it is the payload that grows a team session. These tests pin that the leader's
transcript holds an envelope rather than the answer, on the sync, async and
streaming paths, and that a member can read back what the leader stored.
"""

import json
import os
import uuid
from typing import Any, AsyncIterator, Iterator, List

import pytest
from sqlalchemy import create_engine, text

from agno.agent import Agent
from agno.db.base import SessionType
from agno.db.sqlite import SqliteDb
from agno.models.base import Model
from agno.models.message import Message, MessageMetrics
from agno.models.response import ModelResponse
from agno.offload import ResultStore
from agno.team import Team

pytestmark = pytest.mark.integration

PG_URL = "postgresql+psycopg://ai:ai@localhost:5532/ai"
PG_SCHEMA = f"offload_team_test_{os.getpid()}"

BIG = "\n".join(f"finding {i}: " + "d" * 60 for i in range(1, 3001))
NEEDLE = "finding 2500: "


class LeaderModel(Model):
    """Delegates once to the named member, then answers."""

    def __init__(self, member_id: str = "researcher", task: str = "summarise the corpus"):
        super().__init__(id="leader", name="leader", provider="test")
        self.member_id = member_id
        self.task = task
        self.calls = 0
        # The team does not retain the resolved tool list, so capture what it
        # hands the model.
        self.seen_functions: dict = {}
        # Characters in each prompt the leader is handed. RunOutput.messages
        # holds only the messages one run created, so it is not the same thing.
        self.prompt_sizes: List[int] = []

    def response(self, *args: Any, **kwargs: Any) -> ModelResponse:
        self._capture(args, kwargs)
        return super().response(*args, **kwargs)

    async def aresponse(self, *args: Any, **kwargs: Any) -> ModelResponse:
        self._capture(args, kwargs)
        return await super().aresponse(*args, **kwargs)

    def response_stream(self, *args: Any, **kwargs: Any) -> Any:
        self._capture(args, kwargs)
        return super().response_stream(*args, **kwargs)

    def aresponse_stream(self, *args: Any, **kwargs: Any) -> Any:
        self._capture(args, kwargs)
        return super().aresponse_stream(*args, **kwargs)

    def _capture(self, args: tuple, kwargs: dict) -> None:
        for tool in kwargs.get("tools") or []:
            name = getattr(tool, "name", None)
            if name:
                self.seen_functions[name] = tool
        messages = kwargs.get("messages") or (args[0] if args else None)
        self.prompt_sizes.append(sum(len(message.content or "") for message in (messages or [])))

    def _next(self) -> ModelResponse:
        self.calls += 1
        if self.calls == 1:
            return ModelResponse(
                role="assistant",
                tool_calls=[
                    {
                        "id": "call-1",
                        "type": "function",
                        "function": {
                            "name": "delegate_task_to_member",
                            "arguments": json.dumps({"member_id": self.member_id, "task": self.task}),
                        },
                    }
                ],
                response_usage=MessageMetrics(),
            )
        return ModelResponse(role="assistant", content="done", response_usage=MessageMetrics())

    def invoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return self._next()

    async def ainvoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return self._next()

    def invoke_stream(self, *args: Any, **kwargs: Any) -> Iterator[ModelResponse]:
        yield self._next()

    async def ainvoke_stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[ModelResponse]:
        yield self._next()

    def _parse_provider_response(self, response: Any, **kwargs: Any) -> ModelResponse:
        return response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response


class MemberModel(Model):
    """Answers with one long body."""

    def __init__(self, body: str = BIG):
        super().__init__(id="member", name="member", provider="test")
        self.body = body

    def _answer(self) -> ModelResponse:
        return ModelResponse(role="assistant", content=self.body, response_usage=MessageMetrics())

    def invoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return self._answer()

    async def ainvoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return self._answer()

    def invoke_stream(self, *args: Any, **kwargs: Any) -> Iterator[ModelResponse]:
        yield self._answer()

    async def ainvoke_stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[ModelResponse]:
        yield self._answer()

    def _parse_provider_response(self, response: Any, **kwargs: Any) -> ModelResponse:
        return response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response


@pytest.fixture(scope="session")
def pg_engine():
    engine = create_engine(PG_URL)
    with engine.begin() as conn:
        conn.execute(text("SELECT 1"))
        conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{PG_SCHEMA}"'))
    yield engine
    with engine.begin() as conn:
        conn.execute(text(f'DROP SCHEMA IF EXISTS "{PG_SCHEMA}" CASCADE'))
        # Payloads live in the shared fs schema, which other lanes use too.
        # Remove this module's rows by namespace rather than the table, and
        # only when a test in this session created the table at all.
        if conn.execute(text("SELECT to_regclass('fs.agno_fs')")).scalar() is not None:
            conn.execute(text("DELETE FROM fs.agno_fs WHERE namespace LIKE 'tool-results/offload-team-%'"))
    engine.dispose()


@pytest.fixture(params=["sqlite", "postgresql"])
def db(request, tmp_path):
    if request.param == "sqlite":
        yield SqliteDb(db_file=str(tmp_path / "team.db"))
    else:
        from agno.db.postgres import PostgresDb

        request.getfixturevalue("pg_engine")
        pg_db = PostgresDb(db_url=PG_URL, db_schema=PG_SCHEMA)
        yield pg_db
        with pg_db.db_engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{PG_SCHEMA}" CASCADE'))
            conn.execute(text(f'CREATE SCHEMA "{PG_SCHEMA}"'))


def _sid() -> str:
    return f"offload-team-{uuid.uuid4().hex[:10]}"


def _member(body: str = BIG, member_id: str = "researcher") -> Agent:
    return Agent(name=member_id, id=member_id, model=MemberModel(body=body))


def _team(db, offload_tool_results=True, body: str = BIG, **kwargs) -> Team:
    return Team(
        name="platform",
        id="platform",
        members=[_member(body=body)],
        model=LeaderModel(),
        db=db,
        offload_tool_results=offload_tool_results,
        **kwargs,
    )


def _tool_messages(run_output) -> List[Any]:
    return [m for m in (run_output.messages or []) if m.role == "tool"]


def _result_id(content: str) -> str:
    return content.split('id="')[1].split('"')[0]


# ------------------------------------------------------------------
# The member response is the payload
# ------------------------------------------------------------------


def test_member_response_is_replaced_by_an_envelope(db):
    team = _team(db)
    output = team.run("go", session_id=_sid())
    tool_message = _tool_messages(output)[0]
    assert tool_message.tool_name == "delegate_task_to_member"
    assert len(tool_message.content) < 2600
    assert "lines omitted ...]" in tool_message.content
    assert tool_message.content.startswith('<result id="res_')
    assert 'tool="delegate_task_to_member"' in tool_message.content
    assert BIG not in tool_message.content


def test_the_stored_payload_is_the_whole_member_response(db):
    team = _team(db)
    output = team.run("go", session_id=_sid())
    result_id = _result_id(_tool_messages(output)[0].content)
    page = team._result_store.read(result_id, 1, 3000)
    assert page.line_count == 3000
    assert page.text.startswith("finding 1: ")


def test_offloading_off_leaves_the_member_response_inline(db):
    team = _team(db, offload_tool_results=False)
    output = team.run("go", session_id=_sid())
    tool_message = _tool_messages(output)[0]
    assert tool_message.content == BIG
    assert team._result_store is None


def test_a_short_member_response_stays_inline(db):
    team = _team(db, body="short answer")
    output = team.run("go", session_id=_sid())
    assert _tool_messages(output)[0].content == "short answer"


def test_the_persisted_session_row_carries_the_envelope(db):
    team = _team(db)
    session_id = _sid()
    team.run("go", session_id=session_id)
    session = db.get_session(session_id=session_id, session_type=SessionType.TEAM)
    stored = json.dumps(session.to_dict())
    assert "res_" in stored
    assert BIG not in stored


# ------------------------------------------------------------------
# Every path the leader can take
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_run_offloads_the_member_response(db):
    team = _team(db)
    output = await team.arun("go", session_id=_sid())
    tool_message = _tool_messages(output)[0]
    assert tool_message.content.startswith('<result id="res_')
    assert BIG not in tool_message.content


def test_streamed_run_offloads_the_member_response(db):
    team = _team(db)
    session_id = _sid()
    events = list(team.run("go", session_id=session_id, stream=True, stream_events=True))
    output = events[-1] if hasattr(events[-1], "messages") else team.get_last_run_output(session_id=session_id)
    tool_message = _tool_messages(output)[0]
    assert tool_message.content.startswith('<result id="res_')
    assert BIG not in tool_message.content


@pytest.mark.asyncio
async def test_async_streamed_run_offloads_the_member_response(db):
    team = _team(db)
    session_id = _sid()
    async for _ in team.arun("go", session_id=session_id, stream=True, stream_events=True):
        pass
    output = team.get_last_run_output(session_id=session_id)
    tool_message = _tool_messages(output)[0]
    assert tool_message.content.startswith('<result id="res_')
    assert BIG not in tool_message.content


# ------------------------------------------------------------------
# Tools and instructions on the leader
# ------------------------------------------------------------------


def test_leader_gets_the_read_back_tools(db):
    team = _team(db)
    team.run("go", session_id=_sid())
    assert "read_result" in team.model.seen_functions
    assert "search_result" in team.model.seen_functions


def test_no_read_back_tools_when_disabled(db):
    team = _team(db, offload_tool_results=False)
    team.run("go", session_id=_sid())
    assert "read_result" not in team.model.seen_functions
    assert "search_result" not in team.model.seen_functions


def test_leader_system_message_gains_the_instruction(db):
    team = _team(db)
    output = team.run("go", session_id=_sid())
    system = [m for m in (output.messages or []) if m.role == "system"][0]
    assert "Large tool results are stored as files" in system.content


def test_leader_can_read_and_search_the_stored_response(db):
    team = _team(db)
    output = team.run("go", session_id=_sid())
    result_id = _result_id(_tool_messages(output)[0].content)

    read_tool = team.model.seen_functions["read_result"]
    reply = read_tool.entrypoint(result_id=result_id, start_line=1, end_line=3)
    assert "finding 1: " in reply
    assert "lines 1-3 of 3000" in reply

    search_tool = team.model.seen_functions["search_result"]
    hits = search_tool.entrypoint(result_id=result_id, pattern=NEEDLE)
    assert "2500:" in hits


# ------------------------------------------------------------------
# Members share the leader's store
# ------------------------------------------------------------------


def test_member_inherits_the_teams_store(db):
    member = _member()
    team = Team(name="platform", id="platform", members=[member], model=LeaderModel(), db=db, offload_tool_results=True)
    team.initialize_team()
    # The member's own declared setting is left alone; only the runtime store is shared.
    assert member.offload_tool_results is None
    assert member._result_store is team._result_store


def test_a_member_that_set_its_own_store_keeps_its_settings(db):
    member = _member()
    member.offload_tool_results = ResultStore(threshold_chars=100)
    team = Team(name="platform", id="platform", members=[member], model=LeaderModel(), db=db, offload_tool_results=True)
    team.initialize_team()
    assert member._result_store is not team._result_store
    assert member._result_store.threshold_chars == 100
    # On the team's database, so the leader and the other members can read it.
    assert member._result_store.db is team._result_store.db


def test_a_member_with_no_db_of_its_own_still_gets_offloading(db):
    member = _member()
    member.offload_tool_results = True
    member.db = None
    team = Team(name="platform", id="platform", members=[member], model=LeaderModel(), db=db, offload_tool_results=True)
    team.initialize_team()
    assert member._result_store is team._result_store
    member.initialize_agent()
    assert member._result_store is team._result_store


def test_a_member_reads_a_result_stored_in_the_same_session(db):
    team = _team(db)
    session_id = _sid()
    output = team.run("go", session_id=session_id)
    result_id = _result_id(_tool_messages(output)[0].content)

    from agno.offload.tools import get_read_result_function
    from agno.run import RunContext

    member = team.members[0]
    run_context = RunContext(session_id=session_id, run_id="r1", user_id=None)
    reply = get_read_result_function(member, run_context=run_context).entrypoint(result_id=result_id, end_line=2)
    assert "finding 1: " in reply


def test_a_result_from_another_session_is_refused(db):
    team = _team(db)
    output = team.run("go", session_id=_sid())
    result_id = _result_id(_tool_messages(output)[0].content)

    from agno.offload.tools import get_read_result_function
    from agno.run import RunContext

    other = RunContext(session_id=_sid(), run_id="r1", user_id=None)
    reply = get_read_result_function(team, run_context=other).entrypoint(result_id=result_id)
    assert reply.startswith("Error: result ")
    assert "different session" in reply


# ------------------------------------------------------------------
# Results that end the run keep their text
# ------------------------------------------------------------------


def test_respond_directly_keeps_the_member_response_verbatim(db):
    team = _team(db, respond_directly=True)
    output = team.run("go", session_id=_sid())
    tool_message = _tool_messages(output)[0]
    assert tool_message.content == BIG
    # The delegation result is the answer the caller receives.
    assert output.content == BIG


# ------------------------------------------------------------------
# The point of the feature: a long session stays flat
# ------------------------------------------------------------------


def _largest_prompt_over_six_turns(db, offload: bool) -> int:
    """The biggest prompt the leader is handed across six delegating turns."""
    team = _team(db, offload_tool_results=offload, add_history_to_context=True, num_history_runs=10)
    session_id = _sid()
    for _ in range(6):
        team.model.calls = 0
        team.run("go", session_id=session_id)
    return max(team.model.prompt_sizes)


def test_six_delegations_stay_flat_with_offloading(db):
    with_offload = _largest_prompt_over_six_turns(db, offload=True)
    without_offload = _largest_prompt_over_six_turns(db, offload=False)

    # History replays every earlier delegation result, so the leader's prompt
    # grows by one member answer per turn. Offloading replaces each with an
    # envelope: measured here, 1,120,927 characters becomes 8,807.
    assert without_offload > 4 * len(BIG)
    assert with_offload < len(BIG) // 10
    assert with_offload * 50 < without_offload


def test_both_the_team_row_and_the_member_row_are_small(db):
    """The leader's row holds an envelope, and so does the member's own row.

    The member's stored run is what it replays as its own history, so it is
    context as well as storage.
    """
    team = _team(db)
    session_id = _sid()
    team.run("go", session_id=session_id)

    session = db.get_session(session_id=session_id, session_type=SessionType.TEAM)
    sizes = {}
    for run in session.to_dict().get("runs", []):
        kind = "team" if run.get("parent_run_id") is None else "member"
        sizes[kind] = sum(len(str(message.get("content") or "")) for message in (run.get("messages") or []))

    assert sizes["team"] < 10_000
    assert sizes["member"] < 10_000


def test_the_caller_still_gets_the_whole_member_answer(db):
    """Offloading changes what a model reads, never what a caller reads."""
    team = _team(db)
    output = team.run("go", session_id=_sid())
    assert output.member_responses[0].content == BIG


def test_a_paused_member_run_is_stored_whole(db):
    """Resuming replays a paused run's messages, so they must survive intact."""
    from agno.offload.runs import offload_run_for_storage
    from agno.run.agent import RunOutput
    from agno.run.base import RunStatus

    team = _team(db)
    team.initialize_team()
    messages = [Message(role="assistant", content=BIG)]

    paused = RunOutput(run_id="r-paused", messages=list(messages), status=RunStatus.paused)
    assert paused.is_paused
    same = offload_run_for_storage(team._result_store, paused, session_id="offload-team-s1")
    assert same is paused
    assert same.messages[0].content == BIG

    # The same run, not paused, is offloaded.
    running = RunOutput(run_id="r-done", messages=list(messages), status=RunStatus.completed)
    stored = offload_run_for_storage(team._result_store, running, session_id="offload-team-s1")
    assert stored is not running
    assert stored.messages[0].content.startswith('<result id="res_')
    assert running.messages[0].content == BIG


# ------------------------------------------------------------------
# share_member_interactions must not nest
# ------------------------------------------------------------------


class RoundRobinLeaderModel(LeaderModel):
    """Delegates once to each member in turn, then answers."""

    def __init__(self, member_ids: List[str]):
        super().__init__()
        self.member_ids = member_ids

    def _next(self) -> ModelResponse:
        self.calls += 1
        if self.calls <= len(self.member_ids):
            return ModelResponse(
                role="assistant",
                tool_calls=[
                    {
                        "id": f"call-{self.calls}",
                        "type": "function",
                        "function": {
                            "name": "delegate_task_to_member",
                            "arguments": json.dumps({"member_id": self.member_ids[self.calls - 1], "task": "go"}),
                        },
                    }
                ],
                response_usage=MessageMetrics(),
            )
        return ModelResponse(role="assistant", content="done", response_usage=MessageMetrics())


def test_shared_member_interactions_grow_one_answer_per_member(db):
    """Each member sees the answers before it, once each.

    The member's prompt is assembled by wrapping the leader's task in the block
    of prior interactions. Recording that assembled prompt as the interaction's
    own task would nest every block inside the next one, and the copies would
    double per member instead of growing by one.
    """
    marker = "ANSWER-MARKER"
    member_ids = ["m1", "m2", "m3", "m4", "m5"]
    members = [Agent(name=i, id=i, model=MemberModel(body=f"{marker} from {i}")) for i in member_ids]

    seen: List[int] = []
    for member in members:

        def record(model=member.model):
            def invoke(*args: Any, **kwargs: Any) -> ModelResponse:
                messages = kwargs.get("messages") or (args[0] if args else None)
                prompt = "\n".join(m.content or "" for m in (messages or []))
                seen.append(prompt.count(marker))
                return model._answer()

            return invoke

        member.model.invoke = record()

    team = Team(
        name="platform",
        id="platform",
        members=members,
        model=RoundRobinLeaderModel(member_ids),
        db=db,
        offload_tool_results=True,
        share_member_interactions=True,
    )
    team.run("go", session_id=_sid())

    assert seen == [0, 1, 2, 3, 4]


# ------------------------------------------------------------------
# Store inheritance follows the team, never the member object
# ------------------------------------------------------------------
def test_a_member_moved_to_a_second_team_follows_that_team(db, tmp_path):
    member = _member()
    first = Team(name="first", id="first", members=[member], model=LeaderModel(), db=db, offload_tool_results=True)
    first.initialize_team()
    assert member._result_store is first._result_store

    other_db = SqliteDb(db_file=str(tmp_path / "other.db"))
    second = Team(
        name="second", id="second", members=[member], model=LeaderModel(), db=other_db, offload_tool_results=True
    )
    second.initialize_team()
    assert member._result_store is second._result_store
    assert member._result_store.db is other_db
    assert member.offload_tool_results is None


def test_a_team_without_offloading_clears_an_inherited_store(db):
    member = _member()
    with_offload = Team(name="a", id="a", members=[member], model=LeaderModel(), db=db, offload_tool_results=True)
    with_offload.initialize_team()
    assert member._result_store is not None

    without = Team(name="b", id="b", members=[member], model=LeaderModel(), db=db)
    without.initialize_team()
    assert member._result_store is None


def test_a_member_with_its_own_db_is_rebound_to_the_team_db(db, tmp_path):
    member = _member()
    member.db = SqliteDb(db_file=str(tmp_path / "member.db"))
    member.offload_tool_results = True
    member.initialize_agent()
    assert member._result_store is not None and member._result_store.db is member.db

    team = Team(name="platform", id="platform", members=[member], model=LeaderModel(), db=db, offload_tool_results=True)
    team.initialize_team()
    # In the team, payloads go where the leader can read them back.
    assert member._result_store.db is db
    assert member.offload_tool_results is True


def test_a_member_with_its_own_db_and_settings_stores_on_the_team_db(db, tmp_path):
    member = _member()
    member.db = SqliteDb(db_file=str(tmp_path / "member2.db"))
    member.offload_tool_results = ResultStore(threshold_chars=100)
    team = Team(name="platform", id="platform", members=[member], model=LeaderModel(), db=db, offload_tool_results=True)
    team.initialize_team()
    assert member._result_store.threshold_chars == 100
    assert member._result_store.db is db


# ------------------------------------------------------------------
# Members that are not Agents, live session copies, caps, nested teams
# ------------------------------------------------------------------
def test_a_remote_member_does_not_break_team_initialization(db):
    from agno.agent.remote import RemoteAgent

    remote = RemoteAgent(base_url="http://localhost:1", agent_id="explorer")
    team = Team(name="hybrid", id="hybrid", members=[_member(), remote], model=LeaderModel(), db=db)
    team.initialize_team()
    with_offload = Team(
        name="hybrid2", id="hybrid2", members=[_member(), remote], model=LeaderModel(), db=db, offload_tool_results=True
    )
    with_offload.initialize_team()
    assert with_offload.members[0]._result_store is with_offload._result_store


def _member_seen_prompt_sizes(member: Agent) -> List[int]:
    return getattr(member.model, "prompt_sizes", [])


class _SizeRecordingMemberModel(MemberModel):
    """Records how big each prompt it is handed is."""

    def __init__(self, body: str = BIG):
        super().__init__(body=body)
        self.prompt_sizes: List[int] = []

    def _record(self, args, kwargs) -> None:
        messages = kwargs.get("messages") or (args[0] if args else [])
        self.prompt_sizes.append(sum(len(str(m.content or "")) for m in messages))

    def invoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        self._record(args, kwargs)
        return self._answer()

    async def ainvoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        self._record(args, kwargs)
        return self._answer()


def test_member_replays_the_envelope_within_one_team_run(db):
    member = Agent(name="researcher", id="researcher", model=_SizeRecordingMemberModel(), add_history_to_context=True)
    team = Team(
        name="platform",
        id="platform",
        members=[member],
        model=RoundRobinLeaderModel(["researcher", "researcher"]),
        db=db,
        offload_tool_results=True,
    )
    team.run("go", session_id=_sid())
    sizes = _member_seen_prompt_sizes(member)
    assert len(sizes) == 2
    # The second delegation replays the first answer as history: as an envelope, not the 200KB body.
    assert sizes[1] < len(BIG) // 10


def test_member_replays_the_envelope_with_a_cached_session(db):
    member = Agent(name="researcher", id="researcher", model=_SizeRecordingMemberModel(), add_history_to_context=True)
    team = Team(
        name="platform",
        id="platform",
        members=[member],
        model=LeaderModel(),
        db=db,
        offload_tool_results=True,
        cache_session=True,
    )
    session_id = _sid()
    team.run("go", session_id=session_id)
    team.model = LeaderModel()
    team.run("again", session_id=session_id)
    sizes = _member_seen_prompt_sizes(member)
    assert len(sizes) == 2
    assert sizes[1] < len(BIG) // 10


def test_the_caller_still_gets_the_whole_member_answer_after_upsert(db):
    team = _team(db)
    output = team.run("go", session_id=_sid())
    assert output.member_responses[0].content == BIG


def test_search_result_output_stays_within_one_page(db):
    team = _team(db)
    session_id = _sid()
    output = team.run("go", session_id=session_id)
    result_id = _result_id(_tool_messages(output)[0].content)
    from agno.offload.store import SEARCH_MAX_CHARS
    from agno.offload.tools import get_search_result_function
    from agno.run import RunContext

    run_context = RunContext(session_id=session_id, run_id="r1", user_id=None)
    search = get_search_result_function(team, run_context=run_context).entrypoint
    reply = search(result_id=result_id, pattern=r"^finding", context_lines=1000)
    assert len(reply) <= SEARCH_MAX_CHARS + 200


def test_a_sub_teams_member_replays_an_envelope_and_its_rows_are_reclaimed(db):
    inner_member = Agent(name="inner", id="inner", model=_SizeRecordingMemberModel(), add_history_to_context=True)
    inner = Team(name="inner", id="inner", members=[inner_member], model=RoundRobinLeaderModel(["inner", "inner"]))
    outer = Team(
        name="outer", id="outer", members=[inner], model=LeaderModel("inner"), db=db, offload_tool_results=True
    )
    session_id = _sid()
    outer.run("go", session_id=session_id)
    # The inner member's second turn replays its first answer as an envelope, not the 200KB body.
    sizes = _member_seen_prompt_sizes(inner_member)
    assert len(sizes) == 2 and sizes[1] < len(BIG) // 10
    # Every row of the session, referenced by a persisted run or not, goes with the session.
    assert db.get_tool_results_for_session(session_id)
    db.delete_sessions(session_ids=[session_id])
    assert db.get_tool_results_for_session(session_id) == []


def test_a_member_on_defaults_takes_the_team_settings_even_with_its_own_store(db):
    member = _member()
    member.db = db
    member.offload_tool_results = True
    member.initialize_agent()
    own = member._result_store
    assert own is not None and own.db is db

    team = Team(
        name="platform",
        id="platform",
        members=[member],
        model=LeaderModel(),
        db=db,
        offload_tool_results=ResultStore(threshold_chars=100),
    )
    team.initialize_team()
    assert member._result_store is team._result_store
    assert member._result_store.threshold_chars == 100


def test_a_member_store_that_names_its_own_db_is_still_rebound_to_the_team_db(db, tmp_path):
    other = SqliteDb(db_file=str(tmp_path / "member3.db"))
    member = _member()
    member.offload_tool_results = ResultStore(db=other, threshold_chars=100)
    team = Team(name="platform", id="platform", members=[member], model=LeaderModel(), db=db, offload_tool_results=True)
    team.initialize_team()
    assert member._result_store.threshold_chars == 100
    assert member._result_store.db is db
    # The caller's settings object is untouched.
    assert member.offload_tool_results.db is other


# ------------------------------------------------------------------
# Every copy of a member run a model can read holds envelopes
# ------------------------------------------------------------------
def test_storing_the_same_member_run_twice_keeps_one_payload(db):
    from agno.offload.runs import offload_run_for_storage
    from agno.run.agent import RunOutput
    from agno.run.base import RunStatus

    team = _team(db)
    team.initialize_team()
    run = RunOutput(run_id="r-twice", messages=[Message(role="assistant", content=BIG)], status=RunStatus.completed)
    first = offload_run_for_storage(team._result_store, run, session_id="offload-team-s-twice")
    second = offload_run_for_storage(team._result_store, run, session_id="offload-team-s-twice")
    assert first.messages[0].content == second.messages[0].content
    assert len(db.get_tool_results_for_session("offload-team-s-twice")) == 1

    # Different content under the same run and message index is a new payload.
    changed = RunOutput(
        run_id="r-twice",
        messages=[Message(role="assistant", content=BIG.replace("d", "e"))],
        status=RunStatus.completed,
    )
    offload_run_for_storage(team._result_store, changed, session_id="offload-team-s-twice")
    assert len(db.get_tool_results_for_session("offload-team-s-twice")) == 2


def test_the_team_row_embeds_envelopes_when_member_responses_are_stored(db):
    team = _team(db, store_member_responses=True)
    session_id = _sid()
    output = team.run("go", session_id=session_id)
    # The caller's copy is whole.
    assert output.member_responses[0].content == BIG
    # The persisted team row's embedded member copy is not.
    stored = db.get_session(session_id=session_id, session_type=SessionType.TEAM)
    team_runs = [r for r in (stored.runs or []) if getattr(r, "member_responses", None)]
    assert team_runs, "the team row carries the embedded member run"
    embedded = team_runs[0].member_responses[0]
    assistant = [m for m in (embedded.messages or []) if m.role == "assistant"][0]
    assert str(assistant.content).startswith('<result id="res_')
    # And only one payload exists for that member answer across the session row and the team row.
    rows = [r for r in db.get_tool_results_for_session(session_id) if r["tool_name"] == "assistant_message"]
    assert len(rows) == 1


class _GatedMemberModel(_SizeRecordingMemberModel):
    """Calls a confirmation-gated tool once, then answers with the long body."""

    def _answer(self) -> ModelResponse:
        self.calls = getattr(self, "calls", 0) + 1
        if self.calls == 1:
            return ModelResponse(
                role="assistant",
                tool_calls=[{"id": "gate-1", "type": "function", "function": {"name": "gated", "arguments": "{}"}}],
                response_usage=MessageMetrics(),
            )
        return ModelResponse(role="assistant", content=self.body, response_usage=MessageMetrics())


def test_a_member_resumed_after_confirmation_replays_the_envelope(db):
    from agno.tools.decorator import tool

    @tool(requires_confirmation=True)
    def gated() -> str:
        """A gated tool.

        Returns:
            str: ok.
        """
        return "ok"

    member = Agent(
        name="researcher", id="researcher", model=_GatedMemberModel(), tools=[gated], add_history_to_context=True
    )
    team = Team(
        name="platform",
        id="platform",
        members=[member],
        model=LeaderModel(),
        db=db,
        offload_tool_results=True,
        cache_session=True,
    )
    session_id = _sid()
    paused = team.run("go", session_id=session_id)
    assert paused.is_paused
    for requirement in paused.requirements or []:
        if requirement.tool_execution is not None:
            requirement.tool_execution.confirmed = True
    team.continue_run(paused, session_id=session_id)

    # The member's next turn replays its earlier answer as history: an envelope, not 200KB.
    team.model = LeaderModel()
    member.model = _GatedMemberModel()
    member.model.calls = 1
    team.run("again", session_id=session_id)
    sizes = _member_seen_prompt_sizes(member)
    assert sizes and sizes[-1] < len(BIG) // 10


async def test_async_run_storage_matches_the_sync_copy(db):
    from agno.offload.runs import aoffload_run_for_storage, offload_run_for_storage
    from agno.run.agent import RunOutput
    from agno.run.base import RunStatus

    team = _team(db)
    team.initialize_team()
    run = RunOutput(run_id="r-async", messages=[Message(role="assistant", content=BIG)], status=RunStatus.completed)
    via_async = await aoffload_run_for_storage(team._result_store, run, session_id="offload-team-s-async")
    via_sync = offload_run_for_storage(team._result_store, run, session_id="offload-team-s-async")
    assert via_async.messages[0].content == via_sync.messages[0].content
    assert via_async.messages[0].content.startswith('<result id="res_')
    assert len(db.get_tool_results_for_session("offload-team-s-async")) == 1


async def test_async_search_does_not_block_the_event_loop(db):
    import asyncio
    import time as _time

    team = _team(db)
    session_id = _sid()
    output = await team.arun("go", session_id=session_id)
    result_id = _result_id(_tool_messages(output)[0].content)
    store = team.result_store

    # Stand in for a slow scan: the real one is CPU-bound regex work over the payload.
    real_matches = store._matches_from_content

    def slow_matches(content, pattern, context_lines):
        _time.sleep(0.3)
        return real_matches(content, pattern, context_lines)

    store._matches_from_content = slow_matches  # type: ignore[method-assign]
    ticks = []

    async def heartbeat():
        while True:
            ticks.append(_time.perf_counter())
            await asyncio.sleep(0.005)

    beat = asyncio.create_task(heartbeat())
    await asyncio.gather(*(store.asearch(result_id, r"^finding 1:") for _ in range(3)))
    beat.cancel()
    gaps = [b - a for a, b in zip(ticks, ticks[1:])]
    # The loop kept ticking while the scans ran in worker threads.
    assert gaps and max(gaps) < 0.25


def test_an_explicit_false_keeps_a_member_out_of_the_teams_store(db):
    member = _member()
    member.offload_tool_results = False
    team = Team(name="platform", id="platform", members=[member], model=LeaderModel(), db=db, offload_tool_results=True)
    team.initialize_team()
    assert member._result_store is None
    # The leader still offloads the member's answer; the member itself does not offload and gets no read-back tools.
    output = team.run("go", session_id=_sid())
    assert _tool_messages(output)[0].content.startswith('<result id="res_')
    assert member.offload_tool_results is False


def test_an_opted_out_members_history_is_never_rewritten(db):
    member = Agent(name="researcher", id="researcher", model=_SizeRecordingMemberModel(), add_history_to_context=True)
    member.offload_tool_results = False
    team = Team(
        name="platform",
        id="platform",
        members=[member],
        model=RoundRobinLeaderModel(["researcher", "researcher"]),
        db=db,
        offload_tool_results=True,
    )
    session_id = _sid()
    output = team.run("go", session_id=session_id)
    # The leader still reads envelopes.
    assert _tool_messages(output)[0].content.startswith('<result id="res_')
    # The member has no read-back tools, so its own history keeps the whole text.
    sizes = _member_seen_prompt_sizes(member)
    assert len(sizes) == 2 and sizes[1] > len(BIG)
    stored = db.get_session(session_id=session_id, session_type=SessionType.TEAM)
    member_runs = [r for r in (stored.runs or []) if getattr(r, "agent_id", None) == "researcher"]
    assert member_runs
    for run in member_runs:
        for message in run.messages or []:
            assert not str(message.content or "").startswith('<result id="res_')


def test_a_factory_member_that_opted_out_keeps_its_history_whole(db):
    # A callable member factory cannot be resolved from the storage seam, so
    # an unresolvable member is stored whole: an envelope a member cannot
    # read is never safe, plain text always is.
    member = Agent(name="researcher", id="researcher", model=MemberModel(), offload_tool_results=False)

    def factory(**kwargs):
        return [member]

    team = Team(
        name="platform",
        id="platform",
        members=factory,
        model=LeaderModel(),
        db=db,
        offload_tool_results=True,
    )
    session_id = _sid()
    output = team.run("go", session_id=session_id)
    # The leader still reads an envelope for the member's answer.
    assert _tool_messages(output)[0].content.startswith('<result id="res_')
    stored = db.get_session(session_id=session_id, session_type=SessionType.TEAM)
    member_runs = [r for r in (stored.runs or []) if getattr(r, "agent_id", None) == "researcher"]
    assert member_runs
    for run in member_runs:
        for message in run.messages or []:
            assert not str(message.content or "").startswith('<result id="res_')


# ------------------------------------------------------------------
# A member offloading on its own, inside a team that does not
# ------------------------------------------------------------------


class ToolCallingMemberModel(Model):
    """Calls one tool, then answers. The tool result is what grows."""

    def __init__(self, tool_name: str = "fetch_corpus"):
        super().__init__(id="member", name="member", provider="test")
        self.tool_name = tool_name
        self.calls = 0

    def _next(self) -> ModelResponse:
        self.calls += 1
        if self.calls == 1:
            return ModelResponse(
                role="assistant",
                tool_calls=[
                    {
                        "id": "member-call-1",
                        "type": "function",
                        "function": {"name": self.tool_name, "arguments": "{}"},
                    }
                ],
                response_usage=MessageMetrics(),
            )
        return ModelResponse(role="assistant", content="summarised", response_usage=MessageMetrics())

    def invoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return self._next()

    async def ainvoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return self._next()

    def invoke_stream(self, *args: Any, **kwargs: Any) -> Iterator[ModelResponse]:
        yield self._next()

    async def ainvoke_stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[ModelResponse]:
        yield self._next()

    def _parse_provider_response(self, response: Any, **kwargs: Any) -> ModelResponse:
        return response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response


def _offloading_member_in_a_plain_team(db) -> Team:
    """A member that offloads its own tool results, in a team that does not."""

    def fetch_corpus() -> str:
        return BIG

    member = Agent(
        name="researcher",
        id="researcher",
        model=ToolCallingMemberModel(),
        db=db,
        tools=[fetch_corpus],
        offload_tool_results=ResultStore(threshold_chars=8000),
    )
    return Team(
        name="platform",
        id="platform",
        members=[member],
        model=LeaderModel(),
        db=db,
        # The team itself does not offload. That must not disable the member.
        offload_tool_results=False,
    )


def _member_tool_messages(output) -> List[Any]:
    member_run = output.member_responses[0]
    return [m for m in (member_run.messages or []) if m.role == "tool"]


def test_a_member_offloads_its_own_tool_results_in_a_team_that_does_not(db):
    # The payoff, not the wiring: the member's own oversized tool result is a
    # short envelope in its transcript even though the team stores nothing.
    team = _offloading_member_in_a_plain_team(db)
    output = team.run("go", session_id=_sid())

    assert team._result_store is None
    tool_message = _member_tool_messages(output)[0]
    assert tool_message.tool_name == "fetch_corpus"
    assert tool_message.content.startswith('<result id="res_')
    assert BIG not in tool_message.content


def test_that_member_can_read_its_payload_back(db):
    team = _offloading_member_in_a_plain_team(db)
    output = team.run("go", session_id=_sid())

    member = team.members[0]
    result_id = _result_id(_member_tool_messages(output)[0].content)
    page = member._result_store.read(result_id, 1, 3000)
    assert page.line_count == 3000
    assert page.text.startswith("finding 1: ")


def test_a_member_that_also_compresses_still_gets_its_store(db):
    # The corner no test covered: compression on the member, its own store, and
    # a team that offloads nothing. Guards against a symmetric raise growing
    # back on this path by accident.
    def fetch_corpus() -> str:
        return BIG

    member = Agent(
        name="researcher",
        id="researcher",
        model=ToolCallingMemberModel(),
        db=db,
        tools=[fetch_corpus],
        offload_tool_results=ResultStore(threshold_chars=8000),
    )
    team = Team(name="platform", id="platform", members=[member], model=LeaderModel(), db=db)
    team.initialize_team()

    assert member._result_store is not None
    assert member._result_store.threshold_chars == 8000
