from typing import List

import pytest

from agno.agent import Agent
from agno.agent import _default_tools as agent_default_tools
from agno.models.message import Message
from agno.run.agent import RunOutput
from agno.run.team import TeamRunOutput
from agno.session import AgentSession, TeamSession
from agno.team import _default_tools
from agno.team.team import Team

TURNS = [
    ("The staging database is called lumen-stage-7.\nKeep the budget under 4,200 dollars.", "Noted."),
    ("Who reviews replies?", "Priya reviews every reply.\nNothing is sent before that."),
    ("Draft the note.", "Here is the note."),
]


def _team_run(index: int, question: str, answer: str) -> TeamRunOutput:
    return TeamRunOutput(
        run_id=f"run-{index}",
        session_id="s1",
        team_id="team-1",
        messages=[
            Message(role="system", content="You lead the team. SECRET-SYSTEM"),
            Message(role="user", content=question),
            Message(
                role="assistant",
                content=None,
                tool_calls=[
                    {"id": "call-1", "type": "function", "function": {"name": "delegate_task", "arguments": "{}"}}
                ],
            ),
            Message(role="tool", content="tool output lumen-stage-7", tool_call_id="call-1"),
            Message(role="assistant", content=answer),
        ],
    )


def _member_run(index: int) -> RunOutput:
    return RunOutput(
        run_id=f"member-run-{index}",
        parent_run_id=f"run-{index}",
        session_id="s1",
        agent_id="member-1",
        messages=[Message(role="user", content="task"), Message(role="assistant", content="member lumen-stage-7")],
    )


def _session() -> TeamSession:
    runs: List = []
    for index, (question, answer) in enumerate(TURNS, start=1):
        runs += [_team_run(index, question, answer), _member_run(index)]
    return TeamSession(session_id="s1", team_id="team-1", runs=runs)


@pytest.fixture
def team() -> Team:
    return Team(id="team-1", members=[])


async def _search(team: Team, session: TeamSession, async_mode: bool, **kwargs) -> str:
    tool = _default_tools._search_chat_history_function(team, session, async_mode=async_mode)
    assert tool.name == "search_chat_history"
    result = tool.entrypoint(**kwargs)  # type: ignore[misc]
    return await result if async_mode else result


@pytest.mark.asyncio
@pytest.mark.parametrize("async_mode", [False, True])
async def test_a_match_names_its_turn_and_who_said_it(team, async_mode):
    found = await _search(team, _session(), async_mode, pattern="LUMEN-STAGE", context_lines=0)
    lines = found.splitlines()
    assert lines[0] == "3 turns are stored, numbered from 1 at the start of the conversation."
    # Only the person's message matches: tool results, member runs and the system prompt are not searched.
    assert lines[1:] == ["[turn 1 user] The staging database is called lumen-stage-7."]


@pytest.mark.asyncio
@pytest.mark.parametrize("async_mode", [False, True])
async def test_context_lines_and_alternatives(team, async_mode):
    found = await _search(team, _session(), async_mode, pattern="budget|Priya", context_lines=1)
    assert "[turn 1 user] Keep the budget under 4,200 dollars." in found
    assert "[turn 2 assistant] Priya reviews every reply." in found
    # One line of context either side of each match.
    assert "[turn 1 assistant] Noted." in found
    assert "[turn 2 assistant] Nothing is sent before that." in found
    assert "Draft the note." not in found


@pytest.mark.asyncio
@pytest.mark.parametrize("async_mode", [False, True])
async def test_no_match_and_no_turns_say_so(team, async_mode):
    assert await _search(team, _session(), async_mode, pattern="SECRET-SYSTEM") == (
        "No earlier turn matches 'SECRET-SYSTEM'. 3 turns are stored."
    )
    empty = TeamSession(session_id="s1", team_id="team-1")
    assert await _search(team, empty, async_mode, pattern="x") == "This conversation has no earlier turns stored."


def test_output_is_bounded_like_the_compacted_history_search(team):
    from agno.compaction.compaction import _SEARCH_LINE_CHARS, _SEARCH_OUTPUT_CHARS

    long_line = "padding " * 200 + "needle " + "padding " * 200
    runs = [_team_run(i, f"needle {i} " + long_line, "ok") for i in range(1, 80)]
    session = TeamSession(session_id="s1", team_id="team-1", runs=runs)
    found = _default_tools._search_chat_history_function(team, session).entrypoint(pattern="needle")  # type: ignore[misc]
    assert len(found) < _SEARCH_OUTPUT_CHARS + 200
    assert all(len(line) < _SEARCH_LINE_CHARS + 50 for line in found.splitlines())
    assert found.endswith("... more matches than fit; narrow the search.")


def test_a_pattern_is_literal_text_not_a_regular_expression(team):
    assert "No earlier turn matches" in _default_tools._search_chat_history_function(team, _session()).entrypoint(  # type: ignore[misc]
        pattern="lumen.*7"
    )


def test_agent_tool_searches_its_session_the_same_way():
    session = AgentSession(
        session_id="s1",
        agent_id="agent-1",
        runs=[
            RunOutput(
                run_id="r1",
                session_id="s1",
                agent_id="agent-1",
                messages=[
                    Message(role="user", content="The file is docs/guide.md"),
                    Message(role="assistant", content="Got it."),
                ],
            )
        ],
    )
    search = agent_default_tools.search_chat_history_function(Agent(id="agent-1"), session)
    assert search(pattern="guide.md", context_lines=0).splitlines()[1] == "[turn 1 user] The file is docs/guide.md"


def test_a_team_that_reads_its_chat_history_gets_the_search_tool():
    from agno.run import RunContext
    from agno.team import _tools

    team = Team(id="team-1", members=[], read_chat_history=True)
    run_context = RunContext(run_id="r", session_id="s1")
    tools = _tools._determine_tools_for_model(
        team,
        model=team.model or __import__("agno.models.openai", fromlist=["OpenAIResponses"]).OpenAIResponses(id="x"),
        run_response=TeamRunOutput(run_id="r", session_id="s1", team_id="team-1"),
        run_context=run_context,
        team_run_context={},
        session=_session(),
        user_id="u",
    )
    names = [tool.name if hasattr(tool, "name") else tool.get("name") for tool in tools]
    assert "get_chat_history" in names and "search_chat_history" in names


def _plain_session(turns: List) -> TeamSession:
    runs = [_team_run(index, question, answer) for index, (question, answer) in enumerate(turns, start=1)]
    return TeamSession(session_id="s1", team_id="team-1", runs=runs)


def test_a_number_matches_what_was_said_not_the_turn_labels(team):
    turns = [("Next question.", "Done.")] * 16
    turns[2] = ("Keep the budget at 15 dollars.", "Done.")
    search = _default_tools._search_chat_history_function(team, _plain_session(turns)).entrypoint
    found = search(pattern="15", context_lines=0)  # type: ignore[misc]
    assert found.splitlines()[1:] == ["[turn 3 user] Keep the budget at 15 dollars."]


def test_a_role_word_matches_what_was_said_not_every_label(team):
    turns = [("Next question.", "Done.")] * 5
    turns[1] = ("How many seats does each user get?", "Done.")
    search = _default_tools._search_chat_history_function(team, _plain_session(turns)).entrypoint
    assert search(pattern="user", context_lines=0).splitlines()[1:] == [  # type: ignore[misc]
        "[turn 2 user] How many seats does each user get?"
    ]
    assert search(pattern="turn|assistant", context_lines=0).startswith("No earlier turn matches")  # type: ignore[misc]


def test_a_match_deep_in_a_long_line_keeps_its_turn(team):
    reply = "Background on the rollout. " * 40 + "The deploy path is /srv/app/blue."
    turns = [("Next question.", "Done."), ("Where does it deploy?", reply)]
    search = _default_tools._search_chat_history_function(team, _plain_session(turns)).entrypoint
    line = search(pattern="/srv/app", context_lines=0).splitlines()[1]  # type: ignore[misc]
    assert line.startswith("[turn 2 assistant] ")
    assert "/srv/app/blue" in line


async def _agent_tool_names(agent: Agent, async_mode: bool) -> List[str]:
    from agno.agent import _tools
    from agno.run import RunContext

    kwargs = dict(
        run_response=RunOutput(run_id="r", session_id="s1"),
        run_context=RunContext(run_id="r", session_id="s1"),
        session=AgentSession(session_id="s1"),
    )
    tools = await _tools.aget_tools(agent, **kwargs) if async_mode else _tools.get_tools(agent, **kwargs)  # type: ignore[arg-type]
    return [getattr(tool, "__name__", getattr(tool, "name", "")) for tool in tools]


@pytest.mark.asyncio
@pytest.mark.parametrize("async_mode", [False, True])
async def test_an_agent_that_searches_its_compacted_history_gets_one_search_tool(tmp_path, async_mode):
    from agno.compaction import Compaction
    from agno.compaction.types import CompactionRecord
    from agno.db.sqlite import SqliteDb
    from agno.models.openai import OpenAIResponses

    db = SqliteDb(db_file=str(tmp_path / "agent.db"))
    compaction = Compaction(search_compacted_messages=True)
    compaction.archive_for("s1", db).write(  # type: ignore[union-attr]
        CompactionRecord(messages_compacted=1, summary="s", first_kept_message_id="m1", id="c1"),
        [Message(role="user", content="archived")],
    )
    model = OpenAIResponses(id="gpt-5.6-luna")
    agent = Agent(model=model, db=db, compaction=compaction, read_chat_history=True)
    names = await _agent_tool_names(agent, async_mode)
    assert "search_compacted_history" in names and "get_chat_history" in names
    assert "search_chat_history" not in names


@pytest.mark.asyncio
@pytest.mark.parametrize("async_mode", [False, True])
async def test_an_agent_without_a_compacted_history_search_gets_the_chat_history_search(tmp_path, async_mode):
    from agno.compaction import Compaction
    from agno.db.sqlite import SqliteDb
    from agno.models.openai import OpenAIResponses

    model = OpenAIResponses(id="gpt-5.6-luna")
    db = SqliteDb(db_file=str(tmp_path / "agent.db"))
    for agent in (
        Agent(model=model, db=db, read_chat_history=True),
        Agent(model=model, db=db, compaction=Compaction(search_compacted_messages=False), read_chat_history=True),
        # Before the first fold num_history_runs can still drop turns, and nothing is archived yet.
        Agent(model=model, db=db, compaction=True, read_chat_history=True),
        # Without a db the compacted history has nowhere to live, so it can never be searched.
        Agent(model=model, compaction=Compaction(search_compacted_messages=True), read_chat_history=True),
    ):
        names = await _agent_tool_names(agent, async_mode)
        assert "search_chat_history" in names and "search_compacted_history" not in names
