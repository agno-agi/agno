"""Unit tests for contacts: the Contact wrapper and the message_contact tool.

Contacted entities are faked with duck-typed stand-ins (no models, no network);
RemoteAgent/RemoteTeam instances are real but their run methods are patched.
"""

import pytest

from agno.agent.agent import Agent
from agno.agent.remote import RemoteAgent
from agno.contacts import Contact
from agno.contacts.contacts import (
    DEFAULT_INSTRUCTIONS,
    _contacts_overview,
    _resolve_contacts,
    get_message_contact_function,
)
from agno.exceptions import RunCancelledException
from agno.run.agent import RunCompletedEvent, RunContentEvent, RunOutput
from agno.run.base import RunContext, RunStatus
from agno.run.cancel import cancel_run, cleanup_run, register_run
from agno.team.remote import RemoteTeam
from agno.tools.function import Function


class FakeEntity:
    """Duck-typed local Agent/Team stand-in with a scripted event stream."""

    def __init__(self, events=None, output=None, id="helper", name="Helper", description=None, mutate_state=None):
        self.id = id
        self.name = name
        self.description = description
        self._events = events or []
        self._output = output
        self._mutate_state = mutate_state
        self.run_kwargs = None
        self.cancelled = False

    def _finalize(self, kwargs):
        if self._mutate_state and kwargs.get("session_state") is not None:
            kwargs["session_state"].update(self._mutate_state)

    def run(self, **kwargs):
        self.run_kwargs = kwargs

        def gen():
            for event in self._events:
                yield event
            self._finalize(kwargs)
            if self._output is not None and kwargs.get("yield_run_output"):
                yield self._output

        return gen()

    def arun(self, **kwargs):
        self.run_kwargs = kwargs

        async def agen():
            for event in self._events:
                yield event
            self._finalize(kwargs)
            if self._output is not None and kwargs.get("yield_run_output"):
                yield self._output

        return agen()


def _run_context(**overrides):
    defaults = dict(run_id="parent-run", session_id="parent-session", user_id="user-1")
    defaults.update(overrides)
    return RunContext(**defaults)


def _make_function(contacts, async_mode=False, run_context=None):
    parent = Agent(name="Parent", contacts=contacts)
    return get_message_contact_function(parent, run_context or _run_context(), async_mode=async_mode)


# --- Contact wrapper ---


def test_contact_requires_exactly_one_target():
    with pytest.raises(ValueError):
        Contact()
    with pytest.raises(ValueError):
        Contact(agent=FakeEntity(), team=FakeEntity())


def test_contact_kind_detection():
    assert Contact(agent=FakeEntity()).kind == "agent"
    assert Contact(team=FakeEntity()).kind == "team"
    assert Contact(agent=RemoteAgent(base_url="http://offline-host", agent_id="ra-1")).kind == "remote agent"
    assert Contact(team=RemoteTeam(base_url="http://offline-host", team_id="rt-1")).kind == "remote team"


def test_contact_key_resolution():
    assert Contact(agent=FakeEntity(id="my-id"), name="override").key == "override"
    assert Contact(agent=FakeEntity(id="my-id")).key == "my-id"
    assert Contact(agent=RemoteAgent(base_url="http://offline-host", agent_id="ra-1")).key == "ra-1"


def test_contact_key_auto_generates_missing_id():
    # Agno auto-generates entity ids at run init; the key triggers the same
    agent = Agent(name="Docs Agent")
    assert agent.id is None
    assert Contact(agent=agent).key == "docs-agent"
    assert agent.id == "docs-agent"


def test_resolve_contacts_rejects_duplicate_keys():
    parent = Agent(contacts=[Contact(agent=FakeEntity(id="dup")), Contact(team=FakeEntity(id="dup"))])
    with pytest.raises(ValueError):
        _resolve_contacts(parent)


def test_contacts_overview_uses_instructions_then_description():
    contacts = {
        "a": Contact(agent=FakeEntity(id="a", name="A"), instructions="Call for A things"),
        "b": Contact(agent=FakeEntity(id="b", name="B", description="B expert")),
    }
    overview = _contacts_overview(contacts)
    assert "- a (agent): A - Call for A things" in overview
    assert "- b (agent): B - B expert" in overview


# --- Tool factory ---


def test_factory_builds_message_contact_function():
    fn = _make_function([Contact(agent=FakeEntity(id="helper"), instructions="Helps out")])
    assert isinstance(fn, Function)
    assert fn.name == "message_contact"
    assert "helper" in fn.description
    assert fn.instructions == DEFAULT_INSTRUCTIONS
    assert fn.add_instructions is True
    assert fn.entrypoint.__name__ == "message_contact"


def test_factory_async_mode_picks_async_entrypoint():
    fn = _make_function([Contact(agent=FakeEntity())], async_mode=True)
    assert fn.entrypoint.__name__ == "amessage_contact"


def test_factory_schema_has_only_contact_and_task_params():
    fn = _make_function([Contact(agent=FakeEntity())])
    fn.process_entrypoint()
    assert set(fn.parameters["properties"].keys()) == {"contact", "task"}


# --- Sync pump ---


def test_unknown_contact_yields_helpful_message():
    fn = _make_function([Contact(agent=FakeEntity(id="helper"))])
    results = list(fn.entrypoint(contact="nope", task="do it"))
    assert len(results) == 1
    assert "not found" in results[0]
    assert "helper" in results[0]


def test_sync_remote_contact_yields_async_required_message():
    remote = RemoteAgent(base_url="http://offline-host", agent_id="ra-1")
    fn = _make_function([Contact(agent=remote)])
    results = list(fn.entrypoint(contact="ra-1", task="do it"))
    assert len(results) == 1
    assert "async" in results[0]


def test_sync_events_stamped_and_output_captured():
    events = [RunContentEvent(content="hel"), RunContentEvent(content="lo")]
    output = RunOutput(run_id="child", content="hello", status=RunStatus.completed)
    entity = FakeEntity(events=events, output=output, id="helper")
    fn = _make_function([Contact(agent=entity)])

    results = list(fn.entrypoint(contact="helper", task="say hello"))

    # Events stamped with the parent run id; the final RunOutput never yielded
    assert all(not isinstance(r, RunOutput) for r in results)
    streamed = [r for r in results if isinstance(r, RunContentEvent)]
    assert len(streamed) == 2
    assert all(e.parent_run_id == "parent-run" for e in streamed)
    # Content streamed, so no duplicate final string
    assert not any(isinstance(r, str) for r in results)
    # Child ran in the parent's session with delegation kwargs
    kwargs = entity.run_kwargs
    assert kwargs["session_id"] == "parent-session"
    assert kwargs["user_id"] == "user-1"
    assert kwargs["stream"] is True
    assert kwargs["stream_events"] is True
    assert kwargs["yield_run_output"] is True
    assert kwargs["run_id"] is not None


def test_sync_no_streamed_content_yields_final_string():
    output = RunOutput(run_id="child", content="the answer", status=RunStatus.completed)
    entity = FakeEntity(events=[], output=output, id="helper")
    fn = _make_function([Contact(agent=entity)])

    results = list(fn.entrypoint(contact="helper", task="answer"))

    assert results[-1] == "the answer"


def test_sync_error_status_yields_failure_string():
    output = RunOutput(run_id="child", content="boom", status=RunStatus.error)
    entity = FakeEntity(events=[], output=output, id="helper")
    fn = _make_function([Contact(agent=entity)])

    results = list(fn.entrypoint(contact="helper", task="fail"))

    assert results[-1] == "Contact task failed: boom"


def test_sync_exception_yields_failure_string():
    class ExplodingEntity(FakeEntity):
        def run(self, **kwargs):
            raise RuntimeError("connection lost")

    fn = _make_function([Contact(agent=ExplodingEntity(id="helper"))])
    results = list(fn.entrypoint(contact="helper", task="do it"))
    assert results == ["Contact task failed: connection lost"]


def test_team_contact_gets_derived_session_id():
    output = RunOutput(run_id="child", content="done", status=RunStatus.completed)
    entity = FakeEntity(events=[], output=output, id="crew")
    fn = _make_function([Contact(team=entity)])

    list(fn.entrypoint(contact="crew", task="do it"))

    assert entity.run_kwargs["session_id"] == "parent-session-contact-crew"


def test_sync_session_state_merged_back():
    output = RunOutput(run_id="child", content="done", status=RunStatus.completed)
    entity = FakeEntity(events=[], output=output, id="helper", mutate_state={"added": 1})
    run_context = _run_context(session_state={"existing": True})
    fn = _make_function([Contact(agent=entity)], run_context=run_context)

    list(fn.entrypoint(contact="helper", task="do it"))

    assert run_context.session_state == {"existing": True, "added": 1}
    # The child received a copy, not the parent's dict
    assert entity.run_kwargs["session_state"] is not run_context.session_state


def test_sync_parent_cancel_cancels_child_and_raises(monkeypatch):
    cancelled_children = []
    monkeypatch.setattr("agno.team._run.cancel_run", lambda run_id: cancelled_children.append(run_id))

    events = [RunContentEvent(content="one"), RunContentEvent(content="two"), RunCompletedEvent(content="done")]
    entity = FakeEntity(events=events, id="helper")
    run_context = _run_context(run_id="cancel-parent")
    fn = _make_function([Contact(agent=entity)], run_context=run_context)

    register_run("cancel-parent")
    try:
        received = []
        with pytest.raises(RunCancelledException):
            for item in fn.entrypoint(contact="helper", task="do it"):
                received.append(item)
                cancel_run("cancel-parent")
        # The child run was cancelled with the pre-generated run id
        assert cancelled_children == [entity.run_kwargs["run_id"]]
        # Draining: the post-cancel content event is suppressed, the terminal event forwarded
        assert len([r for r in received if isinstance(r, RunContentEvent)]) == 1
        assert any(isinstance(r, RunCompletedEvent) for r in received)
    finally:
        cleanup_run("cancel-parent")


# --- Async pump ---


@pytest.mark.asyncio
async def test_async_events_stamped_and_output_captured():
    events = [RunContentEvent(content="hi")]
    output = RunOutput(run_id="child", content="hi", status=RunStatus.completed)
    entity = FakeEntity(events=events, output=output, id="helper")
    fn = _make_function([Contact(agent=entity)], async_mode=True)

    results = [item async for item in fn.entrypoint(contact="helper", task="say hi")]

    assert all(not isinstance(r, RunOutput) for r in results)
    assert results[0].parent_run_id == "parent-run"
    assert not any(isinstance(r, str) for r in results)
    assert entity.run_kwargs["yield_run_output"] is True


@pytest.mark.asyncio
async def test_async_remote_contact_runs_without_local_only_kwargs():
    remote = RemoteAgent(base_url="http://offline-host", agent_id="ra-1")
    captured = {}

    def fake_arun(**kwargs):
        captured.update(kwargs)

        async def agen():
            yield RunContentEvent(content="remote says hi", run_id="remote-child")
            yield RunCompletedEvent(content="remote says hi", run_id="remote-child")

        return agen()

    remote.arun = fake_arun
    fn = _make_function([Contact(agent=remote, instructions="Remote helper")], async_mode=True)

    results = [item async for item in fn.entrypoint(contact="ra-1", task="hi")]

    assert "yield_run_output" not in captured
    assert captured["run_id"] is not None
    assert captured["session_id"] == "parent-session"
    events = [r for r in results if not isinstance(r, str)]
    assert all(e.parent_run_id == "parent-run" for e in events)


@pytest.mark.asyncio
async def test_async_remote_final_content_from_completed_event():
    remote = RemoteAgent(base_url="http://offline-host", agent_id="ra-1")

    def fake_arun(**kwargs):
        async def agen():
            # No content events streamed and no RunOutput possible remotely
            yield RunCompletedEvent(content="remote result", run_id="remote-child")

        return agen()

    remote.arun = fake_arun
    fn = _make_function([Contact(agent=remote)], async_mode=True)

    results = [item async for item in fn.entrypoint(contact="ra-1", task="hi")]

    assert results[-1] == "remote result"


@pytest.mark.asyncio
async def test_async_remote_cancel_uses_acancel_run():
    remote = RemoteAgent(base_url="http://offline-host", agent_id="ra-1")
    captured = {}
    cancelled = []

    def fake_arun(**kwargs):
        captured.update(kwargs)

        async def agen():
            yield RunContentEvent(content="one", run_id="remote-child")
            yield RunContentEvent(content="two", run_id="remote-child")

        return agen()

    async def fake_acancel(run_id):
        cancelled.append(run_id)
        return True

    remote.arun = fake_arun
    remote.acancel_run = fake_acancel
    run_context = _run_context(run_id="remote-cancel-parent")
    fn = _make_function([Contact(agent=remote)], async_mode=True, run_context=run_context)

    register_run("remote-cancel-parent")
    try:
        with pytest.raises(RunCancelledException):
            async for _ in fn.entrypoint(contact="ra-1", task="hi"):
                cancel_run("remote-cancel-parent")
        assert cancelled == [captured["run_id"]]
    finally:
        cleanup_run("remote-cancel-parent")


@pytest.mark.asyncio
async def test_async_unknown_contact_yields_helpful_message():
    fn = _make_function([Contact(agent=FakeEntity(id="helper"))], async_mode=True)
    results = [item async for item in fn.entrypoint(contact="nope", task="do it")]
    assert len(results) == 1
    assert "not found" in results[0]


# --- Agent integration ---


def test_determine_tools_for_model_includes_message_contact():
    from unittest.mock import MagicMock

    from agno.agent._tools import determine_tools_for_model
    from agno.models.base import Model
    from agno.session import AgentSession

    agent = Agent(name="Parent", contacts=[Contact(agent=FakeEntity(id="helper"), instructions="Helps")])
    functions = determine_tools_for_model(
        agent=agent,
        model=MagicMock(spec=Model),
        processed_tools=[],
        run_response=RunOutput(run_id="parent-run"),
        run_context=_run_context(),
        session=AgentSession(session_id="parent-session"),
    )

    names = [fn.name for fn in functions if isinstance(fn, Function)]
    assert "message_contact" in names
    assert DEFAULT_INSTRUCTIONS in agent._tool_instructions


def test_agent_without_contacts_unchanged():
    from unittest.mock import MagicMock

    from agno.agent._tools import determine_tools_for_model
    from agno.models.base import Model
    from agno.session import AgentSession

    agent = Agent(name="Plain")
    functions = determine_tools_for_model(
        agent=agent,
        model=MagicMock(spec=Model),
        processed_tools=[],
        run_response=RunOutput(run_id="parent-run"),
        run_context=_run_context(),
        session=AgentSession(session_id="parent-session"),
    )
    assert functions == []


def test_parent_history_drops_contact_child_runs():
    from agno.models.message import Message
    from agno.session import AgentSession

    parent_run = RunOutput(run_id="parent-run", messages=[Message(role="user", content="hi")])
    child_run = RunOutput(
        run_id="child-run", parent_run_id="parent-run", messages=[Message(role="user", content="child task")]
    )
    session = AgentSession(session_id="parent-session", runs=[parent_run, child_run])

    messages = session.get_messages()

    assert all(m.content != "child task" for m in messages)
