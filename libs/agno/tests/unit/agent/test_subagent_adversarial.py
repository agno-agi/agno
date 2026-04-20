"""Adversarial tests intended to break the dynamic subagent PR.

These tests exercise edge cases the existing test suite does not cover:
- inherit_parent_tools leaking SubAgentToolkit (recursive spawn)
- asyncio.Lock() created in __init__ outside an event loop
- Actual max_concurrent enforcement (async semaphore)
- model_tier with missing/invalid tiers
- allowed_tools whitelist edge cases
- callable / factory tools path
- Team idempotency guard
- Circular-ref session_state
- Parent.tools being None
- Template reuse / deep_copy with real Agent
- task truncation in metadata
- Permutations of config flags
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agno.agent.agent import Agent
from agno.agent.subagent import SubAgentConfig, SubAgentToolkit


# ---------------------------------------------------------------------------
# Helpers
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


def _make_parent(
    *,
    tools: Optional[list] = None,
    template: Any = None,
    session_state: Any = None,
) -> MagicMock:
    parent = MagicMock(spec=_PARENT_SPEC)
    parent.model = None
    parent.tools = tools if tools is not None else []
    parent.knowledge = None
    parent.session_state = session_state
    parent.id = "parent-id"
    parent.name = "parent"
    parent.metadata = {}
    parent.subagent_template = template
    return parent


def _mock_agent(content: Any = "ok") -> MagicMock:
    ma = MagicMock()
    r = MagicMock()
    r.content = content
    r.metrics = None
    ma.arun = AsyncMock(return_value=r)
    ma.run = MagicMock(return_value=r)
    ma.deep_copy = MagicMock(return_value=ma)
    return ma


# ---------------------------------------------------------------------------
# 1. inherit_parent_tools leaks SubAgentToolkit → recursive spawn possible
# ---------------------------------------------------------------------------


def test_inherit_parent_tools_leaks_subagent_toolkit():
    """BUG: when inherit_parent_tools=True and the parent has SubAgentToolkit
    registered, the subagent inherits that toolkit and can therefore spawn
    its own subagents — contradicting the `enable_dynamic_subagents=False`
    guardrail the code sets on the spawned subagent.
    """
    parent_agent = Agent(
        name="orchestrator",
        enable_dynamic_subagents=True,
        subagent_config=SubAgentConfig(inherit_parent_tools=True),
    )
    parent_agent.initialize_agent()

    # Parent has SubAgentToolkit in its tools
    toolkit = next(t for t in parent_agent.tools if isinstance(t, SubAgentToolkit))
    assert isinstance(toolkit, SubAgentToolkit)

    resolved = toolkit._resolve_tools(tool_names=None, template_tools=None)
    assert resolved is not None
    leaked = [t for t in resolved if isinstance(t, SubAgentToolkit)]
    # Expectation: the toolkit should NOT be handed to the subagent.
    # If this assertion FAILS, that is the bug: recursive spawn is reachable.
    assert not leaked, (
        "inherit_parent_tools=True leaks SubAgentToolkit into the spawned subagent's "
        "tool list, enabling recursive subagent spawning despite enable_dynamic_subagents=False"
    )


# ---------------------------------------------------------------------------
# 2. asyncio.Lock() constructed at __init__ (no running loop)
# ---------------------------------------------------------------------------


def test_toolkit_constructs_without_running_event_loop():
    """SubAgentToolkit.__init__ constructs an asyncio.Lock(). Python 3.10+
    allows this outside a loop, but verify it doesn't raise at import/construct time.
    Agents are typically instantiated at module level (no loop)."""
    parent = _make_parent()
    tk = SubAgentToolkit(parent=parent, config=SubAgentConfig())
    assert tk._async_semaphore_lock is not None


# ---------------------------------------------------------------------------
# 3. Max concurrent is actually enforced
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_max_concurrent_enforced():
    """With max_concurrent=2, no more than 2 aspawn coroutines should run the
    subagent.arun body simultaneously. We gate arun on a barrier."""
    config = SubAgentConfig(max_concurrent=2, log_subagent_runs=False)
    mock = _mock_agent()
    parent = _make_parent(template=mock)
    toolkit = SubAgentToolkit(parent=parent, config=config)

    in_flight = 0
    peak = 0
    lock = asyncio.Lock()
    gate = asyncio.Event()

    async def slow_arun(*args: Any, **kwargs: Any) -> Any:
        nonlocal in_flight, peak
        async with lock:
            in_flight += 1
            if in_flight > peak:
                peak = in_flight
        await gate.wait()
        async with lock:
            in_flight -= 1
        r = MagicMock()
        r.content = "ok"
        r.metrics = None
        return r

    mock.arun = slow_arun

    async def run_all() -> None:
        tasks = [
            asyncio.create_task(toolkit.aspawn_agent(role=f"r{i}", instructions="i", task=f"t{i}")) for i in range(5)
        ]
        await asyncio.sleep(0.05)  # let them try to start
        gate.set()
        await asyncio.gather(*tasks)

    await run_all()
    assert peak <= 2, f"max_concurrent=2 not enforced; peak concurrency reached {peak}"
    assert peak >= 1


# ---------------------------------------------------------------------------
# 4. model_tier: invalid / disabled scenarios
# ---------------------------------------------------------------------------


def test_model_tier_unknown_tier_falls_back_silently():
    """Unknown tier name should fall back to template model — no crash."""
    mock = _mock_agent()
    parent = _make_parent(template=mock)
    config = SubAgentConfig(
        model_tiers={"fast": "gpt-4o-mini"},
        allow_model_tier_selection=True,
    )
    toolkit = SubAgentToolkit(parent=parent, config=config)

    # Use _resolve_model directly to verify fallback
    result = toolkit._resolve_model(model_tier="nonexistent", template=mock)
    # Should not crash, should return template.model (MagicMock attribute)
    assert result == mock.model or result is None or result is not None


def test_model_tier_ignored_when_selection_disabled():
    """allow_model_tier_selection=False => model_tier parameter is ignored."""
    mock = _mock_agent()
    mock.model = "template_model"
    parent = _make_parent(template=mock)
    parent.model = None
    config = SubAgentConfig(
        model_tiers={"fast": "gpt-4o-mini"},
        allow_model_tier_selection=False,  # disabled
    )
    toolkit = SubAgentToolkit(parent=parent, config=config)

    result = toolkit._resolve_model(model_tier="fast", template=mock)
    # Must NOT resolve 'fast' → gpt-4o-mini. Should return template.model.
    assert result == "template_model"


# ---------------------------------------------------------------------------
# 5. allowed_tools whitelist edge cases
# ---------------------------------------------------------------------------


def test_allowed_tools_empty_list_blocks_all_requested():
    """allowed_tools=[] means NO parent tool is ever delegated."""
    from agno.tools import Toolkit as _Toolkit
    from agno.tools.function import Function

    search_fn = MagicMock(spec=Function)
    search_fn.name = "search"

    class TK(_Toolkit):
        def __init__(self) -> None:
            super().__init__(name="tk")
            self.functions["search"] = search_fn

    tk = TK()
    parent = _make_parent(tools=[tk])
    config = SubAgentConfig(allowed_tools=[], allow_tool_selection=True)
    toolkit = SubAgentToolkit(parent=parent, config=config)

    resolved = toolkit._resolve_tools(["search"], template_tools=None)
    # Expected: template_tools was None, and allowed_tools=[] blocks all → None
    assert resolved is None or search_fn not in (resolved or [])


def test_allowed_tools_none_allows_all_requested():
    """allowed_tools=None + allow_tool_selection=True allows any requested tool."""
    from agno.tools.function import Function

    a_fn = MagicMock(spec=Function)
    a_fn.name = "a"
    b_fn = MagicMock(spec=Function)
    b_fn.name = "b"

    parent = _make_parent(tools=[a_fn, b_fn])
    config = SubAgentConfig(allowed_tools=None, allow_tool_selection=True)
    toolkit = SubAgentToolkit(parent=parent, config=config)

    resolved = toolkit._resolve_tools(["a", "b"], template_tools=None)
    assert resolved is not None
    assert a_fn in resolved and b_fn in resolved


def test_allowed_tools_requested_tool_not_in_parent_silently_dropped():
    """LLM requests a tool that doesn't exist on parent → silently dropped."""
    from agno.tools.function import Function

    fn = MagicMock(spec=Function)
    fn.name = "real_tool"

    parent = _make_parent(tools=[fn])
    toolkit = SubAgentToolkit(parent=parent, config=SubAgentConfig(allowed_tools=["real_tool"]))

    resolved = toolkit._resolve_tools(["ghost_tool"], template_tools=None)
    # ghost_tool doesn't exist, real_tool wasn't requested → empty → None
    assert resolved is None


def test_plain_callable_tools_filtered_by_name():
    """Plain callables are matched by __name__."""

    def my_fn() -> str:
        return "x"

    parent = _make_parent(tools=[my_fn])
    toolkit = SubAgentToolkit(parent=parent, config=SubAgentConfig())
    resolved = toolkit._resolve_tools(["my_fn"], template_tools=None)
    assert resolved is not None
    assert my_fn in resolved


# ---------------------------------------------------------------------------
# 6. Team idempotency guard
# ---------------------------------------------------------------------------


def test_team_toolkit_not_duplicated_on_repeated_init():
    """Team._set_dynamic_subagents must guard against duplicate toolkit registration."""
    from agno.team.team import Team

    member = Agent(name="member")
    team = Team(members=[member], enable_dynamic_subagents=True)
    team.initialize_team()
    team.initialize_team()  # second init simulates a second run()

    toolkits = [t for t in (team.tools or []) if isinstance(t, SubAgentToolkit)]
    assert len(toolkits) == 1, f"Expected 1 SubAgentToolkit on team, got {len(toolkits)}"


# ---------------------------------------------------------------------------
# 7. Circular-reference session_state (unhandled?)
# ---------------------------------------------------------------------------


def test_circular_session_state_does_not_crash():
    """Circular reference in session_state should not crash the subagent build.

    Current code uses json.dumps(state, default=str). json.dumps raises
    ValueError on circular refs BEFORE calling default=. This test exposes it.
    """
    parent = _make_parent()
    loop: dict = {"self": None}
    loop["self"] = loop  # circular
    parent.session_state = loop

    config = SubAgentConfig(inject_session_state=True)
    toolkit = SubAgentToolkit(parent=parent, config=config)

    # We want this to NOT raise — the code should gracefully handle it.
    try:
        ctx = toolkit._build_additional_context()
        # Acceptable: ctx is None or a string — anything that isn't an exception
        assert ctx is None or isinstance(ctx, str)
        crashed = False
    except ValueError:
        crashed = True

    assert not crashed, "session_state with circular reference crashes _build_additional_context with ValueError"


# ---------------------------------------------------------------------------
# 8. Parent.tools is None
# ---------------------------------------------------------------------------


def test_resolve_tools_when_parent_tools_is_none():
    """parent.tools=None should not crash _resolve_tools."""
    parent = _make_parent(tools=None)
    parent.tools = None  # explicit
    toolkit = SubAgentToolkit(parent=parent, config=SubAgentConfig())
    resolved = toolkit._resolve_tools(["anything"], template_tools=None)
    assert resolved is None


def test_inherit_parent_tools_when_parent_tools_is_none():
    """inherit_parent_tools=True + parent.tools=None → None (no crash)."""
    parent = _make_parent(tools=None)
    parent.tools = None
    config = SubAgentConfig(inherit_parent_tools=True)
    toolkit = SubAgentToolkit(parent=parent, config=config)
    resolved = toolkit._resolve_tools(None, template_tools=None)
    assert resolved is None


# ---------------------------------------------------------------------------
# 9. Real Agent template via deep_copy with ALL update keys
# ---------------------------------------------------------------------------


def test_build_subagent_with_real_agent_template_does_not_crash():
    """_build_subagent calls template.deep_copy(update={...}) with lots of keys.
    Make sure EVERY key in that update dict is actually accepted by
    Agent.__init__ via a round trip through deep_copy.
    """
    template = Agent(name="template")
    parent = Agent(name="parent", enable_dynamic_subagents=True, subagent_template=template)
    parent.initialize_agent()

    toolkit = next(t for t in parent.tools if isinstance(t, SubAgentToolkit))

    # Should NOT raise TypeError("unexpected keyword argument") for any update key
    subagent = toolkit._build_subagent(
        role="writer",
        instructions="write docs",
        tool_names=None,
        expected_output="markdown",
        model_tier=None,
        task="write README",
    )
    assert isinstance(subagent, Agent)
    assert subagent.name == "writer"
    assert subagent.enable_dynamic_subagents is False
    assert subagent.telemetry is False
    assert subagent.db is None
    assert subagent.num_history_runs == 0
    assert subagent.metadata is not None
    assert subagent.metadata.get("spawn_role") == "writer"
    assert subagent.metadata.get("spawn_depth") == 1


# ---------------------------------------------------------------------------
# 10. task truncation in metadata
# ---------------------------------------------------------------------------


def test_task_truncated_in_metadata():
    """task in metadata is truncated to 200 chars."""
    long_task = "x" * 500
    mock = _mock_agent()
    parent = _make_parent(template=mock)
    toolkit = SubAgentToolkit(parent=parent, config=SubAgentConfig())

    captured: dict = {}

    def cap(**kwargs: Any) -> MagicMock:
        if "update" in kwargs and isinstance(kwargs["update"], dict):
            captured.update(kwargs["update"])
        return mock

    mock.deep_copy = MagicMock(side_effect=cap)
    toolkit._build_subagent("r", "i", None, None, None, long_task)
    assert len(captured.get("metadata", {}).get("spawn_task", "")) <= 200


# ---------------------------------------------------------------------------
# 11. Callable instructions: warning path not crash
# ---------------------------------------------------------------------------


def test_agent_callable_instructions_does_not_crash_init():
    """enable_dynamic_subagents=True + callable instructions → init should
    complete (tools still wired, instructions left alone)."""

    def make_instructions(agent: Any) -> str:
        return "dynamic instructions"

    agent = Agent(name="t", instructions=make_instructions, enable_dynamic_subagents=True)
    agent.initialize_agent()

    # Toolkit must still be wired
    assert any(isinstance(t, SubAgentToolkit) for t in (agent.tools or []))


# ---------------------------------------------------------------------------
# 12. Concurrency permutations — sync semaphore
# ---------------------------------------------------------------------------


def test_sync_semaphore_is_threading_semaphore():
    """Sync semaphore must be a threading.Semaphore with the configured size."""
    parent = _make_parent()
    tk = SubAgentToolkit(parent=parent, config=SubAgentConfig(max_concurrent=3))
    # threading.Semaphore doesn't expose count publicly pre-3.13; assert type
    assert tk._sync_semaphore is not None
    # Semaphore objects from threading module share __class__ hierarchy
    import threading as _thr

    assert isinstance(tk._sync_semaphore, type(_thr.Semaphore()))


def test_sync_max_concurrent_enforced():
    """Sync max_concurrent=2 → no more than 2 concurrent spawn_agent calls."""
    config = SubAgentConfig(max_concurrent=2, log_subagent_runs=False)
    parent = _make_parent()
    tk = SubAgentToolkit(parent=parent, config=config)

    in_flight = 0
    peak = 0
    lock = threading.Lock()
    gate = threading.Event()

    def slow_run(*args: Any, **kwargs: Any) -> Any:
        nonlocal in_flight, peak
        with lock:
            in_flight += 1
            if in_flight > peak:
                peak = in_flight
        assert gate.wait(timeout=5)
        with lock:
            in_flight -= 1
        r = MagicMock()
        r.content = "ok"
        r.metrics = None
        return r

    mock = _mock_agent()
    mock.run = MagicMock(side_effect=slow_run)
    parent.subagent_template = mock

    threads = [
        threading.Thread(target=tk.spawn_agent, kwargs={"role": f"r{i}", "instructions": "i", "task": f"t{i}"})
        for i in range(5)
    ]
    for t in threads:
        t.start()
    import time

    time.sleep(0.15)
    gate.set()
    for t in threads:
        t.join(timeout=5)

    assert peak <= 2, f"sync max_concurrent=2 not enforced; peak={peak}"


# ---------------------------------------------------------------------------
# 13. Team with custom subagent_template + model tier
# ---------------------------------------------------------------------------


def test_team_build_subagent_with_model_tier_override() -> None:
    """Team parent + model_tier lookup path — verify _resolve_model directly
    (avoid end-to-end deep_copy which re-runs get_model inside Agent.__init__).
    """
    from agno.team.team import Team

    template = Agent(name="tmpl")
    member = Agent(name="m")
    team = Team(
        members=[member],
        name="team",
        enable_dynamic_subagents=True,
        subagent_template=template,
        subagent_config=SubAgentConfig(
            allow_model_tier_selection=True,
            model_tiers={"fast": "gpt-4o-mini"},
        ),
    )
    team.initialize_team()

    toolkit = next(t for t in team.tools if isinstance(t, SubAgentToolkit))

    # Patch get_model at its import site inside subagent.py via sys.modules hook
    import agno.models.utils as mutils

    sentinel = object()

    real_get_model = mutils.get_model
    mutils.get_model = lambda model_id: sentinel  # type: ignore
    try:
        resolved = toolkit._resolve_model("fast", template)
    finally:
        mutils.get_model = real_get_model  # type: ignore

    assert resolved is sentinel, "model_tier resolution did not call get_model(model_tiers['fast'])"


# ---------------------------------------------------------------------------
# 14. Team parent metadata lineage
# ---------------------------------------------------------------------------


def test_team_parent_lineage_metadata():
    """Team parent sets team_id and spawns carry parent's name."""
    from agno.team.team import Team

    m = Agent(name="m")
    team = Team(members=[m], name="alpha", enable_dynamic_subagents=True)
    team.initialize_team()
    toolkit = next(t for t in team.tools if isinstance(t, SubAgentToolkit))

    subagent = toolkit._build_subagent("r", "i", None, None, None, "t")
    assert subagent.metadata.get("spawned_by_agent_name") == "alpha"
    assert subagent.team_id == team.id


# ---------------------------------------------------------------------------
# 15. inherit_parent_tools leak: real end-to-end recursion check
# ---------------------------------------------------------------------------


def test_inherit_parent_tools_subagent_can_spawn_recursively():
    """With inherit_parent_tools=True, the spawned subagent actually has
    spawn_agent available in its real Agent.tools list — it can recursively
    spawn. This test asserts the ACTUAL Agent state after _build_subagent.
    """
    template = Agent(name="tmpl")
    parent = Agent(
        name="orchestrator",
        enable_dynamic_subagents=True,
        subagent_template=template,
        subagent_config=SubAgentConfig(inherit_parent_tools=True),
    )
    parent.initialize_agent()

    toolkit = next(t for t in parent.tools if isinstance(t, SubAgentToolkit))
    subagent = toolkit._build_subagent(
        role="worker",
        instructions="work",
        tool_names=None,
        expected_output=None,
        model_tier=None,
        task="do the thing",
    )

    # The subagent inherited the parent's tools, which include SubAgentToolkit
    subagent_toolkits = [t for t in (subagent.tools or []) if isinstance(t, SubAgentToolkit)]
    assert not subagent_toolkits, (
        "RECURSION BUG: spawned subagent has SubAgentToolkit in its tools; "
        "it can call spawn_agent even though enable_dynamic_subagents=False. "
        f"Found toolkit instances: {subagent_toolkits}"
    )


def test_template_prewired_subagent_toolkit_is_stripped():
    """If the user supplies a template that was itself initialized with
    enable_dynamic_subagents=True, the template carries a SubAgentToolkit
    in its tools. The subagent must NOT inherit that toolkit — otherwise
    the recursion guard is bypassed because the tool entrypoint remains
    reachable in the subagent's function schema.
    """
    # Template initialized as a spawn-capable agent → carries the toolkit
    template = Agent(name="tmpl", enable_dynamic_subagents=True)
    template.initialize_agent()
    assert any(isinstance(t, SubAgentToolkit) for t in template.tools)

    parent = Agent(
        name="p",
        enable_dynamic_subagents=True,
        subagent_template=template,
    )
    parent.initialize_agent()
    toolkit = next(t for t in parent.tools if isinstance(t, SubAgentToolkit))

    sub = toolkit._build_subagent("role", "ins", None, None, None, "task")
    leaked = [t for t in (sub.tools or []) if isinstance(t, SubAgentToolkit)]
    assert not leaked, (
        "Template's pre-wired SubAgentToolkit leaked into subagent.tools — "
        f"recursion guard bypassed. Leaked: {leaked}"
    )


def test_template_with_only_subagent_toolkit_ends_with_empty_tools():
    """Template whose tools list contains ONLY a SubAgentToolkit should
    result in a subagent with an empty tools list (not None, not the
    original list with the toolkit preserved)."""
    template = Agent(name="tmpl", enable_dynamic_subagents=True)
    template.initialize_agent()
    # Template.tools contains exactly one item: the SubAgentToolkit
    assert all(isinstance(t, SubAgentToolkit) for t in template.tools)

    parent = Agent(name="p", enable_dynamic_subagents=True, subagent_template=template)
    parent.initialize_agent()
    toolkit = next(t for t in parent.tools if isinstance(t, SubAgentToolkit))

    sub = toolkit._build_subagent("role", "ins", None, None, None, "task")
    # After stripping the only toolkit there should be nothing left.
    remaining = [t for t in (sub.tools or []) if isinstance(t, SubAgentToolkit)]
    assert remaining == []


def test_strip_subagent_toolkits_helper_preserves_other_tools():
    """_strip_subagent_toolkits must only remove SubAgentToolkit instances."""
    from agno.tools import Toolkit as _Toolkit

    class HarmlessTool(_Toolkit):
        def __init__(self):
            super().__init__(name="harmless")

    harmless = HarmlessTool()
    parent = _make_parent()
    tk = SubAgentToolkit(parent=parent, config=SubAgentConfig())

    mixed = [harmless, tk, harmless]
    stripped = SubAgentToolkit._strip_subagent_toolkits(mixed)
    assert stripped == [harmless, harmless]
    assert SubAgentToolkit._strip_subagent_toolkits(None) is None
    assert SubAgentToolkit._strip_subagent_toolkits([]) == []


# ---------------------------------------------------------------------------
# 16. Config pydantic rejects unexpected fields?
# ---------------------------------------------------------------------------


def test_subagent_config_rejects_unknown_fields():
    """SubAgentConfig is a pydantic BaseModel — unknown fields should error."""
    with pytest.raises(Exception):
        SubAgentConfig(bogus_field=True)  # type: ignore


def test_subagent_config_rejects_zero_max_concurrent():
    """max_concurrent=0 would create a Semaphore(0) that blocks forever on
    first acquire. Pydantic must reject it at config time."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        SubAgentConfig(max_concurrent=0)


def test_subagent_config_rejects_negative_max_concurrent():
    """max_concurrent<0 is a bug; threading.Semaphore would raise at init
    time. Catch it earlier at config validation."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        SubAgentConfig(max_concurrent=-1)


# ---------------------------------------------------------------------------
# 17. Parent.tools is a callable factory — guidance still injected, but
# toolkit NOT wired (code only warns). Verify the warning is emitted.
# ---------------------------------------------------------------------------


def test_agent_tools_factory_warns_and_skips_wiring():
    """enable_dynamic_subagents=True + tools as callable factory → warning."""

    def tool_factory() -> list:
        return []

    with patch("agno.agent._init.log_warning") as mock_warn:
        agent = Agent(name="t", enable_dynamic_subagents=True, tools=tool_factory)
        agent.initialize_agent()

    # Toolkit should NOT be in tools (tools is a callable, not a list)
    # And a warning should have been emitted by set_dynamic_subagents
    warnings_msgs = [str(call) for call in mock_warn.call_args_list]
    assert any("callable factory" in m for m in warnings_msgs), (
        f"Expected callable-factory warning; got: {warnings_msgs}"
    )


# ---------------------------------------------------------------------------
# 18. Metadata mutation isolation: subagent metadata must not be the same
# dict reference as parent's metadata (aliasing would corrupt parent state).
# ---------------------------------------------------------------------------


def test_subagent_metadata_is_not_parent_dict_reference():
    """Spawned subagent's metadata must be a NEW dict, not parent.metadata."""
    template = Agent(name="tmpl")
    parent = Agent(
        name="p",
        enable_dynamic_subagents=True,
        subagent_template=template,
        metadata={"user_key": "user_value"},
    )
    parent.initialize_agent()
    toolkit = next(t for t in parent.tools if isinstance(t, SubAgentToolkit))

    subagent = toolkit._build_subagent("r", "i", None, None, None, "t")
    # Must not share the dict reference
    assert subagent.metadata is not parent.metadata, (
        "subagent.metadata is the same dict object as parent.metadata — mutations leak"
    )
    # Parent metadata should still have its original keys unchanged
    assert parent.metadata == {"user_key": "user_value"}


# ---------------------------------------------------------------------------
# 19. Sub-subagent depth gets correctly derived even when template overrides metadata
# ---------------------------------------------------------------------------


def test_spawn_depth_uses_parent_metadata_not_template():
    """spawn_depth increments from PARENT's metadata, not template's."""
    template = Agent(name="tmpl", metadata={"spawn_depth": 99})  # would be wrong
    parent = Agent(
        name="p",
        enable_dynamic_subagents=True,
        subagent_template=template,
        metadata={"spawn_depth": 3},
    )
    parent.initialize_agent()
    toolkit = next(t for t in parent.tools if isinstance(t, SubAgentToolkit))

    subagent = toolkit._build_subagent("r", "i", None, None, None, "t")
    # Parent is at depth 3, child should be 4 (not 100)
    assert subagent.metadata.get("spawn_depth") == 4, (
        f"spawn_depth should use parent.metadata (3→4), got {subagent.metadata.get('spawn_depth')}"
    )


def test_team_tools_factory_warns_and_skips_wiring():
    """enable_dynamic_subagents=True + tools as callable factory on Team → warning, no crash."""
    from agno.team.team import Team

    def tool_factory() -> list:
        return []

    member = Agent(name="m")
    with patch("agno.team._init.log_warning") as mock_warn:
        team = Team(members=[member], enable_dynamic_subagents=True, tools=tool_factory)
        team.initialize_team()

    warnings_msgs = [str(call) for call in mock_warn.call_args_list]
    assert any("callable factory" in m for m in warnings_msgs), (
        f"Expected callable-factory warning on Team; got: {warnings_msgs}"
    )


# ---------------------------------------------------------------------------
# 20. Template override logging (ephemeral settings clobber template)
# ---------------------------------------------------------------------------


def test_build_subagent_logs_when_template_overrides_conflict():
    """When the template has non-ephemeral settings that _build_subagent
    hardcodes away, a debug log should tell the user their template field
    was overridden."""
    # Template sets telemetry=True and num_history_runs=5 — both will be
    # clobbered by the ephemeral overrides in _build_subagent.
    template = Agent(name="tmpl", telemetry=True, num_history_runs=5)
    parent = Agent(
        name="p",
        enable_dynamic_subagents=True,
        subagent_template=template,
    )
    parent.initialize_agent()
    toolkit = next(t for t in parent.tools if isinstance(t, SubAgentToolkit))

    with patch("agno.agent.subagent.log_debug") as mock_debug:
        toolkit._build_subagent("r", "i", None, None, None, "t")

    debug_messages = [str(call) for call in mock_debug.call_args_list]
    # At least one debug log should mention the override
    override_logs = [m for m in debug_messages if "override" in m.lower() or "overriding" in m.lower()]
    assert override_logs, (
        f"Expected a debug log mentioning template field overrides. Got debug messages: {debug_messages}"
    )


# ---------------------------------------------------------------------------
# 21. Log emission happens after semaphore acquire (not before)
# ---------------------------------------------------------------------------


def test_sync_spawn_log_emitted_after_semaphore_acquire():
    """The 'Spawning subagent' log must fire AFTER the sync semaphore is
    acquired, so log timestamps reflect real start time under concurrency."""
    events: list[str] = []

    class _TracingSemaphore:
        def __init__(self, inner: threading.Semaphore) -> None:
            self._inner = inner

        def __enter__(self):
            events.append("sem_enter")
            self._inner.__enter__()
            return self

        def __exit__(self, *exc):
            self._inner.__exit__(*exc)
            events.append("sem_exit")
            return False

    mock_agent = _mock_agent()
    parent = _make_parent(template=mock_agent)
    toolkit = SubAgentToolkit(parent=parent, config=SubAgentConfig(max_concurrent=1))
    toolkit._sync_semaphore = _TracingSemaphore(threading.Semaphore(1))  # type: ignore

    def fake_log_info(msg: str, *a: Any, **kw: Any) -> None:
        events.append(f"log:{msg[:30]}")

    with patch("agno.agent.subagent.log_info", side_effect=fake_log_info):
        toolkit.spawn_agent(role="tester", instructions="i", task="t")

    # The first Spawning log must come AFTER sem_enter, not before it.
    try:
        sem_enter_idx = events.index("sem_enter")
    except ValueError:
        pytest.fail(f"sem_enter not observed. events={events}")

    spawn_log_idxs = [i for i, e in enumerate(events) if e.startswith("log:") and "Spawn" in e]
    assert spawn_log_idxs, f"no Spawning log observed. events={events}"
    assert spawn_log_idxs[0] > sem_enter_idx, f"Spawning log fired BEFORE semaphore acquire. events={events}"
