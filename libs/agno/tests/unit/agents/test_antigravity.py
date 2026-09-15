"""Unit tests for AntigravityAgent.

These exercise the adapter's request shape, session-keyed state caching,
and SSE event translation by stubbing httpx with MockTransport. They do
not hit the live Gemini Agents API.
"""

import json
import os
import tempfile
from typing import List, Optional, Tuple
from unittest.mock import patch

import httpx
import pytest

from agno.agents.antigravity import AntigravityAgent
from agno.db.sqlite import SqliteDb
from agno.run.agent import (
    RunCompletedEvent,
    RunContentEvent,
    RunStartedEvent,
    ToolCallCompletedEvent,
    ToolCallStartedEvent,
)


@pytest.fixture
def tmp_db():
    """Fresh file-backed SqliteDb per test (env/interaction state persists here now)."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        yield SqliteDb(db_file=path)
    finally:
        if os.path.exists(path):
            os.unlink(path)


def _session_env(agent: AntigravityAgent, session_id: str) -> Tuple[Optional[str], Optional[str]]:
    """Read back (env_id, previous_interaction_id) from the persisted session_data."""
    session = agent.read_or_create_session(session_id)
    data = session.session_data or {}
    return data.get(agent._ENV_KEY), data.get(agent._PREV_KEY)


def _interaction_response(env_id: str = "env-1", interaction_id: str = "int-1", text: str = "hi"):
    """Real /interactions response shape observed against the live API."""
    return {
        "id": interaction_id,
        "status": "completed",
        "outputs": [{"type": "text", "text": text}],
        "usage": {"total_tokens": 1},
        "environment_id": env_id,
        "service_tier": "default",
        "object": "interaction",
        "agent": "antigravity-preview-05-2026",
    }


def _mock_transport(handler):
    """Build an httpx MockTransport from a request->Response handler."""
    return httpx.MockTransport(handler)


def _patch_async_client(transport):
    """Patch httpx.AsyncClient to use the given MockTransport.

    Adapter constructs `httpx.AsyncClient(timeout=...)` directly; we patch
    AsyncClient at the module level inside agno.agents.antigravity.agent.
    """
    original_init = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = transport
        original_init(self, *args, **kwargs)

    return patch("httpx.AsyncClient.__init__", patched_init)


def test_first_call_sends_remote_environment_and_caches_env_id(tmp_db):
    captured: List[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content.decode()))
        return httpx.Response(200, json=_interaction_response(env_id="env-42", interaction_id="int-7"))

    agent = AntigravityAgent(
        name="Test",
        api_key="dummy",
        sources=[{"type": "inline", "content": "x", "target": "/a"}],
        db=tmp_db,
    )

    with _patch_async_client(_mock_transport(handler)):
        result = agent.run("hello", session_id="s1")

    assert result.content == "hi"
    assert len(captured) == 1
    body = captured[0]
    # First call seeds sources, NOT a cached env id
    assert body["environment"] == {"type": "remote", "sources": [{"type": "inline", "content": "x", "target": "/a"}]}
    assert body["stream"] is False
    assert "previous_interaction_id" not in body

    # State persisted to the session for next turn
    assert _session_env(agent, "s1") == ("env-42", "int-7")


def test_second_call_reuses_cached_env_id_and_previous_interaction(tmp_db):
    captured: List[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content.decode()))
        return httpx.Response(200, json=_interaction_response(env_id="env-42", interaction_id="int-9"))

    agent = AntigravityAgent(name="Test", api_key="dummy", db=tmp_db)

    # Seed prior-turn state into the persisted session.
    session = agent.read_or_create_session("s1")
    session.session_data = {agent._ENV_KEY: "env-42", agent._PREV_KEY: "int-7"}
    agent.upsert_session(session)

    with _patch_async_client(_mock_transport(handler)):
        agent.run("follow up", session_id="s1")

    body = captured[0]
    assert body["environment"] == "env-42"
    assert body["previous_interaction_id"] == "int-7"
    # And the second turn's response updated the interaction id.
    assert _session_env(agent, "s1") == ("env-42", "int-9")


def test_http_error_surfaces_as_runerror():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    agent = AntigravityAgent(name="Test", api_key="dummy")

    with _patch_async_client(_mock_transport(handler)):
        result = agent.run("hello", session_id="s1")

    # BaseExternalAgent catches the exception and builds an error RunOutput
    assert result.status.value.lower() == "error"
    assert "500" in str(result.content)


def test_extract_final_text_concatenates_text_blocks():
    data = {
        "steps": [
            {"type": "model_output", "content": [{"type": "text", "text": "Hello "}]},
            {"type": "tool_call", "content": []},
            {"type": "model_output", "content": [{"type": "text", "text": "world"}]},
        ]
    }
    assert AntigravityAgent._extract_final_text(data) == "Hello world"


def test_resolved_api_key_raises_when_missing():
    agent = AntigravityAgent(name="Test")
    with patch.dict("os.environ", {}, clear=True):
        with pytest.raises(ValueError, match="GEMINI_API_KEY"):
            agent._resolved_api_key()


def test_streaming_translates_sse_to_agno_events(tmp_db):
    """Feed a real-shape SSE response and verify content + tool events are produced.

    Frame taxonomy here matches what the live API actually emits (observed):
    interaction.start, content.delta with delta.text / delta.type=function_call /
    delta.type=function_result, interaction.complete. The API does NOT include
    environment_id anywhere in the SSE stream — see _arun_adapter_stream comments.
    """
    sse_lines = [
        'data: {"event_type": "interaction.start", "interaction": {"id": "v1_abc", "status": "in_progress", "object": "interaction", "agent": "antigravity-preview-05-2026"}}',
        'data: {"event_type": "content.delta", "index": 0, "delta": {"text": "Hello", "type": "text"}}',
        'data: {"event_type": "content.delta", "index": 0, "delta": {"text": " world", "type": "text"}}',
        'data: {"event_type": "content.delta", "index": 1, "delta": {"name": "google_search", "arguments": {"q": "agno"}, "type": "function_call", "id": "call-1"}}',
        'data: {"event_type": "content.delta", "index": 2, "delta": {"name": "google_search", "result": {"ok": true}, "type": "function_result", "tool_call_id": "call-1"}}',
        'data: {"event_type": "interaction.complete", "interaction": {"id": "v1_abc", "status": "completed", "outputs": [{"text": "Hello world", "type": "text"}]}}',
        "data: [DONE]",
    ]
    body = "\n\n".join(sse_lines).encode()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=body,
            headers={"content-type": "text/event-stream"},
        )

    agent = AntigravityAgent(name="Test", api_key="dummy", db=tmp_db)

    events: List = []
    with _patch_async_client(_mock_transport(handler)):
        for event in agent.run("hello", stream=True, session_id="s1"):
            events.append(event)

    assert isinstance(events[0], RunStartedEvent)
    assert isinstance(events[-1], RunCompletedEvent)

    middle = events[1:-1]
    content_events = [e for e in middle if isinstance(e, RunContentEvent)]
    tool_started = [e for e in middle if isinstance(e, ToolCallStartedEvent)]
    tool_completed = [e for e in middle if isinstance(e, ToolCallCompletedEvent)]

    assert len(content_events) >= 2
    assert "".join(str(e.content or "") for e in content_events) == "Hello world"
    assert len(tool_started) == 1
    assert tool_started[0].tool.tool_name == "google_search"
    assert tool_started[0].tool.tool_call_id == "call-1"
    assert len(tool_completed) == 1
    assert tool_completed[0].tool.tool_call_id == "call-1"

    # interaction_id captured from event.interaction.id (the real shape) and
    # persisted to session_data. environment_id is NOT in SSE, so it stays None.
    env_id, prev_id = _session_env(agent, "s1")
    assert prev_id == "v1_abc"
    assert env_id is None


def test_coerce_tool_args_handles_dict_string_and_none():
    assert AntigravityAgent._coerce_tool_args(None) is None
    assert AntigravityAgent._coerce_tool_args({"a": 1}) == {"a": 1}
    assert AntigravityAgent._coerce_tool_args('{"a": 1}') == {"a": 1}
    assert AntigravityAgent._coerce_tool_args("plain") == {"input": "plain"}


def test_extract_final_text_prefers_outputs_over_steps():
    """Real API uses top-level outputs[]; docs example showed steps[].content[]."""
    outputs_shape = {"outputs": [{"type": "text", "text": "from outputs"}]}
    assert AntigravityAgent._extract_final_text(outputs_shape) == "from outputs"

    steps_shape = {"steps": [{"type": "model_output", "content": [{"type": "text", "text": "from steps"}]}]}
    assert AntigravityAgent._extract_final_text(steps_shape) == "from steps"


def test_resolved_agent_uses_custom_agent_name_when_set():
    base = AntigravityAgent(name="T", api_key="dummy")
    assert base._resolved_agent() == "antigravity-preview-05-2026"

    custom = AntigravityAgent(name="T", api_key="dummy", custom_agent_name="my-bot")
    assert custom._resolved_agent() == "my-bot"


def test_run_with_custom_agent_sends_agent_name_in_body_and_omits_sources():
    """When custom_agent_name is set, sources belong on the agent definition,
    NOT on the /interactions request."""
    captured: List[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content.decode()))
        return httpx.Response(200, json=_interaction_response(text="haiku here"))

    agent = AntigravityAgent(
        name="T",
        api_key="dummy",
        custom_agent_name="my-bot",
        sources=[{"type": "inline", "content": "x", "target": "/a"}],
    )

    with _patch_async_client(_mock_transport(handler)):
        result = agent.run("hi", session_id="s1")

    assert result.content == "haiku here"
    body = captured[0]
    assert body["agent"] == "my-bot"
    # Sources should NOT be on the interaction body — they go with /agents.
    assert body["environment"] == "remote"


def test_ensure_custom_agent_posts_agent_definition():
    captured: List[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(
            {
                "method": request.method,
                "url": str(request.url),
                "body": json.loads(request.content.decode()) if request.content else {},
            }
        )
        return httpx.Response(200, json={"name": "my-bot"})

    agent = AntigravityAgent(
        name="T",
        api_key="dummy",
        custom_agent_name="my-bot",
        custom_agent_instructions="be terse",
        custom_agent_description="desc",
        sources=[{"type": "inline", "content": "x", "target": "/a"}],
    )

    # ensure_custom_agent is sync and constructs its own httpx.Client; the same
    # patch utility works because it patches both AsyncClient.__init__ behavior
    # only — patch sync httpx.Client directly here.
    from unittest.mock import patch as _patch

    original_init = httpx.Client.__init__

    def patched(self, *args, **kwargs):
        kwargs["transport"] = _mock_transport(handler)
        original_init(self, *args, **kwargs)

    with _patch("httpx.Client.__init__", patched):
        result = agent.ensure_custom_agent()

    assert result == {"name": "my-bot"}
    assert captured[0]["method"] == "POST"
    assert captured[0]["url"].endswith("/agents")
    posted = captured[0]["body"]
    assert posted["name"] == "my-bot"
    assert posted["base_agent"] == "antigravity-preview-05-2026"
    assert posted["instructions"] == "be terse"
    assert posted["description"] == "desc"
    assert posted["base_environment"] == {
        "type": "remote",
        "sources": [{"type": "inline", "content": "x", "target": "/a"}],
    }


def test_ensure_custom_agent_treats_409_as_already_exists():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(409, text="conflict: already exists")

    agent = AntigravityAgent(name="T", api_key="dummy", custom_agent_name="my-bot")
    from unittest.mock import patch as _patch

    original_init = httpx.Client.__init__

    def patched(self, *args, **kwargs):
        kwargs["transport"] = _mock_transport(handler)
        original_init(self, *args, **kwargs)

    with _patch("httpx.Client.__init__", patched):
        result = agent.ensure_custom_agent()

    assert result == {}


def test_ensure_custom_agent_requires_custom_agent_name():
    agent = AntigravityAgent(name="T", api_key="dummy")
    with pytest.raises(ValueError, match="custom_agent_name"):
        agent.ensure_custom_agent()


# ---------------------------------------------------------------------------
# from_agent_directory
# ---------------------------------------------------------------------------

from pathlib import Path  # noqa: E402


def _make_agent_dir(tmp: Path, *, with_agents_md: bool = True, system_instruction: str = "yaml-instructions") -> Path:
    (tmp / "agent.yaml").write_text(
        f"id: my-bot\nbase_agent: antigravity-preview-05-2026\ndescription: Test bot\nsystem_instruction: {system_instruction}\n"
    )
    if with_agents_md:
        (tmp / "AGENTS.md").write_text("agents-md-instructions")
    (tmp / "workspace").mkdir()
    (tmp / "workspace" / "about.txt").write_text("workspace content")
    (tmp / "workspace" / "nested").mkdir()
    (tmp / "workspace" / "nested" / "deep.txt").write_text("deep content")
    (tmp / "skills").mkdir()
    (tmp / "skills" / "haiku").mkdir()
    (tmp / "skills" / "haiku" / "SKILL.md").write_text("# Haiku skill")
    return tmp


def test_from_agent_directory_parses_yaml_and_uses_agents_md_for_instructions():
    with tempfile.TemporaryDirectory() as d:
        _make_agent_dir(Path(d))
        agent = AntigravityAgent.from_agent_directory(d, api_key="dummy", register=False)

    assert agent.custom_agent_name == "my-bot"
    assert agent.agent == "antigravity-preview-05-2026"
    assert agent.custom_agent_description == "Test bot"
    # AGENTS.md takes precedence over yaml system_instruction
    assert agent.custom_agent_instructions == "agents-md-instructions"


def test_from_agent_directory_falls_back_to_yaml_system_instruction_when_no_agents_md():
    with tempfile.TemporaryDirectory() as d:
        _make_agent_dir(Path(d), with_agents_md=False)
        agent = AntigravityAgent.from_agent_directory(d, api_key="dummy", register=False)

    assert agent.custom_agent_instructions == "yaml-instructions"


def test_from_agent_directory_builds_sources_with_correct_targets():
    with tempfile.TemporaryDirectory() as d:
        _make_agent_dir(Path(d))
        agent = AntigravityAgent.from_agent_directory(d, api_key="dummy", register=False)

    assert agent.sources is not None
    targets = {s["target"] for s in agent.sources}
    # Workspace files → root, skills files → /.agents/skills/<name>/
    assert "/about.txt" in targets
    assert "/nested/deep.txt" in targets
    assert "/.agents/skills/haiku/SKILL.md" in targets
    # All inline
    assert all(s["type"] == "inline" for s in agent.sources)


def _symlink_or_skip(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("Symlinks not supported on this system")


def test_from_agent_directory_skips_workspace_and_skill_files_that_escape_via_symlink():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        agent_dir = root / "agent"
        agent_dir.mkdir()
        _make_agent_dir(agent_dir)

        secret = root / "outside_secret.txt"
        secret.write_text("OUTSIDE_SECRET")
        _symlink_or_skip(agent_dir / "workspace" / "linked.txt", secret)
        (agent_dir / "skills" / "leaky").mkdir()
        _symlink_or_skip(agent_dir / "skills" / "leaky" / "SKILL.md", secret)

        agent = AntigravityAgent.from_agent_directory(str(agent_dir), api_key="dummy", register=False)

    sources = agent.sources or []
    targets = {s["target"] for s in sources}
    contents = "\n".join(s["content"] for s in sources)
    assert "/about.txt" in targets
    assert "/linked.txt" not in targets
    assert "/.agents/skills/leaky/SKILL.md" not in targets
    assert "OUTSIDE_SECRET" not in contents


def test_from_agent_directory_ignores_agents_md_that_escapes_via_symlink():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        agent_dir = root / "agent"
        agent_dir.mkdir()
        _make_agent_dir(agent_dir, with_agents_md=False)

        secret = root / "outside_secret.txt"
        secret.write_text("OUTSIDE_SECRET")
        _symlink_or_skip(agent_dir / "AGENTS.md", secret)

        agent = AntigravityAgent.from_agent_directory(str(agent_dir), api_key="dummy", register=False)

    # AGENTS.md escapes the agent dir, so it is not read; instructions fall back to the yaml value
    assert agent.custom_agent_instructions == "yaml-instructions"


def test_from_agent_directory_skips_source_dir_that_is_a_symlink_to_outside():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        agent_dir = root / "agent"
        agent_dir.mkdir()
        agent_dir.joinpath("agent.yaml").write_text("id: my-bot\nbase_agent: antigravity-preview-05-2026\n")
        (agent_dir / "skills" / "haiku").mkdir(parents=True)
        (agent_dir / "skills" / "haiku" / "SKILL.md").write_text("# Haiku skill")

        outside = root / "outside_dir"
        outside.mkdir()
        (outside / "secret.txt").write_text("OUTSIDE_DIR_SECRET")
        _symlink_or_skip(agent_dir / "workspace", outside)

        agent = AntigravityAgent.from_agent_directory(str(agent_dir), api_key="dummy", register=False)

    sources = agent.sources or []
    targets = {s["target"] for s in sources}
    contents = "\n".join(s["content"] for s in sources)
    assert "/secret.txt" not in targets
    assert "OUTSIDE_DIR_SECRET" not in contents
    # the real skills/ folder is unaffected
    assert "/.agents/skills/haiku/SKILL.md" in targets


def test_from_agent_directory_rejects_agent_yaml_that_escapes_via_symlink():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        agent_dir = root / "agent"
        agent_dir.mkdir()
        _make_agent_dir(agent_dir)

        outside_yaml = root / "outside.yaml"
        outside_yaml.write_text("id: evil\nbase_agent: antigravity-preview-05-2026\n")
        (agent_dir / "agent.yaml").unlink()
        _symlink_or_skip(agent_dir / "agent.yaml", outside_yaml)

        with pytest.raises(FileNotFoundError):
            AntigravityAgent.from_agent_directory(str(agent_dir), api_key="dummy", register=False)


def test_from_agent_directory_requires_id_and_base_agent():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d)
        (p / "agent.yaml").write_text("description: missing required keys\n")
        with pytest.raises(ValueError, match="id.*base_agent"):
            AntigravityAgent.from_agent_directory(d, api_key="dummy")


def test_from_agent_directory_skips_files_over_75kb():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d)
        (p / "agent.yaml").write_text("id: my-bot\nbase_agent: antigravity-preview-05-2026\n")
        (p / "workspace").mkdir()
        (p / "workspace" / "small.txt").write_text("ok")
        (p / "workspace" / "big.txt").write_text("x" * (80 * 1024))

        agent = AntigravityAgent.from_agent_directory(d, api_key="dummy", register=False)

    targets = {s["target"] for s in agent.sources or []}
    assert "/small.txt" in targets
    assert "/big.txt" not in targets


def test_from_agent_directory_skips_binary_files():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d)
        (p / "agent.yaml").write_text("id: my-bot\nbase_agent: antigravity-preview-05-2026\n")
        (p / "workspace").mkdir()
        (p / "workspace" / "ok.txt").write_text("text")
        (p / "workspace" / "binary.bin").write_bytes(b"\x00\x01\x02\xff\xfe")

        agent = AntigravityAgent.from_agent_directory(d, api_key="dummy", register=False)

    targets = {s["target"] for s in agent.sources or []}
    assert "/ok.txt" in targets
    assert "/binary.bin" not in targets


def test_from_agent_directory_missing_directory_raises():
    with pytest.raises(FileNotFoundError, match="agent directory not found"):
        AntigravityAgent.from_agent_directory("/does/not/exist", api_key="dummy")


def test_from_agent_directory_missing_yaml_raises():
    with tempfile.TemporaryDirectory() as d:
        with pytest.raises(FileNotFoundError, match="agent.yaml"):
            AntigravityAgent.from_agent_directory(d, api_key="dummy")


def test_from_agent_directory_register_true_calls_post_agents():
    """When register=True (default), the classmethod should POST to /agents before returning."""
    captured: List[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(
            {"method": request.method, "url": str(request.url), "body": json.loads(request.content.decode())}
        )
        return httpx.Response(200, json={"name": "my-bot"})

    with tempfile.TemporaryDirectory() as d:
        _make_agent_dir(Path(d))

        original_init = httpx.Client.__init__

        def patched(self, *args, **kwargs):
            kwargs["transport"] = _mock_transport(handler)
            original_init(self, *args, **kwargs)

        with patch("httpx.Client.__init__", patched):
            AntigravityAgent.from_agent_directory(d, api_key="dummy")  # register=True is the default

    assert len(captured) == 1
    assert captured[0]["method"] == "POST"
    assert captured[0]["url"].endswith("/agents")
    assert captured[0]["body"]["name"] == "my-bot"


# ---------------------------------------------------------------------------
# download_environment_snapshot
# ---------------------------------------------------------------------------


def test_download_environment_snapshot_writes_bytes_and_uses_cached_env_id(tmp_db):
    snapshot_body = b"FAKE_TAR_DATA_" + b"x" * 100

    def handler(request: httpx.Request) -> httpx.Response:
        assert "/files/environment-env-99:download" in str(request.url)
        return httpx.Response(200, content=snapshot_body)

    agent = AntigravityAgent(name="T", api_key="dummy", db=tmp_db)
    # Seed the env id into the persisted session, as a prior turn would have.
    session = agent.read_or_create_session("s1")
    session.session_data = {agent._ENV_KEY: "env-99"}
    agent.upsert_session(session)

    original_init = httpx.Client.__init__

    def patched(self, *args, **kwargs):
        kwargs["transport"] = _mock_transport(handler)
        original_init(self, *args, **kwargs)

    with tempfile.NamedTemporaryFile(suffix=".tar", delete=False) as f:
        out_path = f.name
    try:
        with patch("httpx.Client.__init__", patched):
            written = agent.download_environment_snapshot(out_path, session_id="s1")
        assert written == len(snapshot_body)
        with open(out_path, "rb") as fh:
            assert fh.read() == snapshot_body
    finally:
        import os

        os.unlink(out_path)


def test_download_environment_snapshot_requires_an_env_id():
    agent = AntigravityAgent(name="T", api_key="dummy")
    with pytest.raises(ValueError, match="environment_id"):
        agent.download_environment_snapshot("/tmp/x.tar")


def test_no_db_degrades_gracefully_no_cross_turn_reuse():
    """Without a db there is no session persistence: every turn provisions a
    fresh sandbox ('remote') and never sends previous_interaction_id. Must not error."""
    captured: List[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content.decode()))
        return httpx.Response(200, json=_interaction_response(env_id="env-1", interaction_id="int-1"))

    agent = AntigravityAgent(name="T", api_key="dummy")  # no db

    with _patch_async_client(_mock_transport(handler)):
        agent.run("turn one", session_id="s1")
        agent.run("turn two", session_id="s1")

    # Both turns provisioned fresh — no cached env id, no interaction linkage.
    for body in captured:
        assert body["environment"] == "remote"
        assert "previous_interaction_id" not in body
