"""Unit tests for SubAgentConfig and SubAgentToolkit."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agno.agent.subagent import SubAgentConfig, SubAgentToolkit

# ---------------------------------------------------------------------------
# SubAgentConfig tests
# ---------------------------------------------------------------------------


def test_subagent_config_defaults():
    """Verify all defaults match the spec (10 policy fields)."""
    cfg = SubAgentConfig()

    # Tool delegation
    assert cfg.inherit_parent_tools is False
    assert cfg.allowed_tools is None
    assert cfg.allow_tool_selection is True
    assert cfg.context_heavy_tools is None

    # Model tiers
    assert cfg.model_tiers is None
    assert cfg.allow_model_tier_selection is False

    # Context injection
    assert cfg.inject_session_state is False

    # Concurrency
    assert cfg.max_concurrent == 5

    # Observability
    assert cfg.log_subagent_runs is True
    assert cfg.show_subagent_output is False


def test_subagent_config_accepts_policy_fields():
    """Verify all policy fields round-trip correctly."""
    cfg = SubAgentConfig(
        inherit_parent_tools=True,
        allowed_tools=["search", "write"],
        allow_tool_selection=False,
        context_heavy_tools=["query_db", "read_file"],
        model_tiers={"fast": "gpt-4o-mini", "standard": "gpt-4o"},
        allow_model_tier_selection=True,
        inject_session_state=True,
        max_concurrent=10,
    )
    assert cfg.inherit_parent_tools is True
    assert cfg.allowed_tools == ["search", "write"]
    assert cfg.allow_tool_selection is False
    assert cfg.context_heavy_tools == ["query_db", "read_file"]
    assert cfg.model_tiers == {"fast": "gpt-4o-mini", "standard": "gpt-4o"}
    assert cfg.allow_model_tier_selection is True
    assert cfg.inject_session_state is True
    assert cfg.max_concurrent == 10


# ---------------------------------------------------------------------------
# SubAgentToolkit registration tests
# ---------------------------------------------------------------------------


_PARENT_SPEC = [
    "model",
    "tools",
    "knowledge",
    "session_state",
    "id",
    "name",
    "metadata",
    "subagent_template",
]


def _make_parent_mock(*, subagent_template: object = None) -> MagicMock:
    """Return a minimal MagicMock parent with explicit attribute control.

    Using spec= prevents MagicMock from auto-creating truthy attributes on access,
    which would cause getattr(parent, 'subagent_template', None) to return a MagicMock
    instead of None, silently routing _build_subagent through deep_copy instead of
    the intended fallback path.
    """
    parent = MagicMock(spec=_PARENT_SPEC)
    parent.model = None
    parent.tools = []
    parent.knowledge = None
    parent.session_state = None
    parent.id = "parent-id"
    parent.name = "parent"
    parent.metadata = {}
    parent.subagent_template = subagent_template
    return parent


def _make_toolkit(*, subagent_template: object = None) -> SubAgentToolkit:
    """Return a SubAgentToolkit with a minimal mock parent.

    Pass subagent_template=_make_mock_agent() to test the template (deep_copy) path.
    Leave as None to test the fallback Agent() creation path.
    """
    parent = _make_parent_mock(subagent_template=subagent_template)
    config = SubAgentConfig()
    return SubAgentToolkit(parent=parent, config=config)


def test_subagent_toolkit_registers_tool():
    """spawn_agent must appear in both functions and async_functions."""
    toolkit = _make_toolkit()

    assert "spawn_agent" in toolkit.functions, "spawn_agent missing from toolkit.functions"
    assert "spawn_agent" in toolkit.async_functions, "spawn_agent missing from toolkit.async_functions"


def test_subagent_toolkit_tool_description():
    """The sync function must have a description and the expected parameter properties."""
    toolkit = _make_toolkit()
    fn = toolkit.functions["spawn_agent"]
    fn.process_entrypoint()

    assert fn.description, "spawn_agent Function.description should not be empty"

    props = fn.parameters.get("properties", {})
    for expected_param in ("role", "instructions", "task"):
        assert expected_param in props, f"Expected parameter '{expected_param}' not found in spawn_agent schema"

    # model_tier should be present (optional)
    assert "model_tier" in props, "model_tier parameter missing from spawn_agent schema"


def test_subagent_toolkit_async_tool_description():
    """The async function must also have the correct parameter schema."""
    toolkit = _make_toolkit()
    async_fn = toolkit.async_functions["spawn_agent"]
    async_fn.process_entrypoint()

    assert async_fn.description, "async spawn_agent Function.description should not be empty"

    props = async_fn.parameters.get("properties", {})
    for expected_param in ("role", "instructions", "task"):
        assert expected_param in props, f"Expected parameter '{expected_param}' missing from async spawn_agent schema"


# ---------------------------------------------------------------------------
# Guidance injection tests
# ---------------------------------------------------------------------------


def test_build_guidance_basic():
    """build_guidance returns a non-empty string."""
    toolkit = _make_toolkit()
    guidance = toolkit.build_guidance()
    assert guidance
    assert "spawn_agent" in guidance


def test_build_guidance_includes_context_heavy_tools():
    """context_heavy_tools appear in the guidance block."""
    parent = MagicMock()
    parent.model = None
    parent.tools = []
    parent.knowledge = None
    parent.session_state = None
    parent.id = "p"
    parent.subagent_template = None

    config = SubAgentConfig(context_heavy_tools=["query_db", "read_csv"])
    toolkit = SubAgentToolkit(parent=parent, config=config)
    guidance = toolkit.build_guidance()

    assert "query_db" in guidance
    assert "read_csv" in guidance


def test_build_guidance_includes_model_tiers():
    """model_tiers appear in the guidance when allow_model_tier_selection=True."""
    parent = MagicMock()
    parent.model = None
    parent.tools = []
    parent.knowledge = None
    parent.session_state = None
    parent.id = "p"
    parent.subagent_template = None

    config = SubAgentConfig(
        model_tiers={"fast": "gpt-4o-mini", "powerful": "o3"},
        allow_model_tier_selection=True,
    )
    toolkit = SubAgentToolkit(parent=parent, config=config)
    guidance = toolkit.build_guidance()

    assert "fast" in guidance
    assert "gpt-4o-mini" in guidance
    assert "powerful" in guidance


def test_build_guidance_uses_custom_tier_hints():
    """Custom tier_hints appear in guidance alongside built-in hints."""
    parent = _make_parent_mock()
    config = SubAgentConfig(
        model_tiers={"cheap": "gpt-4o-mini", "fast": "gpt-4o"},
        allow_model_tier_selection=True,
        tier_hints={"cheap": "trivial lookups only"},
    )
    toolkit = SubAgentToolkit(parent=parent, config=config)
    guidance = toolkit.build_guidance()

    assert "cheap" in guidance
    assert "trivial lookups only" in guidance
    # Built-in fast hint still merged in
    assert "extraction" in guidance


def test_toolkit_registers_both_sync_and_async_spawn():
    """Both spawn_agent (sync) and aspawn_agent (async) must be registered as different entrypoints."""
    mock_agent = _make_mock_agent()
    toolkit = _make_toolkit(subagent_template=mock_agent)

    assert "spawn_agent" in toolkit.functions, "sync spawn_agent not registered"
    assert "spawn_agent" in toolkit.async_functions, "async spawn_agent not registered"

    sync_fn = toolkit.functions["spawn_agent"]
    async_fn = toolkit.async_functions["spawn_agent"]
    # They must be different Function objects wrapping different callables
    assert sync_fn is not async_fn, "sync and async spawn_agent should be distinct Function objects"


def test_guidance_injected_into_agent_instructions():
    """set_dynamic_subagents appends guidance to agent.instructions (None → str)."""
    from agno.agent.agent import Agent

    agent = Agent(name="test", enable_dynamic_subagents=True)
    agent.initialize_agent()

    assert agent.instructions is not None
    assert "spawn_agent" in str(agent.instructions)
    assert "Dynamic Subagent Guidance" in str(agent.instructions)


def test_guidance_injected_into_str_instructions():
    """set_dynamic_subagents appends guidance after existing str instructions."""
    from agno.agent.agent import Agent

    original = "You are a helpful assistant."
    agent = Agent(name="test", instructions=original, enable_dynamic_subagents=True)
    agent.initialize_agent()

    assert isinstance(agent.instructions, str)
    # Original instructions must be preserved at the start
    assert agent.instructions.startswith(original)
    # Guidance must be appended after
    assert "Dynamic Subagent Guidance" in agent.instructions
    assert agent.instructions.index(original) < agent.instructions.index("Dynamic Subagent Guidance")


def test_guidance_injected_into_list_instructions():
    """set_dynamic_subagents appends guidance as final element of list instructions."""
    from agno.agent.agent import Agent

    original = ["You are a helpful assistant.", "Always be concise."]
    agent = Agent(name="test", instructions=original, enable_dynamic_subagents=True)
    agent.initialize_agent()

    assert isinstance(agent.instructions, list)
    # Original messages must be preserved
    assert agent.instructions[0] == original[0]
    assert agent.instructions[1] == original[1]
    # Guidance must be the last element
    last = agent.instructions[-1]
    assert "Dynamic Subagent Guidance" in str(last)


# ---------------------------------------------------------------------------
# Agent integration tests
# ---------------------------------------------------------------------------


def test_agent_has_dynamic_subagent_fields():
    """Agent accepts enable_dynamic_subagents, subagent_template, and subagent_config."""
    from agno.agent.agent import Agent

    agent = Agent(name="test", enable_dynamic_subagents=False)
    assert agent.enable_dynamic_subagents is False
    assert agent.subagent_template is None
    assert agent.subagent_config is None


def test_agent_wires_toolkit_when_enabled():
    """SubAgentToolkit is added to agent.tools after initialize_agent runs."""
    from agno.agent.agent import Agent

    agent = Agent(name="test", enable_dynamic_subagents=True)
    agent.initialize_agent()

    toolkit_found = any(isinstance(t, SubAgentToolkit) for t in (agent.tools or []))
    assert toolkit_found, "SubAgentToolkit should be in agent.tools when enable_dynamic_subagents=True"


def test_toolkit_not_duplicated_on_repeated_run():
    """set_dynamic_subagents must not add a second toolkit on repeated initialize_agent calls."""
    from agno.agent.agent import Agent

    agent = Agent(name="test", enable_dynamic_subagents=True)
    agent.initialize_agent()
    agent.initialize_agent()  # second call simulates second run()

    toolkits = [t for t in (agent.tools or []) if isinstance(t, SubAgentToolkit)]
    assert len(toolkits) == 1, f"Expected 1 SubAgentToolkit, found {len(toolkits)}"


def test_agent_wires_toolkit_with_custom_config():
    """Custom SubAgentConfig is threaded through to the toolkit."""
    from agno.agent.agent import Agent

    config = SubAgentConfig(max_concurrent=2, context_heavy_tools=["big_query"])
    agent = Agent(name="test", enable_dynamic_subagents=True, subagent_config=config)
    agent.initialize_agent()

    toolkit = next((t for t in (agent.tools or []) if isinstance(t, SubAgentToolkit)), None)
    assert toolkit is not None
    assert toolkit._config.max_concurrent == 2
    assert toolkit._config.context_heavy_tools == ["big_query"]


def test_agent_with_subagent_template():
    """subagent_template is stored on the agent."""
    from agno.agent.agent import Agent

    template = Agent(name="template_agent")
    agent = Agent(name="orchestrator", enable_dynamic_subagents=True, subagent_template=template)
    agent.initialize_agent()

    assert agent.subagent_template is template


# ---------------------------------------------------------------------------
# Team integration tests
# ---------------------------------------------------------------------------


def test_team_has_dynamic_subagent_fields():
    """Team accepts enable_dynamic_subagents, subagent_template, and subagent_config."""
    from agno.agent.agent import Agent
    from agno.team.team import Team

    member = Agent(name="member")
    team = Team(members=[member], enable_dynamic_subagents=False)
    assert team.enable_dynamic_subagents is False
    assert team.subagent_template is None
    assert team.subagent_config is None


def test_team_wires_toolkit_when_enabled():
    """SubAgentToolkit is added to team.tools after initialize_team runs."""
    from agno.agent.agent import Agent
    from agno.team.team import Team

    member = Agent(name="member")
    team = Team(members=[member], enable_dynamic_subagents=True)
    team.initialize_team()

    toolkit_found = any(isinstance(t, SubAgentToolkit) for t in (team.tools or []))
    assert toolkit_found, "SubAgentToolkit should be in team.tools when enable_dynamic_subagents=True"


# ---------------------------------------------------------------------------
# Async spawn tests
# ---------------------------------------------------------------------------


def _make_mock_agent(content: object = "ok") -> MagicMock:
    """Return a MagicMock that quacks like an Agent with arun/run/deep_copy."""
    agent_mock = MagicMock()
    result_mock = MagicMock()
    result_mock.content = content
    result_mock.metrics = None  # explicit None — prevents MagicMock auto-attr polluting log assertions
    agent_mock.arun = AsyncMock(return_value=result_mock)
    agent_mock.run = MagicMock(return_value=result_mock)
    # _build_subagent calls template.deep_copy(update={...}) — return self so
    # the mock's arun/run are preserved on the spawned agent.
    agent_mock.deep_copy = MagicMock(return_value=agent_mock)
    return agent_mock


@pytest.mark.asyncio
async def test_aspawn_agent_returns_content():
    """aspawn_agent returns the subagent's content string (via template deep_copy path)."""
    mock_agent = _make_mock_agent(content="Subagent answer")
    toolkit = _make_toolkit(subagent_template=mock_agent)

    answer = await toolkit.aspawn_agent(
        role="helper",
        instructions="Do the thing",
        task="What is 1+1?",
    )
    assert answer == "Subagent answer"


@pytest.mark.asyncio
async def test_aspawn_agent_no_content_returns_fallback():
    """aspawn_agent returns fallback message when content is None (via template deep_copy path)."""
    mock_agent = _make_mock_agent(content=None)
    toolkit = _make_toolkit(subagent_template=mock_agent)

    answer = await toolkit.aspawn_agent(
        role="helper",
        instructions="Do the thing",
        task="What is 1+1?",
    )
    assert answer == "Subagent completed with no output."


@pytest.mark.asyncio
async def test_async_semaphore_single_instance():
    """Concurrent aspawn_agent calls must share ONE semaphore, not create duplicates."""
    import asyncio

    mock_agent = _make_mock_agent(content="ok")
    parent = MagicMock(
        spec=["model", "tools", "knowledge", "session_state", "id", "name", "metadata", "subagent_template"]
    )
    parent.model = None
    parent.tools = []
    parent.knowledge = None
    parent.session_state = None
    parent.id = "p"
    parent.name = "p"
    parent.metadata = {}
    parent.subagent_template = mock_agent

    config = SubAgentConfig(max_concurrent=2)
    toolkit = SubAgentToolkit(parent=parent, config=config)

    semaphores_seen: list = []
    original_get = toolkit._get_async_semaphore

    async def tracking_get() -> asyncio.Semaphore:
        sem = await original_get()
        semaphores_seen.append(id(sem))
        return sem

    toolkit._get_async_semaphore = tracking_get  # type: ignore

    await asyncio.gather(
        toolkit.aspawn_agent(role="r1", instructions="i", task="t1"),
        toolkit.aspawn_agent(role="r2", instructions="i", task="t2"),
    )

    assert len(set(semaphores_seen)) == 1, "Multiple semaphore objects created — race condition!"


@pytest.mark.asyncio
async def test_aspawn_agent_handles_subagent_exception():
    """aspawn_agent returns a structured error string when subagent.arun raises."""
    mock_agent = _make_mock_agent()
    mock_agent.arun = AsyncMock(side_effect=RuntimeError("API rate limit"))

    parent = MagicMock(
        spec=["model", "tools", "knowledge", "session_state", "id", "name", "metadata", "subagent_template"]
    )
    parent.model = None
    parent.tools = []
    parent.knowledge = None
    parent.session_state = None
    parent.id = "p"
    parent.name = "p"
    parent.metadata = {}
    parent.subagent_template = mock_agent

    toolkit = SubAgentToolkit(parent=parent, config=SubAgentConfig())
    result = await toolkit.aspawn_agent(role="r", instructions="i", task="t")

    assert "failed" in result.lower()
    assert "API rate limit" in result


def test_spawn_agent_handles_subagent_exception():
    """spawn_agent returns a structured error string when subagent.run raises."""
    mock_agent = _make_mock_agent()
    mock_agent.run = MagicMock(side_effect=RuntimeError("model unavailable"))

    parent = MagicMock(
        spec=["model", "tools", "knowledge", "session_state", "id", "name", "metadata", "subagent_template"]
    )
    parent.model = None
    parent.tools = []
    parent.knowledge = None
    parent.session_state = None
    parent.id = "p"
    parent.name = "p"
    parent.metadata = {}
    parent.subagent_template = mock_agent

    toolkit = SubAgentToolkit(parent=parent, config=SubAgentConfig())
    result = toolkit.spawn_agent(role="r", instructions="i", task="t")

    assert "failed" in result.lower()
    assert "model unavailable" in result


def test_build_additional_context_warns_on_non_serializable():
    """_build_additional_context emits a log_warning when session_state has non-serializable values."""
    parent = MagicMock(
        spec=["model", "tools", "knowledge", "session_state", "id", "name", "metadata", "subagent_template"]
    )
    parent.session_state = {"connection": object()}  # not JSON-serializable

    config = SubAgentConfig(inject_session_state=True)
    toolkit = SubAgentToolkit(parent=parent, config=config)

    with patch("agno.agent.subagent.log_warning") as mock_warn:
        ctx = toolkit._build_additional_context()

    assert ctx is not None
    mock_warn.assert_called_once()
    warning_msg = mock_warn.call_args[0][0].lower()
    assert "non-serializable" in warning_msg


def test_build_additional_context_injects_session_state():
    """_build_additional_context embeds parent session_state as JSON when inject_session_state=True."""
    parent = MagicMock()
    parent.session_state = {"user": "alice", "plan": "premium"}

    config = SubAgentConfig(inject_session_state=True)
    toolkit = SubAgentToolkit(parent=parent, config=config)

    ctx = toolkit._build_additional_context()
    assert ctx is not None
    assert "alice" in ctx
    assert "premium" in ctx


def test_build_additional_context_skipped_when_disabled():
    """_build_additional_context returns None when inject_session_state=False."""
    parent = MagicMock()
    parent.session_state = {"user": "bob"}

    config = SubAgentConfig(inject_session_state=False)
    toolkit = SubAgentToolkit(parent=parent, config=config)

    assert toolkit._build_additional_context() is None


@pytest.mark.asyncio
async def test_aspawn_agent_injects_session_state():
    """When inject_session_state=True, deep_copy receives additional_context with the state."""
    parent = MagicMock()
    parent.model = None
    parent.tools = []
    parent.knowledge = None
    parent.session_state = {"user": "alice"}
    parent.id = "parent-id"
    parent.name = "p"
    parent.metadata = {}
    parent.subagent_template = None

    config = SubAgentConfig(inject_session_state=True)
    toolkit = SubAgentToolkit(parent=parent, config=config)

    captured_update: dict = {}
    mock_agent = _make_mock_agent(content="ok")

    def capture_deep_copy(**kwargs: object) -> MagicMock:
        if "update" in kwargs and isinstance(kwargs["update"], dict):
            captured_update.update(kwargs["update"])  # type: ignore[arg-type]
        return mock_agent

    mock_agent.deep_copy = MagicMock(side_effect=capture_deep_copy)

    with patch("agno.agent.agent.Agent", return_value=mock_agent):
        await toolkit.aspawn_agent(
            role="helper",
            instructions="Help out",
            task="greet",
        )

    assert "additional_context" in captured_update
    assert "alice" in captured_update["additional_context"]


@pytest.mark.asyncio
async def test_aspawn_agent_does_not_pass_session_state_to_run():
    """session_state is NOT passed to subagent.run() — only embedded in additional_context."""
    parent = MagicMock()
    parent.model = None
    parent.tools = []
    parent.knowledge = None
    parent.session_state = {"user": "bob"}
    parent.id = "pid"
    parent.name = "p"
    parent.metadata = {}
    parent.subagent_template = None

    config = SubAgentConfig(inject_session_state=True)
    toolkit = SubAgentToolkit(parent=parent, config=config)

    captured_run_kwargs: dict = {}
    result_mock = MagicMock()
    result_mock.content = "done"

    # Build a mock that captures arun kwargs and has deep_copy returning itself
    mock_agent = MagicMock()

    async def fake_arun(*args: object, **kwargs: object) -> MagicMock:
        captured_run_kwargs.update(kwargs)
        return result_mock

    mock_agent.arun = fake_arun
    mock_agent.deep_copy = MagicMock(return_value=mock_agent)

    with patch("agno.agent.agent.Agent", return_value=mock_agent):
        await toolkit.aspawn_agent(role="r", instructions="i", task="t")

    # session_state must NOT be in the run() call (only in additional_context)
    assert "session_state" not in captured_run_kwargs


# ---------------------------------------------------------------------------
# Tool whitelist filtering
# ---------------------------------------------------------------------------


def test_build_subagent_does_not_clear_template_tools_when_no_resolution():
    """When _resolve_tools returns None, the tools key must be absent from deep_copy update."""
    mock_agent = _make_mock_agent()
    captured = _capture_deep_copy_update(mock_agent)

    parent = MagicMock(
        spec=["model", "tools", "knowledge", "session_state", "id", "name", "metadata", "subagent_template"]
    )
    parent.model = None
    parent.tools = []  # no parent tools to delegate
    parent.knowledge = None
    parent.session_state = None
    parent.id = "p"
    parent.name = "p"
    parent.metadata = {}
    parent.subagent_template = mock_agent  # template has its own tools

    config = SubAgentConfig(inherit_parent_tools=False, allow_tool_selection=False)
    toolkit = SubAgentToolkit(parent=parent, config=config)

    with patch("agno.agent.agent.Agent", return_value=mock_agent):
        toolkit._build_subagent("r", "i", None, None, None, "t")

    # "tools" key must NOT be in the update dict — template keeps its own tools
    assert "tools" not in captured, f"tools key should be absent, got: {captured.get('tools')}"


def test_resolve_tools_whitelist_filtering():
    """_resolve_tools includes only whitelisted Function objects, not the whole toolkit."""
    from agno.tools import Toolkit as _Toolkit
    from agno.tools.function import Function

    do_search_fn = MagicMock(spec=Function)
    do_search_fn.name = "do_search"
    do_write_fn = MagicMock(spec=Function)
    do_write_fn.name = "do_write"

    class FakeToolkit(_Toolkit):
        def __init__(self) -> None:
            super().__init__(name="fake")
            self.functions["do_search"] = do_search_fn
            self.functions["do_write"] = do_write_fn

    fake_tk = FakeToolkit()

    parent = MagicMock(
        spec=["model", "tools", "knowledge", "session_state", "id", "name", "metadata", "subagent_template"]
    )
    parent.model = None
    parent.tools = [fake_tk]
    parent.knowledge = None
    parent.session_state = None
    parent.id = "parent-id"
    parent.name = "p"
    parent.metadata = {}
    parent.subagent_template = None

    config = SubAgentConfig(allowed_tools=["do_search"])
    toolkit = SubAgentToolkit(parent=parent, config=config)

    resolved = toolkit._resolve_tools(["do_search", "do_write"], template_tools=None)
    assert resolved is not None
    # The whole toolkit must NOT be delegated
    assert fake_tk not in resolved, "Full toolkit must not be delegated — only permitted functions"
    # Only the permitted Function must be present
    assert do_search_fn in resolved, "do_search Function must be present"
    assert do_write_fn not in resolved, "do_write must be excluded since it was not in allowed_tools"


def test_resolve_tools_whitelist_does_not_leak_unrequested_functions():
    """When a toolkit has 3 functions and only 1 is whitelisted, only that 1 is delegated."""
    from agno.tools import Toolkit as _Toolkit
    from agno.tools.function import Function

    search_fn = MagicMock(spec=Function)
    search_fn.name = "search"
    image_fn = MagicMock(spec=Function)
    image_fn.name = "image_search"
    news_fn = MagicMock(spec=Function)
    news_fn.name = "news_search"

    class MultiTool(_Toolkit):
        def __init__(self) -> None:
            super().__init__(name="multi")
            self.functions["search"] = search_fn
            self.functions["image_search"] = image_fn
            self.functions["news_search"] = news_fn

    multi = MultiTool()

    parent = MagicMock(
        spec=["model", "tools", "knowledge", "session_state", "id", "name", "metadata", "subagent_template"]
    )
    parent.model = None
    parent.tools = [multi]
    parent.knowledge = None
    parent.session_state = None
    parent.id = "parent-id"
    parent.name = "p"
    parent.metadata = {}
    parent.subagent_template = None

    config = SubAgentConfig(allowed_tools=["search"], allow_tool_selection=True)
    toolkit = SubAgentToolkit(parent=parent, config=config)

    resolved = toolkit._resolve_tools(["search"], template_tools=None)
    assert resolved is not None
    assert multi not in resolved
    assert search_fn in resolved
    assert image_fn not in resolved
    assert news_fn not in resolved


def test_resolve_tools_inherit_parent():
    """inherit_parent_tools=True returns all parent tools regardless of selection."""
    parent = MagicMock()
    tool_a = MagicMock()
    tool_b = MagicMock()
    parent.tools = [tool_a, tool_b]
    parent.subagent_template = None

    config = SubAgentConfig(inherit_parent_tools=True)
    toolkit = SubAgentToolkit(parent=parent, config=config)

    resolved = toolkit._resolve_tools(["tool_x"], template_tools=None)
    assert tool_a in resolved
    assert tool_b in resolved


# ---------------------------------------------------------------------------
# Lineage / metadata tests
# ---------------------------------------------------------------------------


def _capture_deep_copy_update(mock_agent: MagicMock) -> dict:
    """Wire mock_agent.deep_copy to capture the update dict and return self."""
    captured: dict = {}

    def capture(**kwargs: object) -> MagicMock:
        if "update" in kwargs and isinstance(kwargs["update"], dict):
            captured.update(kwargs["update"])  # type: ignore[arg-type]
        return mock_agent

    mock_agent.deep_copy = MagicMock(side_effect=capture)
    return captured


def _make_lineage_parent(
    *, parent_id: str = "parent-42", name: str = "orchestrator", metadata: dict | None = None
) -> MagicMock:
    parent = MagicMock()
    parent.model = None
    parent.tools = []
    parent.knowledge = None
    parent.session_state = None
    parent.id = parent_id
    parent.name = name
    parent.metadata = metadata if metadata is not None else {}
    parent.subagent_template = None
    return parent


def test_subagent_metadata_carries_lineage():
    """_build_subagent passes spawned_by_* and spawn_depth in metadata via deep_copy update."""
    parent = _make_lineage_parent(parent_id="parent-42", name="orchestrator")
    toolkit = SubAgentToolkit(parent=parent, config=SubAgentConfig())

    mock_agent = _make_mock_agent()
    captured = _capture_deep_copy_update(mock_agent)

    with patch("agno.agent.agent.Agent", return_value=mock_agent):
        toolkit._build_subagent(
            role="rust_dev",
            instructions="Write Rust code.",
            tool_names=None,
            expected_output=None,
            model_tier=None,
            task="Implement a binary search tree in Rust.",
        )

    meta = captured.get("metadata", {})
    assert meta.get("spawned_by_agent_id") == "parent-42"
    assert meta.get("spawned_by_agent_name") == "orchestrator"
    assert meta.get("spawn_role") == "rust_dev"
    assert meta.get("spawn_depth") == 1
    assert "binary search tree" in meta.get("spawn_task", "")


def test_subagent_spawn_task_uses_task_not_instructions():
    """spawn_task in metadata is the task argument, not the instructions."""
    parent = _make_lineage_parent()
    toolkit = SubAgentToolkit(parent=parent, config=SubAgentConfig())

    mock_agent = _make_mock_agent()
    captured = _capture_deep_copy_update(mock_agent)

    with patch("agno.agent.agent.Agent", return_value=mock_agent):
        toolkit._build_subagent(
            role="worker",
            instructions="You are a specialist system prompt that is very long.",
            tool_names=None,
            expected_output=None,
            model_tier=None,
            task="Concrete user task here.",
        )

    spawn_task = captured.get("metadata", {}).get("spawn_task", "")
    assert "Concrete user task" in spawn_task
    assert "specialist system prompt" not in spawn_task


def test_subagent_spawn_depth_increments():
    """spawn_depth increments when parent itself was a subagent (depth 1 → child is depth 2)."""
    parent = _make_lineage_parent(parent_id="subagent-1", name="intermediate", metadata={"spawn_depth": 1})
    toolkit = SubAgentToolkit(parent=parent, config=SubAgentConfig())

    mock_agent = _make_mock_agent()
    captured = _capture_deep_copy_update(mock_agent)

    with patch("agno.agent.agent.Agent", return_value=mock_agent):
        toolkit._build_subagent("child", "Do something.", None, None, None, "child task")

    assert captured.get("metadata", {}).get("spawn_depth") == 2


def test_subagent_recursion_disabled():
    """Spawned subagents always have enable_dynamic_subagents=False."""
    parent = _make_lineage_parent()
    toolkit = SubAgentToolkit(parent=parent, config=SubAgentConfig())

    mock_agent = _make_mock_agent()
    captured = _capture_deep_copy_update(mock_agent)

    with patch("agno.agent.agent.Agent", return_value=mock_agent):
        toolkit._build_subagent("r", "i", None, None, None, "t")

    assert captured.get("enable_dynamic_subagents") is False


def test_team_parent_sets_team_id():
    """When parent is a Team, team_id is set directly on the spawned subagent.

    team_id is NOT in the deep_copy update dict — Agent.__init__ does not
    accept it. It is assigned to the subagent attribute after construction.
    """
    from agno.agent.agent import Agent
    from agno.team.team import Team

    member = Agent(name="member")
    team = Team(members=[member], name="my_team")
    team.initialize_team()

    toolkit = SubAgentToolkit(parent=team, config=SubAgentConfig())

    mock_agent = _make_mock_agent()
    captured = _capture_deep_copy_update(mock_agent)

    with patch("agno.agent.agent.Agent", return_value=mock_agent):
        subagent = toolkit._build_subagent("specialist", "Specialize.", None, None, None, "task")

    # team_id must NOT be in the deep_copy update dict (would crash Agent.__init__)
    assert "team_id" not in captured, "team_id must not be in deep_copy update — Agent.__init__ rejects it"
    # team_id must be set on the subagent directly after construction
    assert subagent.team_id == team.id


def test_agent_parent_does_not_set_team_id():
    """When parent is a plain Agent (not a Team), team_id is not set on the subagent."""
    from agno.agent.agent import Agent

    parent = Agent(name="solo_agent")
    parent.initialize_agent()

    toolkit = SubAgentToolkit(parent=parent, config=SubAgentConfig())

    mock_agent = _make_mock_agent()
    captured = _capture_deep_copy_update(mock_agent)

    with patch("agno.agent.agent.Agent", return_value=mock_agent):
        toolkit._build_subagent("helper", "Help.", None, None, None, "task")

    # team_id must not be in the deep_copy update dict for a plain-Agent parent
    assert "team_id" not in captured


# ---------------------------------------------------------------------------
# Phase 1 — Lifecycle visibility tests
# ---------------------------------------------------------------------------


def test_log_subagent_runs_true_emits_spawn_and_completion():
    """When log_subagent_runs=True (default), log_info is called for spawn and completion."""
    mock_agent = _make_mock_agent(content="result")
    toolkit = _make_toolkit(subagent_template=mock_agent)

    with patch("agno.agent.subagent.log_info") as mock_log:
        toolkit.spawn_agent(role="analyst", instructions="analyse", task="Count the rows")

    assert mock_log.call_count == 2, f"Expected 2 log_info calls, got {mock_log.call_count}"
    spawn_msg = mock_log.call_args_list[0][0][0]
    done_msg = mock_log.call_args_list[1][0][0]
    assert "analyst" in spawn_msg and "Spawning" in spawn_msg
    assert "depth=1" in spawn_msg
    assert "analyst" in done_msg and "completed" in done_msg
    assert "depth=1" in done_msg


def test_log_subagent_runs_false_no_log_info():
    """When log_subagent_runs=False, log_info is never called by the spawn path."""
    mock_agent = _make_mock_agent(content="result")
    parent = _make_parent_mock(subagent_template=mock_agent)
    toolkit = SubAgentToolkit(parent=parent, config=SubAgentConfig(log_subagent_runs=False))

    with patch("agno.agent.subagent.log_info") as mock_log:
        toolkit.spawn_agent(role="analyst", instructions="analyse", task="Count the rows")

    mock_log.assert_not_called()


def test_show_subagent_output_true_prints_to_stdout(capsys):
    """When show_subagent_output=True, the subagent's content is printed to stdout."""
    mock_agent = _make_mock_agent(content="Here is my answer")
    parent = _make_parent_mock(subagent_template=mock_agent)
    toolkit = SubAgentToolkit(parent=parent, config=SubAgentConfig(show_subagent_output=True))

    with patch("agno.agent.subagent.log_info"):
        toolkit.spawn_agent(role="writer", instructions="write", task="Write a haiku")

    captured = capsys.readouterr()
    assert "writer" in captured.out
    assert "Here is my answer" in captured.out


def test_show_subagent_output_false_no_stdout(capsys):
    """When show_subagent_output=False (default), nothing is printed to stdout."""
    mock_agent = _make_mock_agent(content="Here is my answer")
    toolkit = _make_toolkit(subagent_template=mock_agent)

    with patch("agno.agent.subagent.log_info"):
        toolkit.spawn_agent(role="writer", instructions="write", task="Write a haiku")

    captured = capsys.readouterr()
    assert captured.out == ""
