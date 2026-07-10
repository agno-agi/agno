"""Unit tests for AntigravityTools."""

import json
from typing import List
from unittest.mock import MagicMock, patch

import httpx
import pytest

from agno.tools.antigravity import AntigravityTools


def _interaction_response(env_id: str = "env-1", interaction_id: str = "int-1", text: str = "done"):
    return {
        "id": interaction_id,
        "status": "completed",
        "environment_id": env_id,
        "steps": [{"type": "model_output", "content": [{"type": "text", "text": text}]}],
    }


def _patch_sync_client(transport):
    original_init = httpx.Client.__init__

    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = transport
        original_init(self, *args, **kwargs)

    return patch("httpx.Client.__init__", patched_init)


def test_init_requires_api_key():
    with patch.dict("os.environ", {}, clear=True):
        with pytest.raises(ValueError, match="GEMINI_API_KEY"):
            AntigravityTools()


def test_init_registers_expected_tools():
    tools = AntigravityTools(api_key="dummy")
    tool_names = {f.name for f in tools.functions.values()}
    assert tool_names == {
        "run_antigravity_task",
        "run_custom_antigravity_agent",
        "create_custom_antigravity_agent",
        "update_custom_antigravity_agent",
        "get_custom_antigravity_agent",
        "list_antigravity_agents",
        "list_antigravity_agent_versions",
        "delete_antigravity_agent",
        "download_antigravity_environment_snapshot",
    }


def test_run_antigravity_task_first_call_stores_env_id_in_session_state():
    captured: List[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content.decode()))
        return httpx.Response(200, json=_interaction_response(env_id="env-99", interaction_id="int-1"))

    tools = AntigravityTools(api_key="dummy")
    fake_agent = MagicMock()
    fake_agent.session_state = {}

    with _patch_sync_client(httpx.MockTransport(handler)):
        result = tools.run_antigravity_task(fake_agent, "do a thing")

    assert result == "done"
    assert captured[0]["environment"] == "remote"
    assert fake_agent.session_state["antigravity_env_id"] == "env-99"
    assert fake_agent.session_state["antigravity_previous_interaction_id"] == "int-1"


def test_run_antigravity_task_reuses_cached_env_on_subsequent_call():
    captured: List[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content.decode()))
        return httpx.Response(200, json=_interaction_response(env_id="env-99", interaction_id="int-2"))

    tools = AntigravityTools(api_key="dummy")
    fake_agent = MagicMock()
    fake_agent.session_state = {
        "antigravity_env_id": "env-99",
        "antigravity_previous_interaction_id": "int-1",
    }

    with _patch_sync_client(httpx.MockTransport(handler)):
        tools.run_antigravity_task(fake_agent, "follow up")

    body = captured[0]
    assert body["environment"] == "env-99"
    assert body["previous_interaction_id"] == "int-1"


def test_run_antigravity_task_returns_error_json_on_http_failure():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    tools = AntigravityTools(api_key="dummy")
    fake_agent = MagicMock()
    fake_agent.session_state = {}

    with _patch_sync_client(httpx.MockTransport(handler)):
        result = tools.run_antigravity_task(fake_agent, "hi")

    parsed = json.loads(result)
    assert parsed["status"] == "error"
    assert "500" in parsed["message"]


def test_create_custom_antigravity_agent_posts_to_agents_endpoint():
    captured: List[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"name": "test-agent"})

    tools = AntigravityTools(api_key="dummy")

    with _patch_sync_client(httpx.MockTransport(handler)):
        result = tools.create_custom_antigravity_agent(
            name="test-agent",
            instructions="be helpful",
            sources=[{"type": "inline", "content": "x", "target": "/a"}],
        )

    assert json.loads(result) == {"name": "test-agent"}
    assert captured[0].url.path.endswith("/agents")
    body = json.loads(captured[0].content.decode())
    assert body["name"] == "test-agent"
    assert body["instructions"] == "be helpful"
    assert body["base_environment"] == {
        "type": "remote",
        "sources": [{"type": "inline", "content": "x", "target": "/a"}],
    }


def test_delete_antigravity_agent_calls_delete():
    captured: List[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(204)

    tools = AntigravityTools(api_key="dummy")

    with _patch_sync_client(httpx.MockTransport(handler)):
        result = tools.delete_antigravity_agent("test-agent")

    assert json.loads(result) == {"status": "ok", "deleted": "test-agent"}
    assert captured[0].method == "DELETE"
    assert captured[0].url.path.endswith("/agents/test-agent")


def test_run_custom_antigravity_agent_sends_custom_name_in_body():
    captured: List[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content.decode()))
        return httpx.Response(
            200,
            json={
                "id": "int-1",
                "status": "completed",
                "outputs": [{"type": "text", "text": "haiku"}],
                "environment_id": "env-1",
            },
        )

    tools = AntigravityTools(api_key="dummy")
    fake_agent = MagicMock()
    fake_agent.session_state = {}

    with _patch_sync_client(httpx.MockTransport(handler)):
        result = tools.run_custom_antigravity_agent(fake_agent, "my-bot", "write a haiku")

    assert result == "haiku"
    body = captured[0]
    assert body["agent"] == "my-bot"
    assert body["input"] == [{"type": "text", "text": "write a haiku"}]
    assert body["stream"] is False
    # State is keyed per-custom-agent so different named agents don't share envs.
    assert fake_agent.session_state["antigravity_env_id__my-bot"] == "env-1"
    assert fake_agent.session_state["antigravity_previous_interaction_id__my-bot"] == "int-1"


def test_run_custom_antigravity_agent_reuses_per_agent_session_state():
    captured: List[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content.decode()))
        return httpx.Response(
            200,
            json={"id": "int-2", "status": "completed", "outputs": [{"type": "text", "text": "ok"}]},
        )

    tools = AntigravityTools(api_key="dummy")
    fake_agent = MagicMock()
    fake_agent.session_state = {
        "antigravity_env_id__my-bot": "env-1",
        "antigravity_previous_interaction_id__my-bot": "int-1",
    }

    with _patch_sync_client(httpx.MockTransport(handler)):
        tools.run_custom_antigravity_agent(fake_agent, "my-bot", "follow up")

    body = captured[0]
    assert body["environment"] == "env-1"
    assert body["previous_interaction_id"] == "int-1"


def test_update_custom_antigravity_agent_sends_patch():
    captured: List[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"name": "my-bot", "instructions": "new"})

    tools = AntigravityTools(api_key="dummy")

    with _patch_sync_client(httpx.MockTransport(handler)):
        result = tools.update_custom_antigravity_agent("my-bot", instructions="new")

    assert json.loads(result) == {"name": "my-bot", "instructions": "new"}
    assert captured[0].method == "PATCH"
    assert captured[0].url.path.endswith("/agents/my-bot")
    body = json.loads(captured[0].content.decode())
    assert body == {"instructions": "new"}


def test_update_custom_antigravity_agent_rejects_empty_update():
    tools = AntigravityTools(api_key="dummy")
    result = tools.update_custom_antigravity_agent("my-bot")
    assert json.loads(result)["status"] == "error"


def test_get_custom_antigravity_agent_hits_correct_path():
    captured: List[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"name": "my-bot"})

    tools = AntigravityTools(api_key="dummy")
    with _patch_sync_client(httpx.MockTransport(handler)):
        result = tools.get_custom_antigravity_agent("my-bot")

    assert json.loads(result) == {"name": "my-bot"}
    assert captured[0].method == "GET"
    assert captured[0].url.path.endswith("/agents/my-bot")


def test_list_antigravity_agent_versions_hits_versions_path():
    captured: List[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"versions": []})

    tools = AntigravityTools(api_key="dummy")
    with _patch_sync_client(httpx.MockTransport(handler)):
        tools.list_antigravity_agent_versions("my-bot")

    assert captured[0].url.path.endswith("/agents/my-bot/versions")


def test_create_with_base_env_id_uses_env_id_form():
    captured: List[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"name": "my-bot"})

    tools = AntigravityTools(api_key="dummy")
    with _patch_sync_client(httpx.MockTransport(handler)):
        tools.create_custom_antigravity_agent(name="my-bot", instructions="be helpful", base_env_id="env-42")

    body = json.loads(captured[0].content.decode())
    assert body["base_environment"] == {"env_id": "env-42"}


def test_download_environment_snapshot_writes_file_and_returns_status():
    import os
    import tempfile

    snapshot_body = b"FAKE_TAR_" + b"y" * 50

    captured: List[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, content=snapshot_body)

    tools = AntigravityTools(api_key="dummy")
    with tempfile.NamedTemporaryFile(suffix=".tar", delete=False) as f:
        out_path = f.name
    try:
        with _patch_sync_client(httpx.MockTransport(handler)):
            result = tools.download_antigravity_environment_snapshot("env-77", out_path)

        parsed = json.loads(result)
        assert parsed["status"] == "ok"
        assert parsed["bytes"] == len(snapshot_body)
        assert parsed["environment_id"] == "env-77"
        assert "/files/environment-env-77:download" in str(captured[0].url)
        with open(out_path, "rb") as fh:
            assert fh.read() == snapshot_body
    finally:
        os.unlink(out_path)


def test_download_environment_snapshot_current_resolves_from_session_state():
    import os
    import tempfile

    captured: List[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, content=b"tar")

    tools = AntigravityTools(api_key="dummy")
    fake_agent = MagicMock()
    fake_agent.session_state = {"antigravity_env_id": "env-cached"}

    with tempfile.NamedTemporaryFile(suffix=".tar", delete=False) as f:
        out_path = f.name
    try:
        with _patch_sync_client(httpx.MockTransport(handler)):
            result = tools.download_antigravity_environment_snapshot("current", out_path, agent=fake_agent)
        parsed = json.loads(result)
        assert parsed["status"] == "ok"
        assert parsed["environment_id"] == "env-cached"
        assert "/files/environment-env-cached:download" in str(captured[0].url)
    finally:
        os.unlink(out_path)


def test_download_environment_snapshot_current_without_cached_env_returns_error():
    import os
    import tempfile

    tools = AntigravityTools(api_key="dummy")
    fake_agent = MagicMock()
    fake_agent.session_state = {}

    with tempfile.NamedTemporaryFile(suffix=".tar", delete=False) as f:
        out_path = f.name
    try:
        result = tools.download_antigravity_environment_snapshot("current", out_path, agent=fake_agent)
        parsed = json.loads(result)
        assert parsed["status"] == "error"
        assert "no cached env id" in parsed["message"]
    finally:
        os.unlink(out_path)


# ---------------------------------------------------------------------------
# agent_directory loading
# ---------------------------------------------------------------------------

import tempfile  # noqa: E402
from pathlib import Path  # noqa: E402


def _make_toolkit_agent_dir(tmp: Path) -> Path:
    (tmp / "agent.yaml").write_text(
        "id: my-bot\nbase_agent: antigravity-preview-05-2026\ndescription: A bot\nsystem_instruction: be brief\n"
    )
    (tmp / "AGENTS.md").write_text("haiku writer instructions")
    (tmp / "workspace").mkdir()
    (tmp / "workspace" / "about.txt").write_text("about content")
    (tmp / "skills").mkdir()
    (tmp / "skills" / "haiku").mkdir()
    (tmp / "skills" / "haiku" / "SKILL.md").write_text("# Haiku skill")
    return tmp


def test_agent_directory_register_false_parses_without_network():
    with tempfile.TemporaryDirectory() as d:
        _make_toolkit_agent_dir(Path(d))
        tools = AntigravityTools(api_key="dummy", agent_directory=d, register=False)

    assert tools.agent == "my-bot"
    assert tools.default_sources is not None
    targets = {s["target"] for s in tools.default_sources}
    assert "/about.txt" in targets
    assert "/.agents/skills/haiku/SKILL.md" in targets


def _symlink_or_skip(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("Symlinks not supported on this system")


def test_agent_directory_skips_workspace_and_skill_files_that_escape_via_symlink():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        agent_dir = root / "agent"
        agent_dir.mkdir()
        _make_toolkit_agent_dir(agent_dir)

        secret = root / "outside_secret.txt"
        secret.write_text("OUTSIDE_SECRET")
        _symlink_or_skip(agent_dir / "workspace" / "linked.txt", secret)
        (agent_dir / "skills" / "leaky").mkdir()
        _symlink_or_skip(agent_dir / "skills" / "leaky" / "SKILL.md", secret)

        tools = AntigravityTools(api_key="dummy", agent_directory=str(agent_dir), register=False)

    sources = tools.default_sources or []
    targets = {s["target"] for s in sources}
    contents = "\n".join(s["content"] for s in sources)
    assert "/about.txt" in targets
    assert "/linked.txt" not in targets
    assert "/.agents/skills/leaky/SKILL.md" not in targets
    assert "OUTSIDE_SECRET" not in contents


def test_agent_directory_ignores_agents_md_that_escapes_via_symlink():
    captured: List[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append({"body": json.loads(request.content.decode())})
        return httpx.Response(200, json={"name": "my-bot"})

    with tempfile.TemporaryDirectory() as d:
        agent_dir = Path(d) / "agent"
        agent_dir.mkdir()
        _make_toolkit_agent_dir(agent_dir)

        secret = Path(d) / "outside_secret.txt"
        secret.write_text("OUTSIDE_SECRET")
        (agent_dir / "AGENTS.md").unlink()
        _symlink_or_skip(agent_dir / "AGENTS.md", secret)

        with _patch_sync_client(httpx.MockTransport(handler)):
            AntigravityTools(api_key="dummy", agent_directory=str(agent_dir))

    # AGENTS.md escapes the agent dir, so it is not read; instructions fall back to the yaml value
    body = captured[0]["body"]
    assert body["instructions"] == "be brief"
    assert "OUTSIDE_SECRET" not in body.get("instructions", "")


def test_agent_directory_skips_source_dir_that_is_a_symlink_to_outside():
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

        tools = AntigravityTools(api_key="dummy", agent_directory=str(agent_dir), register=False)

    sources = tools.default_sources or []
    targets = {s["target"] for s in sources}
    contents = "\n".join(s["content"] for s in sources)
    assert "/secret.txt" not in targets
    assert "OUTSIDE_DIR_SECRET" not in contents
    # the real skills/ folder is unaffected
    assert "/.agents/skills/haiku/SKILL.md" in targets


def test_agent_directory_rejects_agent_yaml_that_escapes_via_symlink():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        agent_dir = root / "agent"
        agent_dir.mkdir()
        _make_toolkit_agent_dir(agent_dir)

        outside_yaml = root / "outside.yaml"
        outside_yaml.write_text("id: evil\nbase_agent: antigravity-preview-05-2026\n")
        (agent_dir / "agent.yaml").unlink()
        _symlink_or_skip(agent_dir / "agent.yaml", outside_yaml)

        with pytest.raises(FileNotFoundError):
            AntigravityTools(api_key="dummy", agent_directory=str(agent_dir), register=False)


def test_agent_directory_register_true_posts_to_agents():
    captured: List[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(
            {"method": request.method, "url": str(request.url), "body": json.loads(request.content.decode())}
        )
        return httpx.Response(200, json={"name": "my-bot"})

    with tempfile.TemporaryDirectory() as d:
        _make_toolkit_agent_dir(Path(d))
        with _patch_sync_client(httpx.MockTransport(handler)):
            tools = AntigravityTools(api_key="dummy", agent_directory=d)  # register=True default

    assert tools.agent == "my-bot"
    assert len(captured) == 1
    assert captured[0]["method"] == "POST"
    assert captured[0]["url"].endswith("/agents")
    body = captured[0]["body"]
    assert body["name"] == "my-bot"
    assert body["base_agent"] == "antigravity-preview-05-2026"
    # AGENTS.md beat system_instruction
    assert body["instructions"] == "haiku writer instructions"
    assert body["description"] == "A bot"
    # sources were attached
    assert body["base_environment"]["type"] == "remote"
    targets = {s["target"] for s in body["base_environment"]["sources"]}
    assert "/about.txt" in targets
    assert "/.agents/skills/haiku/SKILL.md" in targets


def test_agent_directory_treats_409_as_success():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(409, text="already exists")

    with tempfile.TemporaryDirectory() as d:
        _make_toolkit_agent_dir(Path(d))
        with _patch_sync_client(httpx.MockTransport(handler)):
            tools = AntigravityTools(api_key="dummy", agent_directory=d)

    # Construction succeeded; toolkit is wired to invoke the named agent.
    assert tools.agent == "my-bot"


def test_agent_directory_conflicts_with_explicit_agent_arg():
    with tempfile.TemporaryDirectory() as d:
        _make_toolkit_agent_dir(Path(d))
        with pytest.raises(ValueError, match="conflicts with explicit `agent="):
            AntigravityTools(api_key="dummy", agent_directory=d, agent="other", register=False)


def test_agent_directory_conflicts_with_explicit_default_sources():
    with tempfile.TemporaryDirectory() as d:
        _make_toolkit_agent_dir(Path(d))
        with pytest.raises(ValueError, match="conflicts with explicit `default_sources="):
            AntigravityTools(api_key="dummy", agent_directory=d, default_sources=[{}], register=False)


def test_agent_directory_requires_id_and_base_agent():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d)
        (p / "agent.yaml").write_text("description: missing required keys\n")
        with pytest.raises(ValueError, match="id.*base_agent"):
            AntigravityTools(api_key="dummy", agent_directory=d, register=False)


def test_agent_directory_post_400_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    with tempfile.TemporaryDirectory() as d:
        _make_toolkit_agent_dir(Path(d))
        with _patch_sync_client(httpx.MockTransport(handler)):
            with pytest.raises(RuntimeError, match="500"):
                AntigravityTools(api_key="dummy", agent_directory=d)


def test_run_antigravity_task_after_agent_directory_uses_named_agent():
    """After agent_directory wires up self.agent, run_antigravity_task should
    invoke the named agent, not the bare 'antigravity' one."""
    request_bodies: List[dict] = []
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        # First request is POST /agents (registration); second is /interactions.
        call_count["n"] += 1
        if request.url.path.endswith("/agents"):
            return httpx.Response(200, json={"name": "my-bot"})
        request_bodies.append(json.loads(request.content.decode()))
        return httpx.Response(
            200,
            json={"id": "int-1", "outputs": [{"type": "text", "text": "ok"}], "environment_id": "env-1"},
        )

    fake_agent = MagicMock()
    fake_agent.session_state = {}
    with tempfile.TemporaryDirectory() as d:
        _make_toolkit_agent_dir(Path(d))
        with _patch_sync_client(httpx.MockTransport(handler)):
            tools = AntigravityTools(api_key="dummy", agent_directory=d)
            tools.run_antigravity_task(fake_agent, "do a thing")

    assert request_bodies[0]["agent"] == "my-bot"  # not "antigravity-preview-05-2026"
