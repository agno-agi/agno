"""Integration tests for UpstashBoxTools against the real Upstash Box API.

Requires UPSTASH_BOX_API_KEY (and optionally UPSTASH_BOX_BASE_URL). The end-to-end
agent tests also need a model key: OPENROUTER_API_KEY or OPENAI_API_KEY.

Every box these tests create carries a label unique to this test run, and the
module teardown deletes everything with that label, so a failing test cannot leave
boxes behind and boxes created outside the run are never touched.
"""

import asyncio
import os
import time
import urllib.request
import uuid
from typing import Iterator, List

import pytest

pytest.importorskip("upstash_box")

from upstash_box import AsyncBox, Box  # noqa: E402

from agno.agent import Agent  # noqa: E402
from agno.db.sqlite import SqliteDb  # noqa: E402
from agno.run import RunContext  # noqa: E402
from agno.run.agent import RunOutput  # noqa: E402
from agno.team import Team  # noqa: E402
from agno.tools.upstash_box import SESSION_STATE_BOX_ID, UpstashBoxTools  # noqa: E402

pytestmark = pytest.mark.skipif(not os.environ.get("UPSTASH_BOX_API_KEY"), reason="UPSTASH_BOX_API_KEY not set")

RUN_LABEL = f"agno-it-{uuid.uuid4().hex[:8]}"


@pytest.fixture(scope="module", autouse=True)
def delete_test_boxes() -> Iterator[None]:
    """Delete every box created by this test run, whatever the tests did."""
    yield
    for listed in Box.list(label=RUN_LABEL):
        try:
            box = Box.get(listed.id)
            box.delete()
            box.close()
        except Exception:
            pass


def make_tools(**kwargs) -> UpstashBoxTools:
    return UpstashBoxTools(labels=[RUN_LABEL], **kwargs)


def run_context(session_id: str, **state) -> RunContext:
    return RunContext(run_id=uuid.uuid4().hex, session_id=session_id, session_state=dict(state))


def new_session() -> str:
    return f"it-{uuid.uuid4().hex[:8]}"


def box_exists(box_id: str) -> bool:
    return any(b.id == box_id for b in Box.list(label=RUN_LABEL))


def delete_externally(box_id: str) -> None:
    """Delete a box outside the toolkit, as another process or the console would."""
    box = Box.get(box_id)
    box.delete()
    box.close()


# ---------------------------------------------------------------------------
# Toolkit against the real API (no LLM)
# ---------------------------------------------------------------------------
def test_code_shell_and_file_tools_share_one_box():
    tools = make_tools()
    ctx = run_context(new_session())
    try:
        result = tools.run_python_code(ctx, "import sys\nprint(sys.version_info.major, 6 * 7)")
        assert "3 42" in result and "Exit code: 0" in result

        assert tools.create_file(ctx, "proj/app.py", "print('from file')") == "File written: proj/app.py"
        assert tools.read_file(ctx, "proj/app.py") == "print('from file')"
        assert "from file" in tools.run_command(ctx, "python3 proj/app.py")
        assert "/workspace/home" in tools.run_command(ctx, "pwd")
        assert "file  app.py" in tools.list_files(ctx, "proj")
        assert "dir   proj/" in tools.list_files(ctx)

        failing = tools.run_command(ctx, "ls /does-not-exist")
        assert "Exit code: 0" not in failing and "STDERR" in failing
        assert "file not found" in tools.read_file(ctx, "missing.txt")

        assert tools.delete_file(ctx, "proj") == "Deleted: proj"
        assert "proj" not in tools.list_files(ctx)
        assert SESSION_STATE_BOX_ID in ctx.session_state
    finally:
        tools.shutdown_box(ctx)


def test_box_info_listing_and_shutdown():
    tools = make_tools()
    ctx = run_context(new_session())
    tools.run_command(ctx, "true")
    box_id = ctx.session_state[SESSION_STATE_BOX_ID]

    assert f'"id": "{box_id}"' in tools.get_box_info(ctx)
    assert box_id in tools.list_boxes()

    assert tools.shutdown_box(ctx) == f"Box {box_id} shut down."
    assert ctx.session_state == {}
    assert not box_exists(box_id)
    assert tools.shutdown_box(ctx) == "No active box to shut down."


def test_command_timeout_stops_long_commands():
    tools = make_tools(command_timeout=5)
    ctx = run_context(new_session())
    try:
        tools.run_command(ctx, "true")  # create the box outside the timed calls
        started = time.monotonic()
        assert tools.run_command(ctx, "sleep 30") == "Exit code: 124"
        assert tools.run_python_code(ctx, "import time\ntime.sleep(30)") == "Exit code: 124"
        assert time.monotonic() - started < 25
        assert "Exit code: 0" in tools.run_python_code(ctx, "print('quick')")
    finally:
        tools.shutdown_box(ctx)


def test_public_url_serves_a_port():
    tools = make_tools()
    ctx = run_context(new_session())
    try:
        tools.create_file(ctx, "site/index.html", "hello from box")
        tools.run_command(ctx, "cd site && nohup python3 -m http.server 8000 >/dev/null 2>&1 &")
        time.sleep(2)
        url = tools.get_public_url(ctx, 8000)
        assert url.startswith("https://")
        with urllib.request.urlopen(url, timeout=60) as response:
            assert response.status == 200
            assert "hello from box" in response.read().decode()
    finally:
        tools.shutdown_box(ctx)


def test_pause_resume_and_snapshot():
    tools = make_tools(all=True)
    ctx = run_context(new_session())
    snapshot_id = None
    try:
        tools.create_file(ctx, "keep.txt", "kept")
        assert tools.pause_box(ctx).endswith("paused.")
        # The next tool call resumes the paused box automatically.
        assert tools.read_file(ctx, "keep.txt") == "kept"
        assert tools.resume_box(ctx).endswith("resumed.")
        snapshot = tools.snapshot_box(ctx, "agno-it")
        assert '"status": "ready"' in snapshot
        snapshot_id = snapshot.split('"id": "')[1].split('"')[0]
    finally:
        tools.shutdown_box(ctx)
        if snapshot_id:
            Box.delete_snapshots(snapshot_ids=snapshot_id)


def test_sessions_get_separate_boxes():
    tools = make_tools()
    one, two = run_context(new_session()), run_context(new_session())
    try:
        tools.create_file(one, "secret.txt", "session one")
        assert "file not found" in tools.read_file(two, "secret.txt")
        assert one.session_state[SESSION_STATE_BOX_ID] != two.session_state[SESSION_STATE_BOX_ID]
    finally:
        tools.shutdown_box(one)
        tools.shutdown_box(two)


def test_box_deleted_elsewhere_is_replaced():
    tools = make_tools()
    ctx = run_context(new_session())
    try:
        tools.run_command(ctx, "true")
        old = ctx.session_state[SESSION_STATE_BOX_ID]
        delete_externally(old)
        assert "recovered" in tools.run_command(ctx, "echo recovered")
        assert ctx.session_state[SESSION_STATE_BOX_ID] != old
    finally:
        tools.shutdown_box(ctx)


def test_lifecycle_tools_never_create_a_box_for_a_deleted_saved_id():
    tools = make_tools()
    seed_ctx = run_context(new_session())
    tools.run_command(seed_ctx, "true")
    deleted = seed_ctx.session_state[SESSION_STATE_BOX_ID]
    tools.shutdown_box(seed_ctx)

    ctx = run_context(new_session(), **{SESSION_STATE_BOX_ID: deleted})
    fresh_tools = make_tools(all=True)
    assert "no longer exists" in fresh_tools.pause_box(ctx)
    assert "no longer exists" in asyncio.run(
        fresh_tools.asnapshot_box(run_context(new_session(), **{SESSION_STATE_BOX_ID: deleted}), "x")
    )
    assert ctx.session_state == {}
    assert all(b.id != deleted for b in Box.list(label=RUN_LABEL))


def test_explicit_box_id_reconnects_to_an_existing_box():
    box = Box.create(runtime="python", labels=[RUN_LABEL])
    try:
        box.files.write(path="existing.txt", content="pre-existing")
        tools = make_tools(box_id=box.id)
        assert tools.read_file(run_context(new_session()), "existing.txt") == "pre-existing"
    finally:
        box.delete()
        box.close()


def test_async_tools_across_event_loops_and_with_sync_tools():
    tools = make_tools()
    ctx = run_context(new_session())
    try:
        assert "one" in asyncio.run(tools.arun_command(ctx, "echo one"))
        # A second asyncio.run() is a new event loop; it must reconnect, not fail.
        assert "two" in asyncio.run(tools.arun_command(ctx, "echo two"))
        asyncio.run(tools.acreate_file(ctx, "shared.txt", "async wrote this"))
        assert tools.read_file(ctx, "shared.txt") == "async wrote this"
        assert asyncio.run(tools.aread_file(ctx, "shared.txt")) == "async wrote this"
    finally:
        asyncio.run(tools.ashutdown_box(ctx))
    assert ctx.session_state == {}


async def test_concurrent_async_calls_create_one_box():
    tools = make_tools()
    ctx = run_context(new_session())
    try:
        await asyncio.gather(*(tools.acreate_file(ctx, f"f{i}.txt", str(i)) for i in range(3)))
        listing = await tools.alist_files(ctx)
        assert all(f"f{i}.txt" in listing for i in range(3))
        assert len([b for b in Box.list(label=RUN_LABEL) if b.id == ctx.session_state[SESSION_STATE_BOX_ID]]) == 1
    finally:
        await tools.ashutdown_box(ctx)


async def test_concurrent_shutdowns_of_a_shared_box():
    box = await AsyncBox.create(runtime="python", labels=[RUN_LABEL])
    await box.aclose()
    tools = make_tools(box_id=box.id)
    one, two = run_context(new_session()), run_context(new_session())
    await tools.arun_command(one, "true")
    await tools.arun_command(two, "true")
    results = await asyncio.gather(tools.ashutdown_box(one), tools.ashutdown_box(two))
    assert results == [f"Box {box.id} shut down."] * 2
    assert one.session_state == {} and two.session_state == {}


# ---------------------------------------------------------------------------
# End-to-end: agno agents and teams with a real model
# ---------------------------------------------------------------------------
def _model():
    if os.environ.get("OPENROUTER_API_KEY"):
        from agno.models.openrouter import OpenRouter

        return OpenRouter(id="openai/gpt-5.6-luna")
    if os.environ.get("OPENAI_API_KEY"):
        from agno.models.openai import OpenAIResponses

        return OpenAIResponses(id="gpt-5.6-luna")
    pytest.skip("OPENROUTER_API_KEY or OPENAI_API_KEY not set")


INSTRUCTIONS = [
    "You run code in an Upstash Box using your tools.",
    "Always execute code with your tools and report the real output; never guess results.",
]


def _tool_names(run: RunOutput) -> List[str]:
    return [t.tool_name for t in (run.tools or []) if t.tool_name]


def _cleanup(tools: UpstashBoxTools, session_state) -> None:
    box_id = (session_state or {}).get(SESSION_STATE_BOX_ID)
    if box_id:
        tools.shutdown_box(run_context("cleanup", **{SESSION_STATE_BOX_ID: box_id}))


def test_agent_runs_code_and_reports_real_output():
    tools = make_tools()
    agent = Agent(model=_model(), tools=[tools], instructions=INSTRUCTIONS)
    run = agent.run("Compute the sum of the squares of the integers from 1 to 20 by running Python code.")
    try:
        assert {"run_python_code", "run_command"} & set(_tool_names(run))
        assert "2870" in run.content
        assert run.session_state and run.session_state.get(SESSION_STATE_BOX_ID)
    finally:
        _cleanup(tools, run.session_state)


async def test_agent_arun_uses_file_tools():
    tools = make_tools()
    agent = Agent(model=_model(), tools=[tools], instructions=INSTRUCTIONS)
    run = await agent.arun(
        "Create a file named stats.py that prints the median of [3, 1, 4, 1, 5, 9, 2, 6], "
        "run it, and tell me the printed value."
    )
    try:
        names = _tool_names(run)
        assert "create_file" in names
        assert {"run_command", "run_python_code"} & set(names)
        assert "3.5" in run.content
    finally:
        _cleanup(tools, run.session_state)


def test_agent_streaming_run_calls_tools():
    tools = make_tools()
    agent = Agent(model=_model(), tools=[tools], instructions=INSTRUCTIONS)
    chunks = list(
        agent.run(
            "Run the shell command `echo streamed-$((6*7))` and tell me its output.",
            stream=True,
            stream_events=True,
            yield_run_output=True,
        )
    )
    run = next(c for c in chunks if isinstance(c, RunOutput))
    try:
        assert any(type(c).__name__ == "ToolCallCompletedEvent" for c in chunks)
        assert "run_command" in _tool_names(run)
        assert "streamed-42" in run.content
    finally:
        _cleanup(tools, run.session_state)


def test_session_resumes_the_same_box_from_the_database(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "agno.db"))
    session_id = new_session()
    first_tools = make_tools()
    first = Agent(model=_model(), tools=[first_tools], db=db, session_id=session_id, instructions=INSTRUCTIONS)
    run_one = first.run("Create a file named note.txt containing exactly: persisted-box-check")
    box_id = run_one.session_state[SESSION_STATE_BOX_ID]
    second_tools = make_tools()
    try:
        # A new agent and toolkit, as in a new process, resume the session from the db.
        second = Agent(model=_model(), tools=[second_tools], db=db, session_id=session_id, instructions=INSTRUCTIONS)
        run_two = second.run("Read the file note.txt and tell me exactly what it contains.")
        assert "persisted-box-check" in run_two.content
        assert run_two.session_state[SESSION_STATE_BOX_ID] == box_id
    finally:
        _cleanup(second_tools, {SESSION_STATE_BOX_ID: box_id})


def test_separate_sessions_do_not_share_files():
    tools = make_tools()
    agent = Agent(model=_model(), tools=[tools], instructions=INSTRUCTIONS)
    run_a = agent.run("Create a file named private.txt containing: session-a-only", session_id=new_session())
    run_b = agent.run(
        "Check whether a file named private.txt exists in /workspace/home by listing that directory. "
        "Answer EXISTS or MISSING.",
        session_id=new_session(),
    )
    try:
        assert run_a.session_state[SESSION_STATE_BOX_ID] != run_b.session_state[SESSION_STATE_BOX_ID]
        assert "MISSING" in run_b.content.upper()
    finally:
        _cleanup(tools, run_a.session_state)
        _cleanup(tools, run_b.session_state)


def test_team_member_runs_code_in_a_box():
    tools = make_tools()
    coder = Agent(name="Coder", role="Writes and runs code", model=_model(), tools=[tools], instructions=INSTRUCTIONS)
    team = Team(
        name="Analysis Team",
        model=_model(),
        members=[coder],
        instructions=["Delegate any computation to the Coder and report its real result."],
    )
    run = team.run("Ask the Coder to compute 2**20 by running Python code, then report the number.")
    # The member's box is removed by the module teardown, which deletes this run's label.
    assert "1048576" in run.content.replace(",", "")
