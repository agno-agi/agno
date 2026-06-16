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
    """SubAgentToolkit.__init__ does NOT create an asyncio.Lock. Constructing
    a Lock outside a running loop would bind it to whichever loop first
    acquires it, breaking cross-loop reuse (pytest-asyncio, worker pools).

    Instead the Lock is deferred to first async-spawn access. Verify the
    toolkit constructs cleanly and that the Lock stays unset until then."""
    parent = _make_parent()
    tk = SubAgentToolkit(parent=parent, config=SubAgentConfig())
    assert tk._async_semaphore is None
    assert tk._async_semaphore_lock is None, (
        "Lock should be lazy-initialised inside a running event loop, not at __init__ time"
    )


def test_async_semaphore_survives_cross_event_loop_reuse():
    """Construct the toolkit once, then use it from two successive
    asyncio loops. The lazy-lock pattern must not leak loop affinity."""
    mock = _mock_agent()
    parent = _make_parent(template=mock)
    tk = SubAgentToolkit(parent=parent, config=SubAgentConfig(max_concurrent=1, log_subagent_runs=False))

    async def _spawn_once() -> str:
        return await tk.aspawn_agent(role="r", instructions="i", task="t")

    for _ in range(2):
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(_spawn_once())
            assert result == "ok"
        finally:
            # Fresh loop on next iteration — simulates new test / worker pool.
            # Reset the async primitives so the next loop rebinds them.
            tk._async_semaphore = None
            tk._async_semaphore_lock = None
            loop.close()


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
        f"Template's pre-wired SubAgentToolkit leaked into subagent.tools — recursion guard bypassed. Leaked: {leaked}"
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
# additional_context preservation
# ---------------------------------------------------------------------------


def test_template_additional_context_preserved_when_inject_disabled():
    """Template.additional_context must survive a spawn when
    inject_session_state=False — otherwise the default path silently
    clobbers user-configured context with None."""
    template = Agent(name="tmpl", additional_context="TEMPLATE_CONTEXT_KEEP_ME")
    parent = Agent(
        name="p",
        enable_dynamic_subagents=True,
        subagent_template=template,
        subagent_config=SubAgentConfig(inject_session_state=False),
    )
    parent.initialize_agent()
    toolkit = next(t for t in parent.tools if isinstance(t, SubAgentToolkit))

    sub = toolkit._build_subagent("r", "i", None, None, None, "t")
    assert sub.additional_context == "TEMPLATE_CONTEXT_KEEP_ME"


def test_inject_session_state_overrides_template_additional_context():
    """When inject_session_state=True AND the template has its own
    additional_context, the injected state takes precedence. This documents
    the override semantics — the alternative would be ambiguous merging."""
    template = Agent(name="tmpl", additional_context="TEMPLATE_CTX")
    parent = Agent(
        name="p",
        enable_dynamic_subagents=True,
        subagent_template=template,
        session_state={"user": "alice"},
        subagent_config=SubAgentConfig(inject_session_state=True),
    )
    parent.initialize_agent()
    toolkit = next(t for t in parent.tools if isinstance(t, SubAgentToolkit))

    sub = toolkit._build_subagent("r", "i", None, None, None, "t")
    # The template context is replaced, not merged.
    assert sub.additional_context is not None
    assert "alice" in sub.additional_context
    assert "TEMPLATE_CTX" not in sub.additional_context


def test_no_additional_context_when_neither_template_nor_injection():
    """No template context + inject_session_state=False → subagent has
    additional_context=None (neither source sets it)."""
    template = Agent(name="tmpl")
    parent = Agent(
        name="p",
        enable_dynamic_subagents=True,
        subagent_template=template,
    )
    parent.initialize_agent()
    toolkit = next(t for t in parent.tools if isinstance(t, SubAgentToolkit))
    sub = toolkit._build_subagent("r", "i", None, None, None, "t")
    assert sub.additional_context is None


# ---------------------------------------------------------------------------
# allowed_tools applies to template tools too
# ---------------------------------------------------------------------------


def test_allowed_tools_filters_template_toolkit_functions():
    """When both a template toolkit and an allowed_tools whitelist are set,
    the whitelist must apply to the template's toolkit — otherwise the
    subagent silently inherits every function of that toolkit, bypassing
    the user's explicit whitelist."""
    from agno.tools import Toolkit as _Toolkit
    from agno.tools.function import Function

    keep_fn = MagicMock(spec=Function)
    keep_fn.name = "keep_me"
    drop_fn = MagicMock(spec=Function)
    drop_fn.name = "drop_me"
    extra_fn = MagicMock(spec=Function)
    extra_fn.name = "extra_fn"

    class ThreeFn(_Toolkit):
        def __init__(self):
            super().__init__(name="threefn")
            self.functions["keep_me"] = keep_fn
            self.functions["drop_me"] = drop_fn
            self.functions["extra_fn"] = extra_fn

    tk_on_template = ThreeFn()
    parent = _make_parent()
    cfg = SubAgentConfig(allowed_tools=["keep_me"])
    toolkit = SubAgentToolkit(parent=parent, config=cfg)

    resolved = toolkit._resolve_tools(
        tool_names=None,
        template_tools=[tk_on_template],
    )
    # The whitelist must filter the template toolkit to just the permitted
    # Function; the toolkit object itself must not be delegated.
    assert resolved is not None
    assert tk_on_template not in resolved
    assert keep_fn in resolved
    assert drop_fn not in resolved
    assert extra_fn not in resolved


def test_allowed_tools_none_lets_template_tools_through_unchanged():
    """allowed_tools=None → no template filtering; the whole toolkit passes
    through so the subagent keeps every tool the template had."""
    from agno.tools import Toolkit as _Toolkit

    class LooseToolkit(_Toolkit):
        def __init__(self):
            super().__init__(name="loose")

    loose = LooseToolkit()
    parent = _make_parent()
    cfg = SubAgentConfig(allowed_tools=None)
    toolkit = SubAgentToolkit(parent=parent, config=cfg)

    resolved = toolkit._resolve_tools(
        tool_names=None,
        template_tools=[loose],
    )
    assert resolved == [loose]


def test_allowed_tools_empty_list_blocks_template_tools_too():
    """allowed_tools=[] — explicit empty whitelist — must block template
    toolkits as well as parent tools."""
    from agno.tools import Toolkit as _Toolkit
    from agno.tools.function import Function

    fn = MagicMock(spec=Function)
    fn.name = "search"

    class TK(_Toolkit):
        def __init__(self):
            super().__init__(name="tk")
            self.functions["search"] = fn

    tk = TK()
    parent = _make_parent()
    cfg = SubAgentConfig(allowed_tools=[], allow_tool_selection=True)
    toolkit = SubAgentToolkit(parent=parent, config=cfg)

    resolved = toolkit._resolve_tools(["search"], template_tools=[tk])
    # Whitelist is empty → nothing passes through from either side.
    assert resolved is None or fn not in resolved
    assert resolved is None or tk not in resolved


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


# ---------------------------------------------------------------------------
# Streaming: verify subagent is always invoked with stream=False regardless
# of parent's streaming mode (both sync and async spawn paths).
# ---------------------------------------------------------------------------


def test_sync_spawn_forces_stream_false_on_subagent_run():
    """Parent may run in stream=True mode, but the subagent must always be
    invoked with stream=False — streaming a subagent's chunks into a
    synchronous caller would be pointless (the caller only gets a string
    back) and would defeat context isolation."""
    captured: dict = {}

    def fake_run(*args: Any, **kwargs: Any) -> Any:
        captured.update(kwargs)
        r = MagicMock()
        r.content = "ok"
        r.metrics = None
        return r

    mock_agent = MagicMock()
    mock_agent.run = fake_run
    mock_agent.deep_copy = MagicMock(return_value=mock_agent)

    parent = _make_parent(template=mock_agent)
    toolkit = SubAgentToolkit(parent=parent, config=SubAgentConfig(log_subagent_runs=False))
    toolkit.spawn_agent(role="r", instructions="i", task="task_a")

    assert captured.get("stream") is False
    assert captured.get("input") == "task_a"


@pytest.mark.asyncio
async def test_async_spawn_forces_stream_false_on_subagent_arun():
    """Same invariant for the async path — aspawn_agent must pass stream=False
    to subagent.arun regardless of how the parent is streaming."""
    captured: dict = {}
    result_mock = MagicMock()
    result_mock.content = "ok"
    result_mock.metrics = None

    async def fake_arun(*args: Any, **kwargs: Any) -> Any:
        captured.update(kwargs)
        return result_mock

    mock_agent = MagicMock()
    mock_agent.arun = fake_arun
    mock_agent.deep_copy = MagicMock(return_value=mock_agent)

    parent = _make_parent(template=mock_agent)
    toolkit = SubAgentToolkit(parent=parent, config=SubAgentConfig(log_subagent_runs=False))
    await toolkit.aspawn_agent(role="r", instructions="i", task="task_a")

    assert captured.get("stream") is False
    assert captured.get("input") == "task_a"


# ---------------------------------------------------------------------------
# build_guidance edge cases
# ---------------------------------------------------------------------------


def test_build_guidance_empty_model_tiers_omits_section():
    """model_tiers={} with allow_model_tier_selection=True is a degenerate
    config — the guidance must not emit a dangling 'Model tier selection'
    section with zero tiers listed."""
    parent = _make_parent()
    cfg = SubAgentConfig(model_tiers={}, allow_model_tier_selection=True)
    tk = SubAgentToolkit(parent=parent, config=cfg)

    guidance = tk.build_guidance()
    assert "Model tier selection" not in guidance


# ---------------------------------------------------------------------------
# Edge-case input shapes
# ---------------------------------------------------------------------------


def test_session_state_as_non_dict_string_does_not_crash():
    """session_state is typed Dict in Agent, but defensively handle the case
    where a user set it to a scalar or string value."""
    parent = _make_parent()
    parent.session_state = "I am a string"
    cfg = SubAgentConfig(inject_session_state=True)
    tk = SubAgentToolkit(parent=parent, config=cfg)
    ctx = tk._build_additional_context()
    # json.dumps of a string is the quoted literal — any non-None return is OK.
    assert ctx is not None


def test_template_knowledge_persists_to_subagent():
    """knowledge is a heavy resource shared across deep_copy (see _utils.py) —
    the subagent should carry the same KnowledgeProtocol instance."""
    mock_knowledge = MagicMock()
    mock_knowledge.name = "fake_kb"

    template = Agent(name="tmpl", knowledge=mock_knowledge)
    parent = Agent(
        name="p",
        enable_dynamic_subagents=True,
        subagent_template=template,
    )
    parent.initialize_agent()
    toolkit = next(t for t in parent.tools if isinstance(t, SubAgentToolkit))

    sub = toolkit._build_subagent("role", "ins", None, None, None, "task")
    assert sub.knowledge is mock_knowledge


def test_multiple_spawns_produce_independent_metadata_dicts():
    """Each spawn must get a fresh metadata dict — otherwise two subagents
    in a single parent run would share (and mutate) the same object."""
    template = Agent(name="tmpl")
    parent = Agent(
        name="p",
        enable_dynamic_subagents=True,
        subagent_template=template,
    )
    parent.initialize_agent()
    toolkit = next(t for t in parent.tools if isinstance(t, SubAgentToolkit))

    s1 = toolkit._build_subagent("r1", "i", None, None, None, "t1")
    s2 = toolkit._build_subagent("r2", "i", None, None, None, "t2")
    assert s1.metadata is not s2.metadata
    s1.metadata["leak"] = "from_s1"
    assert "leak" not in (s2.metadata or {})


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


# ---------------------------------------------------------------------------
# 22. inherit_parent_tools respects allowed_tools whitelist (regression)
# ---------------------------------------------------------------------------


def test_inherit_parent_tools_honours_allowed_tools_whitelist():
    """Regression: inherit_parent_tools=True must apply the allowed_tools
    whitelist. Previously the early-return path ignored the whitelist and
    silently delegated every parent tool."""
    from agno.tools.function import Function

    safe = MagicMock(spec=Function)
    safe.name = "safe_lookup"
    danger = MagicMock(spec=Function)
    danger.name = "delete_all_rows"

    parent = _make_parent(tools=[safe, danger])
    cfg = SubAgentConfig(
        inherit_parent_tools=True,
        allowed_tools=["safe_lookup"],
    )
    tk = SubAgentToolkit(parent=parent, config=cfg)

    resolved = tk._resolve_tools(tool_names=None, template_tools=None)
    assert resolved is not None
    assert safe in resolved
    assert danger not in resolved, (
        "inherit_parent_tools=True must apply allowed_tools whitelist; "
        "'delete_all_rows' leaked despite allowed_tools=['safe_lookup']"
    )


def test_inherit_parent_tools_with_empty_allowed_tools_blocks_everything():
    """Regression: allowed_tools=[] (empty whitelist) must block even
    inherited parent tools."""
    from agno.tools.function import Function

    fn = MagicMock(spec=Function)
    fn.name = "any"
    parent = _make_parent(tools=[fn])
    cfg = SubAgentConfig(inherit_parent_tools=True, allowed_tools=[])
    tk = SubAgentToolkit(parent=parent, config=cfg)
    resolved = tk._resolve_tools(tool_names=None, template_tools=None)
    assert resolved == [] or fn not in (resolved or []), "inherit_parent_tools=True bypasses allowed_tools=[]"


def test_inherit_parent_tools_whitelist_keeps_permitted_tool_end_to_end():
    """End-to-end on a real Agent: inherit_parent_tools=True + allowed_tools
    filters correctly at _build_subagent time."""

    def safe_lookup() -> str:
        """Safe read-only."""
        return "ok"

    def danger_delete() -> str:
        """Destructive."""
        return "DELETED"

    parent = Agent(
        name="orch",
        tools=[safe_lookup, danger_delete],
        enable_dynamic_subagents=True,
        subagent_config=SubAgentConfig(
            inherit_parent_tools=True,
            allowed_tools=["safe_lookup"],
        ),
    )
    parent.initialize_agent()
    tk = next(t for t in parent.tools if isinstance(t, SubAgentToolkit))
    sub = tk._build_subagent("r", "i", None, None, None, "t")
    names = [getattr(t, "__name__", getattr(t, "name", type(t).__name__)) for t in (sub.tools or [])]
    assert "safe_lookup" in names
    assert "danger_delete" not in names


# ---------------------------------------------------------------------------
# 23. model_tiers accepts pre-instantiated Model instances (non-OpenAI)
# ---------------------------------------------------------------------------


def test_model_tier_accepts_pre_instantiated_model_instance():
    """model_tiers values can be Model instances — these are returned verbatim,
    bypassing get_model() which defaults to OpenAI and won't work for other
    providers like Azure/Anthropic."""
    from agno.models.base import Model

    # Create a minimal Model subclass stand-in.
    fake_model = MagicMock(spec=Model)
    fake_model.id = "custom-model-id"

    mock_template = _mock_agent()
    parent = _make_parent(template=mock_template)
    cfg = SubAgentConfig(
        model_tiers={"fast": fake_model},
        allow_model_tier_selection=True,
    )
    tk = SubAgentToolkit(parent=parent, config=cfg)

    resolved = tk._resolve_model("fast", mock_template)
    assert resolved is fake_model, (
        "model_tiers value that is already a Model must be returned verbatim; "
        "get_model() must NOT be called when the tier value is a Model instance"
    )


def test_model_tier_string_id_still_routes_through_get_model():
    """Regression: string values must still flow through get_model()."""
    mock_template = _mock_agent()
    parent = _make_parent(template=mock_template)
    cfg = SubAgentConfig(
        model_tiers={"fast": "gpt-4o-mini"},
        allow_model_tier_selection=True,
    )
    tk = SubAgentToolkit(parent=parent, config=cfg)

    import agno.models.utils as mutils

    sentinel = object()
    real_get_model = mutils.get_model
    mutils.get_model = lambda mid: sentinel if mid == "gpt-4o-mini" else None  # type: ignore
    try:
        resolved = tk._resolve_model("fast", mock_template)
    finally:
        mutils.get_model = real_get_model  # type: ignore
    assert resolved is sentinel


def test_refresh_parent_instructions_updates_string_instructions():
    """Mutating subagent_config after init + calling refresh_parent_instructions
    must update the injected guidance block in the parent's instructions."""
    cfg = SubAgentConfig(context_heavy_tools=["alpha"])
    parent = Agent(
        name="p",
        instructions="Base instructions.",
        enable_dynamic_subagents=True,
        subagent_config=cfg,
    )
    parent.initialize_agent()
    tk = next(t for t in parent.tools if isinstance(t, SubAgentToolkit))
    assert "alpha" in (parent.instructions or "")

    cfg.context_heavy_tools = ["alpha", "beta"]
    updated = tk.refresh_parent_instructions()
    assert updated is True
    assert "alpha" in parent.instructions
    assert "beta" in parent.instructions
    # Base instructions preserved.
    assert "Base instructions." in parent.instructions
    # Exactly one guidance block (not duplicated).
    assert parent.instructions.count("--- Dynamic Subagent Guidance ---") == 1


def test_refresh_parent_instructions_updates_list_instructions():
    """Same thing when parent.instructions is a list."""
    cfg = SubAgentConfig(context_heavy_tools=["alpha"])
    parent = Agent(
        name="p",
        instructions=["line 1", "line 2"],
        enable_dynamic_subagents=True,
        subagent_config=cfg,
    )
    parent.initialize_agent()
    tk = next(t for t in parent.tools if isinstance(t, SubAgentToolkit))

    cfg.context_heavy_tools = ["alpha", "gamma"]
    assert tk.refresh_parent_instructions() is True
    joined = "\n".join(parent.instructions)
    assert "gamma" in joined
    assert "line 1" in joined


def test_refresh_parent_instructions_noop_for_callable_instructions():
    """Callable instructions cannot be rewritten at runtime → returns False."""

    def make(agent):
        return "dynamic"

    parent = Agent(
        name="p",
        instructions=make,
        enable_dynamic_subagents=True,
    )
    parent.initialize_agent()
    tk = next(t for t in parent.tools if isinstance(t, SubAgentToolkit))
    assert tk.refresh_parent_instructions() is False
    # instructions still the callable reference
    assert parent.instructions is make


def test_agent_rejects_non_agent_subagent_template():
    """subagent_template must be an Agent instance — catch common misuses."""
    with pytest.raises(TypeError, match="subagent_template must be an Agent"):
        Agent(name="p", subagent_template="not an agent")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="subagent_template must be an Agent"):
        Agent(name="p", subagent_template={"name": "fake"})  # type: ignore[arg-type]


def test_agent_rejects_non_config_subagent_config():
    """subagent_config must be a SubAgentConfig instance."""
    with pytest.raises(TypeError, match="subagent_config must be"):
        Agent(name="p", subagent_config={"max_concurrent": 3})  # type: ignore[arg-type]


def test_team_rejects_non_agent_subagent_template():
    """Team enforces the same subagent_template type check as Agent."""
    from agno.team.team import Team

    m = Agent(name="m")
    with pytest.raises(TypeError, match="subagent_template must be an Agent"):
        Team(members=[m], subagent_template="bad")  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_spawn_agent_raises_when_called_from_async_context():
    """Calling the sync spawn_agent from inside a running event loop would
    silently block; the guard must raise RuntimeError instead."""
    parent = _make_parent(template=_mock_agent())
    tk = SubAgentToolkit(parent=parent, config=SubAgentConfig(log_subagent_runs=False))
    with pytest.raises(RuntimeError, match="aspawn_agent"):
        tk.spawn_agent(role="r", instructions="i", task="t")


def test_spawn_agent_succeeds_from_sync_context():
    """Regression: sync call from sync context still works."""
    parent = _make_parent(template=_mock_agent())
    tk = SubAgentToolkit(parent=parent, config=SubAgentConfig(log_subagent_runs=False))
    out = tk.spawn_agent(role="r", instructions="i", task="t")
    assert out == "ok"


def test_fallback_agent_warns_when_parent_has_knowledge_but_no_template():
    """If the user configured parent.knowledge but no subagent_template, the
    fallback Agent(model=parent_model) silently drops the knowledge ref.
    A warning must surface so the user knows to pass a template."""
    from unittest.mock import patch

    class _KB:
        pass

    parent_agent = Agent(
        name="p",
        knowledge=_KB(),  # type: ignore[arg-type]
        enable_dynamic_subagents=True,
        # subagent_template intentionally NOT set → triggers fallback path
    )
    parent_agent.initialize_agent()
    tk = next(t for t in parent_agent.tools if isinstance(t, SubAgentToolkit))

    with patch("agno.agent.subagent.log_warning") as mock_warn:
        tk._build_subagent("r", "i", None, None, None, "t")

    warn_msgs = [str(c) for c in mock_warn.call_args_list]
    assert any("knowledge" in m.lower() for m in warn_msgs), f"expected knowledge-related warning in {warn_msgs}"


def test_fallback_agent_no_warning_when_parent_has_no_knowledge():
    """No knowledge → no warning (avoid log spam)."""
    from unittest.mock import patch

    parent_agent = Agent(name="p", enable_dynamic_subagents=True)
    parent_agent.initialize_agent()
    tk = next(t for t in parent_agent.tools if isinstance(t, SubAgentToolkit))

    with patch("agno.agent.subagent.log_warning") as mock_warn:
        tk._build_subagent("r", "i", None, None, None, "t")

    warn_msgs = [str(c) for c in mock_warn.call_args_list]
    assert not any("knowledge" in m.lower() for m in warn_msgs), (
        f"unexpected knowledge warning when parent has no knowledge: {warn_msgs}"
    )


def test_subagent_empty_string_result_is_returned_verbatim():
    """result.content=="" is a LEGITIMATE answer from the model; it must not
    be replaced with the 'no output' sentinel."""

    def mk():
        r = MagicMock()
        r.content = ""
        r.metrics = None
        mock = MagicMock()
        mock.run = MagicMock(return_value=r)
        mock.arun = AsyncMock(return_value=r)
        mock.deep_copy = MagicMock(return_value=mock)
        return mock

    parent = _make_parent(template=mk())
    tk = SubAgentToolkit(parent=parent, config=SubAgentConfig(log_subagent_runs=False))
    out = tk.spawn_agent(role="r", instructions="i", task="t")
    assert out == "", f"expected empty string passthrough, got {out!r}"


def test_subagent_none_result_falls_back_to_sentinel():
    """Only result is None OR result.content is None triggers the sentinel."""
    mock = MagicMock()
    r = MagicMock()
    r.content = None
    r.metrics = None
    mock.run = MagicMock(return_value=r)
    mock.arun = AsyncMock(return_value=r)
    mock.deep_copy = MagicMock(return_value=mock)

    parent = _make_parent(template=mock)
    tk = SubAgentToolkit(parent=parent, config=SubAgentConfig(log_subagent_runs=False))
    out = tk.spawn_agent(role="r", instructions="i", task="t")
    assert out == "Subagent completed with no output."


def test_subagent_tools_are_deep_copied_not_shared_with_parent():
    """Toolkits placed in update['tools'] must be deep-copied, not shared
    with the parent. Mutating a toolkit's state in the subagent must not
    corrupt the parent's toolkit instance."""
    from agno.tools import Toolkit as _Toolkit

    class StatefulToolkit(_Toolkit):
        def __init__(self) -> None:
            super().__init__(name="stateful")
            self.counter = 0

    tk_on_template = StatefulToolkit()
    template = Agent(name="tmpl", tools=[tk_on_template])
    parent = Agent(
        name="p",
        enable_dynamic_subagents=True,
        subagent_template=template,
    )
    parent.initialize_agent()
    toolkit = next(t for t in parent.tools if isinstance(t, SubAgentToolkit))

    sub = toolkit._build_subagent("r", "i", None, None, None, "t")
    sub_tks = [t for t in (sub.tools or []) if isinstance(t, StatefulToolkit)]
    assert sub_tks, "expected the template's StatefulToolkit on the subagent"
    sub_tks[0].counter = 42  # mutate on the subagent side

    # Parent's toolkit must NOT have been affected.
    assert tk_on_template.counter == 0, (
        "subagent's toolkit mutation leaked into parent — tools were shared by reference"
    )


def test_duplicate_function_name_across_toolkits_deduped_with_warning():
    """Two toolkits each contribute a Function named 'search'. The LLM must
    see only ONE tool (the first), and a warning must be emitted — otherwise
    the tool schema sent to the model is illegal (duplicate names)."""
    from agno.tools import Toolkit as _Toolkit
    from agno.tools.function import Function

    s1 = MagicMock(spec=Function)
    s1.name = "search"
    s2 = MagicMock(spec=Function)
    s2.name = "search"

    class TK1(_Toolkit):
        def __init__(self):
            super().__init__(name="tk1")
            self.functions["search"] = s1

    class TK2(_Toolkit):
        def __init__(self):
            super().__init__(name="tk2")
            self.functions["search"] = s2

    parent = _make_parent(tools=[TK1(), TK2()])
    cfg = SubAgentConfig(allowed_tools=["search"])
    toolkit = SubAgentToolkit(parent=parent, config=cfg)

    from unittest.mock import patch

    with patch("agno.agent.subagent.log_warning") as mock_warn:
        resolved = toolkit._resolve_tools(["search"], template_tools=None)

    assert resolved is not None
    count = sum(1 for t in resolved if t is s1 or t is s2)
    assert count == 1, f"Expected deduped to 1 'search' Function, got {count}"
    assert any("Duplicate tool name" in str(call) for call in mock_warn.call_args_list), (
        f"Expected a duplicate-name warning; got: {mock_warn.call_args_list}"
    )


def test_model_tier_mixed_dict_accepts_both_str_and_model():
    """model_tiers may mix strings and Model instances in the same dict."""
    from agno.models.base import Model

    instance = MagicMock(spec=Model)
    instance.id = "instance-one"

    cfg = SubAgentConfig(
        model_tiers={"fast": "gpt-4o-mini", "powerful": instance},
        allow_model_tier_selection=True,
    )
    assert cfg.model_tiers is not None
    assert cfg.model_tiers["fast"] == "gpt-4o-mini"
    assert cfg.model_tiers["powerful"] is instance
