"""Recording-model coverage for opt-in page references and history."""

from __future__ import annotations

import copy
import json

import pytest

from agno.agent import Agent
from agno.agent._messages import get_continue_run_messages
from agno.agent._references import resume_references
from agno.db.in_memory import InMemoryDb
from agno.knowledge.document import Document
from agno.knowledge.knowledge import Knowledge
from agno.models.base import Model
from agno.models.message import Message, MessageMetrics
from agno.models.response import ModelResponse
from agno.run import RunContext
from agno.run.agent import RunInput, RunOutput


class RecordingKnowledge(Knowledge):
    def __post_init__(self):
        self.calls = []
        self.revision = "one"

    def retrieve(self, query, **kwargs):
        self.calls.append(query)
        return [
            Document(
                content="Source " + self.revision,
                meta_data={"url": "https://docs.example.com/a", "revision": self.revision},
            )
        ]

    async def aretrieve(self, query, **kwargs):
        return self.retrieve(query, **kwargs)


class RecordingModel(Model):
    def __init__(self, tool_loop=False, tool_name="inspect_example"):
        super().__init__(id="recording", name="recording", provider="test")
        self.seen = []
        self.tool_loop = tool_loop
        self.tool_name = tool_name
        self.rosters = []

    def invoke(self, *args, **kwargs):
        messages = kwargs["messages"]
        self.seen.append(copy.deepcopy(messages))
        self.rosters.append([entry["function"]["name"] for entry in kwargs.get("tools") or []])
        if self.tool_loop and messages[-1].role == "user":
            return ModelResponse(
                role="assistant",
                tool_calls=[
                    {
                        "id": "call-1",
                        "type": "function",
                        "function": {
                            "name": self.tool_name,
                            "arguments": "{}" if self.tool_name == "inspect_example" else '{"query":"custom query"}',
                        },
                    }
                ],
                response_usage=MessageMetrics(),
            )
        return ModelResponse(role="assistant", content="Grounded answer", response_usage=MessageMetrics())

    async def ainvoke(self, *args, **kwargs):
        return self.invoke(*args, **kwargs)

    def invoke_stream(self, *args, **kwargs):
        yield self.invoke(*args, **kwargs)

    async def ainvoke_stream(self, *args, **kwargs):
        yield self.invoke(*args, **kwargs)

    def _parse_provider_response(self, response, **kwargs):
        return response

    def _parse_provider_response_delta(self, response):
        return response


@pytest.mark.parametrize("context,search", [(True, True), (True, False), (False, True), (False, False)])
@pytest.mark.parametrize("asynchronous,stream", [(False, False), (False, True), (True, False), (True, True)])
@pytest.mark.asyncio
async def test_flags_and_multi_turn_history(context, search, asynchronous, stream):
    knowledge = RecordingKnowledge(page_store=object())
    model = RecordingModel()
    agent = Agent(
        model=model,
        knowledge=knowledge,
        add_knowledge_to_context=context,
        search_knowledge=search,
        db=InMemoryDb(),
        add_history_to_context=True,
        telemetry=False,
    )
    questions = ["  Original question?  ", "Follow-up question?"]
    outputs = []
    for question in questions:
        if asynchronous:
            result = (
                agent.arun(question, session_id="conversation", stream=True)
                if stream
                else await agent.arun(question, session_id="conversation")
            )
            if stream:
                outputs.append([event async for event in result])
            else:
                outputs.append(result)
        else:
            result = agent.run(question, session_id="conversation", stream=stream)
            outputs.append(list(result) if stream else result)
    assert knowledge.calls == [q.strip() for q in questions] if context else knowledge.calls == []
    for index, messages in enumerate(model.seen):
        references = [m for m in messages if m.name == "knowledge_references"]
        assert len(references) == int(context)
        assert messages[-1].content == questions[index]
        if context:
            assert messages[-2] is references[0]
            assert references[0].role == "user" and not references[0].temporary and not references[0].add_to_history
    session = agent.get_session(session_id="conversation")
    assert all(m.name != "knowledge_references" for run in session.runs for m in run.messages)
    assert model.seen[0][0].content == model.seen[1][0].content


def test_reference_retained_during_tool_loop_and_fresh_checkpoint_resume():
    knowledge = RecordingKnowledge(page_store=object())
    model = RecordingModel(tool_loop=True)

    def inspect_example() -> str:
        return "Example read."

    agent = Agent(
        model=model,
        knowledge=knowledge,
        add_knowledge_to_context=True,
        search_knowledge=False,
        tools=[inspect_example],
        telemetry=False,
    )
    result = agent.run("Original question")
    assert len(model.seen) == 2 and len(knowledge.calls) == 1
    assert all(sum(m.name == "knowledge_references" for m in messages) == 1 for messages in model.seen)
    assert all(m.name != "knowledge_references" for m in result.messages)
    checkpoint = RunOutput.from_dict(result.to_dict())
    checkpoint.input = RunInput(input_content="Original question")
    knowledge.revision = "two"
    context = RunContext(run_id=result.run_id, session_id=result.session_id)
    messages = get_continue_run_messages(agent, checkpoint.messages, run_context=context)
    resume_references(agent, context, checkpoint, messages)
    resume_references(agent, context, checkpoint, messages)
    assert knowledge.calls == ["Original question", "Original question"]
    evidence = next(m for m in messages.messages if m.name == "knowledge_references")
    assert "Source two" in evidence.content
    calls = next(i for i, m in enumerate(messages.messages) if m.tool_calls)
    assert messages.messages[calls + 1].tool_call_id == "call-1"


@pytest.mark.parametrize("returned,status", [(None, None), ([], "empty"), ([{"content": "x" * 30000}], "available")])
def test_custom_retriever_skipping_empty_and_encoded_budget(returned, status):
    calls = []

    def custom(query, **kwargs):
        calls.append(query)
        return returned

    knowledge = RecordingKnowledge(page_store=object())
    model = RecordingModel()
    agent = Agent(
        model=model,
        knowledge=knowledge,
        knowledge_retriever=custom,
        add_knowledge_to_context=True,
        search_knowledge=False,
        telemetry=False,
    )
    question = "Q" * 700
    agent.run(question)
    assert calls == [question[:500]] and not knowledge.calls
    refs = [m for m in model.seen[0] if m.name == "knowledge_references"]
    if status is None:
        assert not refs
    else:
        assert len(refs[0].content.encode()) <= 24000
        payload = json.loads(refs[0].content.split("\n")[1])
        assert payload["availability"] == status


def test_message_alias_preserves_all_construction_and_copy_paths():
    message = Message(role="user", content="evidence", add_to_history=False)
    assert not message.add_to_agent_memory
    assert not Message.model_validate(message.model_dump()).add_to_history
    assert "add_to_history" not in message.model_dump()
    for copied in (
        copy.copy(message),
        copy.deepcopy(message),
        message.model_copy(),
        Message.model_construct(role="user", add_to_history=False),
    ):
        assert not copied.add_to_history
    assert message.model_copy(update={"add_to_history": True}).add_to_agent_memory
    message.add_to_history = True
    assert message.add_to_agent_memory
    message.add_to_agent_memory = False
    assert not message.add_to_history
    assert Message.from_dict(message.to_dict()).add_to_history
    for construct in (Message, Message.model_construct, lambda **kw: message.model_copy(update=kw)):
        with pytest.raises(ValueError):
            construct(role="user", add_to_history=False, add_to_agent_memory=True)


@pytest.mark.parametrize("asynchronous,stream", [(False, False), (False, True), (True, False), (True, True)])
@pytest.mark.parametrize("mode", ["fresh", "disabled", "outage", "denied"])
@pytest.mark.asyncio
async def test_fresh_agent_resumes_persisted_approval_with_current_evidence(tmp_path, asynchronous, stream, mode):
    from agno.db.sqlite import SqliteDb
    from agno.tools import tool

    executed = []

    @tool(requires_confirmation=True)
    def inspect_example() -> str:
        executed.append("approved")
        return "Example read after approval."

    database = str(tmp_path / "checkpoint.db")
    knowledge = RecordingKnowledge(page_store=object())
    first_model = RecordingModel(tool_loop=True)
    agent = Agent(
        id="checkpoint",
        model=first_model,
        db=SqliteDb(db_file=database),
        knowledge=knowledge,
        add_knowledge_to_context=True,
        search_knowledge=False,
        tools=[inspect_example],
        telemetry=False,
    )
    if asynchronous:
        pending = (
            agent.arun("  Keep my original question  ", session_id="saved", stream=True)
            if stream
            else await agent.arun("  Keep my original question  ", session_id="saved")
        )
        if stream:
            _ = [event async for event in pending]
            pending = await agent.aget_last_run_output(session_id="saved")
    else:
        pending = agent.run("  Keep my original question  ", session_id="saved", stream=stream)
        if stream:
            list(pending)
            pending = agent.get_last_run_output(session_id="saved")
    assert pending.is_paused and not executed
    assert all(m.name != "knowledge_references" for m in pending.messages)
    assert pending.tools and pending.tools[0].requires_confirmation
    if mode == "denied":
        pending.requirements[0].reject()
    else:
        pending.requirements[0].confirm()

    # New objects and database connection reconstruct the checkpoint from persisted state.
    fresh_knowledge = RecordingKnowledge(page_store=object())
    fresh_knowledge.revision = "updated while paused"
    if mode == "outage":

        def unavailable(query, **kwargs):
            fresh_knowledge.calls.append(query)
            raise RuntimeError("provider unavailable")

        fresh_knowledge.retrieve = unavailable
    fresh_model = RecordingModel(tool_loop=True)
    resumed = Agent(
        id="checkpoint",
        model=fresh_model,
        db=SqliteDb(db_file=database),
        knowledge=fresh_knowledge,
        add_knowledge_to_context=mode != "disabled",
        search_knowledge=False,
        tools=[inspect_example],
        telemetry=False,
    )
    args = dict(run_id=pending.run_id, session_id="saved", requirements=pending.requirements, stream=stream)
    if asynchronous:
        output = resumed.acontinue_run(**args) if stream else await resumed.acontinue_run(**args)
        if stream:
            _ = [event async for event in output]
    else:
        output = resumed.continue_run(**args)
        if stream:
            list(output)
    assert executed == ([] if mode == "denied" else ["approved"])
    assert fresh_knowledge.calls == ([] if mode in ("denied", "disabled") else ["Keep my original question"])
    assert len(fresh_model.seen) == 1
    messages = fresh_model.seen[0]
    references = [m for m in messages if m.name == "knowledge_references"]
    if mode in ("disabled", "denied"):
        assert not references
    else:
        assert ("unavailable" if mode == "outage" else "updated while paused") in references[0].content
    assert any(m.content == "  Keep my original question  " for m in messages)
    position = next(i for i, m in enumerate(messages) if m.tool_calls)
    assert messages[position + 1].tool_call_id == "call-1"
    assert all(m.name != "knowledge_references" for m in resumed.get_last_run_output(session_id="saved").messages)


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("kind", ["agent", "team"])
@pytest.mark.asyncio
async def test_factory_and_tools_only_custom_retriever(kind, asynchronous):
    from agno.team import Team

    knowledge = RecordingKnowledge(page_store=object())
    factory_calls, queries = [], []

    def factory(run_context):
        factory_calls.append(run_context.run_id)
        return knowledge

    async def custom(query):
        queries.append(query)
        return [Document(content="Custom evidence")]

    model = RecordingModel(tool_loop=True, tool_name="search_knowledge")
    component = (Agent if kind == "agent" else Team)(
        model=model,
        knowledge=factory,
        knowledge_retriever=custom,
        add_knowledge_to_context=False,
        search_knowledge=True,
        telemetry=False,
        **({"members": []} if kind == "team" else {}),
    )
    if asynchronous:
        await component.arun("Question")
    else:
        component.run("Question")
    assert len(factory_calls) == 1 and queries == ["custom query"]
    assert not knowledge.calls
    roster = model.rosters[0]
    assert all(roster.count(name) == 1 for name in ("search_knowledge", "read_knowledge_page", "grep_knowledge_pages"))
    assert any("Custom evidence" in str(m.content) for m in model.seen[-1])
