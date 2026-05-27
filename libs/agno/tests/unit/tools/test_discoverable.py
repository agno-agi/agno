"""Unit tests for DiscoverableTools."""

import asyncio
import json
import threading

import pytest

from agno.tools.discoverable import DiscoverableTools
from agno.tools.function import Function
from agno.tools.toolkit import Toolkit


def search_contacts(query: str) -> str:
    """Search contacts by name or email."""
    return f"searched: {query}"


def send_email(to: str, subject: str, body: str) -> str:
    """Email a recipient with subject and body."""
    return "sent"


def list_calendar_events() -> str:
    """List upcoming calendar events."""
    return "events"


def fetch_weather(city: str) -> str:
    """Fetch current weather for a city."""
    return "sunny"


@pytest.fixture
def dt():
    return DiscoverableTools(
        tools=[search_contacts, send_email, list_calendar_events, fetch_weather],
        max_results=3,
    )


def test_registry_built_from_callables(dt):
    assert set(dt._registry.keys()) == {
        "search_contacts",
        "send_email",
        "list_calendar_events",
        "fetch_weather",
    }


def test_registry_built_from_function_objects():
    func = Function(name="custom", description="Custom tool.", entrypoint=lambda: "ok")
    dt = DiscoverableTools(tools=[func])
    assert "custom" in dt._registry


def test_registry_built_from_toolkit():
    class MyKit(Toolkit):
        def __init__(self):
            super().__init__(name="mykit", tools=[search_contacts, send_email])

    dt = DiscoverableTools(tools=[MyKit()])
    assert "search_contacts" in dt._registry
    assert "send_email" in dt._registry


def test_toolkit_registers_search_meta_only(dt):
    # DiscoverableTools is a Toolkit - inherits get_functions() from parent.
    # It should register exactly the search_tools meta-Function.
    assert list(dt.functions.keys()) == ["search_tools"]
    assert dt.functions["search_tools"].entrypoint == dt._search


def test_bind_resets_active_names(dt):
    dt._active_names.add("send_email")
    dt.bind(tools_list=[])
    assert dt._active_names == set()


def test_toolkit_instructions_include_count(dt):
    # Toolkit's `instructions` (auto-injected via add_instructions=True)
    # replaces the old get_system_prompt_snippet method.
    assert dt.instructions is not None
    assert "4 additional tools" in dt.instructions
    assert "search_tools" in dt.instructions
    assert dt.add_instructions is True


def test_toolkit_instructions_empty_when_no_registry():
    dt = DiscoverableTools(tools=[])
    assert dt.instructions == ""


def test_search_returns_word_matches(dt):
    fake_list: list = []
    dt.bind(tools_list=fake_list)
    result = json.loads(dt._search("email send"))
    names = [t["name"] for t in result["discovered_tools"]]
    assert "send_email" in names


def test_search_appends_matches_to_tools_list(dt):
    fake_list: list = []
    dt.bind(tools_list=fake_list)
    dt._search("calendar")
    assert any(f.name == "list_calendar_events" for f in fake_list)


def test_search_respects_max_results(dt):
    fake_list: list = []
    dt.bind(tools_list=fake_list)
    # broad query that hits multiple tools
    result = json.loads(dt._search("email send calendar weather"))
    # max_results=3, registry has 4 - must cap at 3
    assert len(result["discovered_tools"]) <= 3
    assert len(fake_list) <= 3


def test_search_skips_already_active(dt):
    fake_list: list = []
    dt.bind(tools_list=fake_list)
    dt._search("email")
    before = set(dt._active_names)
    dt._search("email")
    assert dt._active_names == before  # no new activations


def test_search_returns_empty_when_no_match(dt):
    fake_list: list = []
    dt.bind(tools_list=fake_list)
    result = json.loads(dt._search("xyzzy_no_match_token"))
    assert result["discovered_tools"] == []
    assert fake_list == []


def test_search_remaining_count(dt):
    fake_list: list = []
    dt.bind(tools_list=fake_list)
    result = json.loads(dt._search("email"))
    assert result["remaining"] == len(dt._registry) - len(dt._active_names)


def test_inject_warns_when_unbound(dt, caplog):
    # No bind() called
    result = json.loads(dt._search("email"))
    # Should not crash; tools just not appended anywhere
    assert "discovered_tools" in result


def test_substring_fallback_match(dt):
    fake_list: list = []
    dt.bind(tools_list=fake_list)
    # Query token "weath" is substring of "weather" but not exact word match
    result = json.loads(dt._search("weath"))
    names = [t["name"] for t in result["discovered_tools"]]
    assert "fetch_weather" in names


def test_async_mode_flag_switches_registry():
    """Toolkits with async-only Functions should resolve through async registry."""

    async def async_only_fn() -> str:
        """Async-only capability."""
        return "done"

    class AsyncKit(Toolkit):
        def __init__(self):
            super().__init__(name="asynckit", tools=[async_only_fn])

    dt = DiscoverableTools(tools=[AsyncKit()])
    # Sync registry has the entrypoint via Toolkit.functions (async detected and routed)
    # Async registry also has it
    assert "async_only_fn" in dt._async_registry
    fake_list: list = []
    dt.bind(tools_list=fake_list, async_mode=True)
    dt._search("async")
    assert any(f.name == "async_only_fn" for f in fake_list)


def test_approval_sentinel_preserved_on_callable():
    """Raw callables with @approval(type='required') must carry the flag into the registry."""

    def sensitive_action(target: str) -> str:
        """Delete something sensitive."""
        return f"deleted {target}"

    sensitive_action._agno_approval_type = "required"  # type: ignore[attr-defined]

    dt = DiscoverableTools(tools=[sensitive_action])
    func = dt._sync_registry["sensitive_action"]
    assert func.approval_type == "required"
    assert func.requires_confirmation is True


def test_audit_approval_without_hitl_flag_raises():
    """Mirror parse_tools invariant: @approval(type='audit') needs at least one HITL flag."""

    def audited_action(target: str) -> str:
        """Perform an audited action."""
        return f"logged {target}"

    audited_action._agno_approval_type = "audit"  # type: ignore[attr-defined]

    with pytest.raises(ValueError, match="audit.*HITL"):
        DiscoverableTools(tools=[audited_action])


def test_function_object_input_registers_in_both_registries():
    """A plain Function passed in should appear in sync + async registries."""
    func = Function(name="plain", description="Plain function.", entrypoint=lambda: "ok")
    dt = DiscoverableTools(tools=[func])
    assert "plain" in dt._sync_registry
    assert "plain" in dt._async_registry


def test_bind_resets_active_names_across_runs(dt):
    """A second run must not inherit activations from the first."""
    fake_list_1: list = []
    dt.bind(tools_list=fake_list_1)
    dt._search("email")
    assert len(dt._active_names) > 0
    # Simulate second run
    fake_list_2: list = []
    dt.bind(tools_list=fake_list_2)
    assert dt._active_names == set()
    dt._search("email")
    assert len(fake_list_2) > 0


def test_discovered_function_gets_run_context_and_media(dt):
    """_inject must propagate run_context and media refs to discovered Function."""
    fake_list: list = []
    dummy_ctx = object()
    dummy_images = ["img1"]
    dt.bind(
        tools_list=fake_list,
        run_context=dummy_ctx,  # type: ignore[arg-type]
        images=dummy_images,  # type: ignore[arg-type]
    )
    dt._search("email")
    injected = fake_list[0]
    assert injected._run_context is dummy_ctx
    assert injected._images is dummy_images


def test_agent_accepts_discoverable_tools_inside_tools_list():
    """DX check: DiscoverableTools slots into the existing tools= param (Toolkit pattern)."""
    from agno.agent import Agent

    def upfront_tool() -> str:
        """Always visible."""
        return "upfront"

    def deferred_tool() -> str:
        """Discoverable."""
        return "deferred"

    discoverable = DiscoverableTools(tools=[deferred_tool])
    agent = Agent(tools=[upfront_tool, discoverable])

    # Both the upfront callable and the DiscoverableTools toolkit survive as tools
    assert agent.tools is not None
    assert any(t is discoverable for t in agent.tools)
    # Registry still holds deferred tool; it is NOT in agent.tools as a top-level entry
    assert "deferred_tool" in discoverable._sync_registry
    assert not any(callable(t) and getattr(t, "__name__", None) == "deferred_tool" for t in agent.tools)


def test_registry_exposes_media_needs_for_host_detection():
    """Host (Agent/Team) must be able to introspect discoverable pool for media params."""
    from inspect import signature

    def image_analyzer(images: list) -> str:
        """Analyze images."""
        return "analyzed"

    dt = DiscoverableTools(tools=[image_analyzer])
    has_media_tool = any(
        func.entrypoint is not None
        and any(p in signature(func.entrypoint).parameters for p in ("images", "videos", "audios", "files"))
        for func in dt._sync_registry.values()
    )
    assert has_media_tool is True


def test_async_registry_media_detection():
    """Async-only toolkit media tools must be visible via _async_registry."""
    from inspect import signature

    async def async_image_tool(images: list) -> str:
        """Async image processor."""
        return "processed"

    class AsyncMediaKit(Toolkit):
        def __init__(self):
            super().__init__(name="async_media", tools=[async_image_tool])

    dt = DiscoverableTools(tools=[AsyncMediaKit()])
    has_media_in_async = any(
        func.entrypoint is not None
        and any(p in signature(func.entrypoint).parameters for p in ("images", "videos", "audios", "files"))
        for func in dt._async_registry.values()
    )
    assert has_media_in_async is True


def test_inject_skips_duplicate_names():
    """Discovered tool with same name as already-visible tool must not override it."""

    def send_email(to: str) -> str:
        """Send email."""
        return f"sent to {to}"

    dt = DiscoverableTools(tools=[send_email])
    # Simulate an already-visible tool with same name
    existing = Function(name="send_email", description="Existing.", entrypoint=lambda: "original")
    fake_list = [existing]
    dt.bind(tools_list=fake_list)
    dt._search("email")
    # Should NOT have appended a duplicate
    assert len(fake_list) == 1
    assert fake_list[0] is existing


def test_instructions_populated_for_async_only_toolkit():
    """Async-only toolkits register into _async_registry; instructions must still inject.

    Regression: _build_instructions previously short-circuited on empty _sync_registry,
    so a toolkit with only `async def` methods produced empty instructions - the
    system-prompt hint that tells the model `search_tools` exists was never injected.
    """

    async def async_op_one() -> str:
        """First async capability."""
        return "one"

    async def async_op_two() -> str:
        """Second async capability."""
        return "two"

    class AsyncOnlyKit(Toolkit):
        def __init__(self):
            super().__init__(name="async_only", tools=[async_op_one, async_op_two])

    dt = DiscoverableTools(tools=[AsyncOnlyKit()])
    assert dt.instructions, "async-only toolkit must produce non-empty instructions"
    assert "2 additional tools" in dt.instructions
    assert "search_tools" in dt.instructions


def test_descriptions_hydrated_from_entrypoint_docstring():
    """Toolkit Function.description is empty pre-agent-build; _hydrate fills it from __doc__.

    Regression: discovered tools were returned with empty description fields because
    Agno's Agent._process_tools normally fills Function.description late, but
    _build_registry runs earlier. The model received names with no capability hint.
    """

    async def archive_record(record_id: int) -> str:
        """Archive a record by ID. Removes it from active queries but keeps audit trail."""
        return f"archived {record_id}"

    class ArchiveKit(Toolkit):
        def __init__(self):
            super().__init__(name="archive", tools=[archive_record])

    dt = DiscoverableTools(tools=[ArchiveKit()])
    func = dt._async_registry["archive_record"]
    assert func.description, "description must be hydrated from docstring"
    assert "Archive a record by ID" in func.description
    # Args: block must be stripped (Agno convention)
    assert "Args:" not in func.description


def test_search_returns_hydrated_descriptions_for_async_toolkit():
    """End-to-end: searching an async toolkit returns descriptions, not empty strings."""

    async def cancel_subscription(user_id: int) -> str:
        """Cancel an active subscription for a user."""
        return f"cancelled {user_id}"

    class BillingKit(Toolkit):
        def __init__(self):
            super().__init__(name="billing", tools=[cancel_subscription])

    dt = DiscoverableTools(tools=[BillingKit()])
    fake_list: list = []
    dt.bind(tools_list=fake_list, async_mode=True)
    result = json.loads(dt._search("cancel subscription"))
    assert result["discovered_tools"], "search must find the tool"
    found = result["discovered_tools"][0]
    assert found["name"] == "cancel_subscription"
    assert found["description"], "description must not be empty in search output"
    assert "subscription" in found["description"].lower()


def test_haystack_uses_hydrated_descriptions_for_ranking():
    """Search ranking depends on description text; hydration must reach the haystack."""

    async def reset_password(user_id: int) -> str:
        """Trigger a password reset email."""
        return "ok"

    async def archive_user(user_id: int) -> str:
        """Move a user record to the archive table."""
        return "ok"

    class UserOpsKit(Toolkit):
        def __init__(self):
            super().__init__(name="user_ops", tools=[reset_password, archive_user])

    dt = DiscoverableTools(tools=[UserOpsKit()])
    fake_list: list = []
    dt.bind(tools_list=fake_list, async_mode=True)
    # Query keyword "password" only appears in reset_password's description
    result = json.loads(dt._search("password"))
    names = [t["name"] for t in result["discovered_tools"]]
    assert "reset_password" in names
    assert names[0] == "reset_password", "haystack must rank by description text"


# ---------------------------------------------------------------------------
# Concurrency isolation - bind() state is stored in ContextVars, so concurrent
# runs of the same agent (sharing one DT instance) must not stomp on each
# other's tools list, active-names set, agent/team refs, or media.
# ---------------------------------------------------------------------------


def test_concurrent_async_runs_have_isolated_tools_list():
    """Two asyncio tasks binding the same DT to different tools lists must not collide."""

    def email_op(to: str) -> str:
        """Send email."""
        return "ok"

    def weather_op(city: str) -> str:
        """Get weather."""
        return "ok"

    dt = DiscoverableTools(tools=[email_op, weather_op])

    async def run_one(query: str, tools_list: list) -> None:
        dt.bind(tools_list=tools_list)
        # Yield so the scheduler can interleave bind/search from sibling tasks
        await asyncio.sleep(0)
        dt._search(query)
        await asyncio.sleep(0)

    list_a: list = []
    list_b: list = []

    async def main() -> None:
        await asyncio.gather(
            run_one("email", list_a),
            run_one("weather", list_b),
        )

    asyncio.run(main())

    names_a = [f.name for f in list_a if isinstance(f, Function)]
    names_b = [f.name for f in list_b if isinstance(f, Function)]

    assert "email_op" in names_a
    assert "email_op" not in names_b
    assert "weather_op" in names_b
    assert "weather_op" not in names_a


def test_concurrent_async_runs_have_isolated_active_names():
    """active_names is per-context - task A's activations don't leak into task B."""

    def alpha() -> str:
        """Alpha tool."""
        return "a"

    def beta() -> str:
        """Beta tool."""
        return "b"

    dt = DiscoverableTools(tools=[alpha, beta])

    observed: dict = {}

    async def run_one(label: str, query: str) -> None:
        dt.bind(tools_list=[])
        await asyncio.sleep(0)
        dt._search(query)
        await asyncio.sleep(0)
        observed[label] = set(dt._active_names)

    async def main() -> None:
        await asyncio.gather(run_one("a", "alpha"), run_one("b", "beta"))

    asyncio.run(main())

    assert observed["a"] == {"alpha"}
    assert observed["b"] == {"beta"}


def test_concurrent_thread_runs_have_isolated_state():
    """Two threads binding the same DT must not share tools_list_ref via ContextVars."""

    def op_one() -> str:
        """First op."""
        return "1"

    def op_two() -> str:
        """Second op."""
        return "2"

    dt = DiscoverableTools(tools=[op_one, op_two])

    list_a: list = []
    list_b: list = []
    barrier = threading.Barrier(2)

    def worker(query: str, tools_list: list) -> None:
        dt.bind(tools_list=tools_list)
        # Force interleaving: both threads bind, then both search
        barrier.wait()
        dt._search(query)

    t1 = threading.Thread(target=worker, args=("one", list_a))
    t2 = threading.Thread(target=worker, args=("two", list_b))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    names_a = [f.name for f in list_a if isinstance(f, Function)]
    names_b = [f.name for f in list_b if isinstance(f, Function)]

    assert "op_one" in names_a and "op_one" not in names_b
    assert "op_two" in names_b and "op_two" not in names_a
