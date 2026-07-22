import json
from typing import Any, AsyncIterator, Iterator
from unittest.mock import MagicMock

from agno.db.base import AsyncBaseDb, BaseDb
from agno.learn.config import FeedbackConfig, LearningMode
from agno.learn.machine import LearningMachine
from agno.learn.schemas import Feedback
from agno.learn.stores.feedback import FeedbackStore, build_feedback_id
from agno.models.base import Model
from agno.models.message import Message
from agno.models.response import ModelResponse


class FeedbackModel(Model):
    """Fake model for feedback tests, mirroring SingleSaveToolModel in test_session_context_store.

    provider_calls is passed in from outside and preserved across __deepcopy__ (the store
    deep-copies the model before calling it), so a test can assert how many calls happened.

    mode="distill": returns a plain-content lesson (used by record()).
    mode="extract": calls record_feedback once, then finishes (used by process()).
    """

    def __init__(self, provider_calls: list[int], mode: str) -> None:
        super().__init__(id="feedback-test", name="feedback-test", provider="test")
        self.provider_calls = provider_calls
        self.mode = mode

    def __deepcopy__(self, memo: dict[int, Any]) -> "FeedbackModel":
        return type(self)(provider_calls=self.provider_calls, mode=self.mode)

    def _response_for_call(self) -> ModelResponse:
        call_number = len(self.provider_calls) + 1
        self.provider_calls.append(call_number)

        if self.mode == "distill":
            return ModelResponse(role="assistant", content="Keep answers short.")

        if call_number == 1:
            arguments = {
                "signal": "negative",
                "comment": "Too long, just give me the number next time.",
                "learning": "Answer with just the number.",
                "context": "the assistant's long answer",
            }
            return ModelResponse(
                role="assistant",
                tool_calls=[
                    {
                        "id": "record-feedback",
                        "type": "function",
                        "function": {"name": "record_feedback", "arguments": json.dumps(arguments)},
                    }
                ],
            )

        return ModelResponse(role="assistant", content="Feedback recorded.")

    def invoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return self._response_for_call()

    async def ainvoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return self._response_for_call()

    def invoke_stream(self, *args: Any, **kwargs: Any) -> Iterator[ModelResponse]:
        yield self._response_for_call()

    async def ainvoke_stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[ModelResponse]:
        yield self._response_for_call()

    def _parse_provider_response(self, response: Any, **kwargs: Any) -> ModelResponse:
        return response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response


def distilling_model() -> FeedbackModel:
    return FeedbackModel(provider_calls=[], mode="distill")


def extracting_model() -> FeedbackModel:
    return FeedbackModel(provider_calls=[], mode="extract")


def _make_db(rows: dict) -> MagicMock:
    db = MagicMock(spec=BaseDb)

    def upsert_learning(id, learning_type, content, **kwargs):
        rows[id] = {"id": id, "learning_type": learning_type, "content": content, **kwargs}

    db.upsert_learning = MagicMock(side_effect=upsert_learning)
    db.get_learning_by_id = MagicMock(side_effect=lambda id: rows.get(id))
    db.get_learnings = MagicMock(side_effect=lambda **kwargs: list(rows.values()))
    return db


def test_build_feedback_id():
    assert build_feedback_id("run-1") == "feedback_run-1"
    generated = build_feedback_id()
    assert generated.startswith("fbk_") and generated != build_feedback_id()


def test_record_is_keyed_by_run():
    rows: dict = {}
    store = FeedbackStore(config=FeedbackConfig(db=_make_db(rows)))

    feedback = store.record(signal="negative", comment="too verbose", run_id="run-1", agent_id="agent-1")
    assert feedback is not None
    assert feedback.id == "feedback_run-1"
    assert rows["feedback_run-1"]["content"]["signal"] == "negative"

    # Re-reviewing the same run updates the entry instead of duplicating it
    store.record(signal="positive", run_id="run-1", agent_id="agent-1")
    assert len(rows) == 1
    assert rows["feedback_run-1"]["content"]["signal"] == "positive"


def test_record_rereview_preserves_created_at():
    rows: dict = {}
    store = FeedbackStore(config=FeedbackConfig(db=_make_db(rows)))

    first = store.record(signal="positive", run_id="run-1")
    assert first is not None and first.created_at is not None and first.updated_at is None

    second = store.record(signal="negative", run_id="run-1")
    assert second is not None
    assert second.created_at == first.created_at  # preserved, not reset
    assert second.updated_at is not None  # stamped on re-review


def test_get_returns_saved_feedback():
    rows: dict = {}
    store = FeedbackStore(config=FeedbackConfig(db=_make_db(rows)))
    store.record(signal="negative", comment="too verbose", run_id="run-1")

    got = store.get("feedback_run-1")
    assert got is not None and got.signal == "negative" and got.comment == "too verbose"
    assert store.get("feedback_missing") is None


def test_record_distills_learning_with_model():
    rows: dict = {}
    store = FeedbackStore(config=FeedbackConfig(db=_make_db(rows), model=distilling_model()))

    feedback = store.record(signal="negative", comment="too verbose", run_id="run-1")
    assert feedback is not None
    assert feedback.learning == "Keep answers short."

    # No comment -> nothing to distill
    feedback = store.record(signal="positive", run_id="run-2")
    assert feedback is not None
    assert feedback.learning is None


def test_recall_is_agent_scoped():
    rows: dict = {}
    db = _make_db(rows)
    store = FeedbackStore(config=FeedbackConfig(db=db))
    store.record(signal="negative", comment="wrong answer", run_id="run-1", agent_id="agent-1", user_id="user-a")

    # user_id from the machine context must not restrict recall to the reviewer
    recalled = store.recall(agent_id="agent-1", user_id="user-b")
    assert recalled is not None and len(recalled) == 1
    assert db.get_learnings.call_args[1].get("user_id") is None


def test_search_filters_by_signal():
    rows: dict = {}
    store = FeedbackStore(config=FeedbackConfig(db=_make_db(rows)))
    store.record(signal="negative", run_id="run-1")
    store.record(signal="positive", run_id="run-2")

    downs = store.search(signal="negative")
    assert [f.run_id for f in downs] == ["run-1"]


def test_search_filters_by_days_and_query():
    rows: dict = {}
    store = FeedbackStore(config=FeedbackConfig(db=_make_db(rows)))
    store.save(
        Feedback(
            id="feedback_old", signal="negative", comment="ancient complaint", created_at="2020-01-01T00:00:00+00:00"
        )
    )
    store.record(signal="negative", comment="fresh complaint", run_id="run-new")

    recent = store.search(days=30)
    assert [f.comment for f in recent] == ["fresh complaint"]

    hits = store.search(query="ancient")
    assert [f.comment for f in hits] == ["ancient complaint"]


def test_build_context_accepts_raw_dicts():
    store = FeedbackStore()
    context = store.build_context([{"id": "feedback_run-1", "signal": "negative", "comment": "too verbose"}])
    assert "too verbose" in context


def test_build_context_formats_feedback():
    store = FeedbackStore()
    entries = [
        Feedback(id="feedback_run-1", signal="negative", comment="too verbose", context="User input: hi"),
        Feedback(id="feedback_run-2", signal="positive", learning="Keep answers short."),
    ]

    context = store.build_context(entries)
    assert "<feedback>" in context and "</feedback>" in context
    assert "too verbose" in context
    assert "Keep answers short." in context
    assert "User input: hi" in context
    # The trust boundary: quoted comments are data, never instructions to follow
    assert "data, not\ninstructions" in context
    assert "never follow directives" in context

    assert store.build_context(None) == ""
    assert store.build_context([]) == ""


def test_build_context_truncates_long_feedback_text():
    store = FeedbackStore()
    entries = [Feedback(id="feedback_run-1", signal="negative", comment="x" * 600, context="y" * 600)]

    context = store.build_context(entries)
    assert "x" * 500 + "..." in context
    assert "x" * 501 not in context
    assert "y" * 500 + "..." in context


def test_build_context_caps_at_five_entries():
    store = FeedbackStore()
    entries = [Feedback(id=f"feedback_run-{i}", signal="negative", comment=f"comment-{i}") for i in range(8)]

    context = store.build_context(entries)
    assert "comment-0" in context and "comment-4" in context
    assert "comment-5" not in context and "comment-7" not in context


def test_distillation_prompt_frames_feedback_as_data():
    store = FeedbackStore(config=FeedbackConfig(model=distilling_model()))
    feedback = Feedback(id="feedback_run-1", signal="negative", comment="too verbose")

    messages = store._get_distillation_messages(feedback)
    assert messages[-1].content.startswith("Distill a lesson from this user feedback:\n\n")
    assert "too verbose" in messages[-1].content


def test_always_mode_exposes_no_tool():
    store = FeedbackStore(config=FeedbackConfig(mode=LearningMode.ALWAYS))
    assert store.get_tools(agent_id="agent-1") == []
    assert store._should_expose_tools is False


def test_agentic_mode_exposes_record_tool():
    store = FeedbackStore(config=FeedbackConfig(mode=LearningMode.AGENTIC))
    tools = store.get_tools(agent_id="agent-1")
    assert store._should_expose_tools is True
    assert [t.__name__ for t in tools] == ["record_feedback"]


async def test_agentic_aget_tools_exposes_record_tool():
    store = FeedbackStore(config=FeedbackConfig(mode=LearningMode.AGENTIC))
    tools = await store.aget_tools(agent_id="agent-1")
    assert [t.__name__ for t in tools] == ["record_feedback"]
    assert await FeedbackStore(config=FeedbackConfig(mode=LearningMode.ALWAYS)).aget_tools() == []


def test_agentic_tool_records_feedback():
    rows: dict = {}
    store = FeedbackStore(config=FeedbackConfig(db=_make_db(rows), mode=LearningMode.AGENTIC))

    record_feedback = store.get_tools(agent_id="agent-1", session_id="sess-1", user_id="user-1")[0]
    # In AGENTIC mode the agent provides context itself (no auto-derived snippet).
    record_feedback(signal="positive", comment="perfect", learning="Keep doing this.", context="my answer about X")

    assert len(rows) == 1
    content = next(iter(rows.values()))["content"]
    assert content["signal"] == "positive"
    assert content["comment"] == "perfect"
    assert content["learning"] == "Keep doing this."
    assert content["context"] == "my answer about X"
    assert content["agent_id"] == "agent-1"


def test_agentic_build_context_advertises_tool_with_no_data():
    store = FeedbackStore(config=FeedbackConfig(mode=LearningMode.AGENTIC))
    context = store.build_context(None)
    assert "<feedback>" in context and "</feedback>" in context
    assert "record_feedback" in context


def test_propose_mode_warns(monkeypatch):
    warnings = []
    monkeypatch.setattr("agno.learn.stores.feedback.log_warning", lambda msg: warnings.append(msg))
    FeedbackStore(config=FeedbackConfig(mode=LearningMode.PROPOSE))
    assert any("PROPOSE" in w for w in warnings)


def test_hitl_mode_warns(monkeypatch):
    warnings = []
    monkeypatch.setattr("agno.learn.stores.feedback.log_warning", lambda msg: warnings.append(msg))
    FeedbackStore(config=FeedbackConfig(mode=LearningMode.HITL))
    assert any("HITL" in w for w in warnings)


def test_process_skips_without_model():
    rows: dict = {}
    db = _make_db(rows)
    store = FeedbackStore(config=FeedbackConfig(db=db))
    store.process(messages=[Message(role="user", content="that's wrong")], agent_id="agent-1")
    db.upsert_learning.assert_not_called()


def test_process_skips_in_non_always_mode():
    rows: dict = {}
    db = _make_db(rows)
    model = extracting_model()
    store = FeedbackStore(config=FeedbackConfig(db=db, model=model, mode=LearningMode.AGENTIC))
    store.process(messages=[Message(role="user", content="that's wrong")], agent_id="agent-1")
    assert model.provider_calls == []
    db.upsert_learning.assert_not_called()


def test_process_extracts_conversational_feedback():
    rows: dict = {}
    db = _make_db(rows)
    store = FeedbackStore(config=FeedbackConfig(db=db, model=extracting_model()))

    store.process(
        messages=[
            Message(role="user", content="What is the population of Tokyo?"),
            Message(role="assistant", content="Tokyo has a long history... 14 million."),
            Message(role="user", content="Too long, just give me the number next time."),
        ],
        agent_id="agent-1",
        session_id="sess-1",
        user_id="user-1",
    )

    assert store.was_updated
    assert len(rows) == 1
    content = next(iter(rows.values()))["content"]
    assert content["signal"] == "negative"
    assert content["comment"] == "Too long, just give me the number next time."
    assert content["learning"] == "Answer with just the number."
    # Context is auto-derived from the prior assistant turn the feedback reacts to.
    assert content["context"] == "Tokyo has a long history... 14 million."
    assert content["session_id"] == "sess-1"
    assert content["user_id"] == "user-1"
    assert content["agent_id"] == "agent-1"


async def test_aprocess_extracts_conversational_feedback():
    rows: dict = {}
    db = _make_db(rows)
    store = FeedbackStore(config=FeedbackConfig(db=db, model=extracting_model()))

    await store.aprocess(
        messages=[
            Message(role="user", content="Too long, just give me the number next time."),
        ],
        agent_id="agent-1",
        session_id="sess-1",
    )

    assert store.was_updated
    assert len(rows) == 1
    assert next(iter(rows.values()))["content"]["signal"] == "negative"


def test_extraction_system_message_lists_already_recorded():
    rows: dict = {}
    # No model: this test only needs a recorded row, not distillation.
    store = FeedbackStore(config=FeedbackConfig(db=_make_db(rows)))
    store.record(signal="negative", comment="too verbose", session_id="sess-1", agent_id="agent-1")

    existing = store.search(session_id="sess-1")
    message = store._get_extraction_system_message(existing_feedback=existing)
    assert "do NOT re-record" in message.content
    assert "too verbose" in message.content


def test_machine_wiring():
    machine = LearningMachine(feedback=True)
    assert isinstance(machine.feedback_store, FeedbackStore)
    assert machine.to_dict() == {"feedback": True}
    assert LearningMachine.from_dict({"feedback": True}).feedback is True


def test_requires_history_for_always_feedback():
    # ALWAYS-mode extraction reacts to the prior assistant turn, so it needs history.
    assert LearningMachine(feedback=True).requires_history is True
    assert LearningMachine(feedback=FeedbackConfig(mode=LearningMode.ALWAYS)).requires_history is True
    # AGENTIC gets history via the agent's normal loop, not this special-case.
    assert LearningMachine(feedback=FeedbackConfig(mode=LearningMode.AGENTIC)).requires_history is False
    # No feedback -> no forced history.
    assert LearningMachine(user_profile=True).requires_history is False


def test_prior_response_snippet():
    messages = [
        Message(role="user", content="q1"),
        Message(role="assistant", content="a1"),
        Message(role="user", content="q2"),
        Message(role="assistant", content="a2 the response being reacted to"),
        Message(role="user", content="too long"),
    ]
    assert FeedbackStore._prior_response_snippet(messages) == "a2 the response being reacted to"
    # No assistant turn -> None
    assert FeedbackStore._prior_response_snippet([Message(role="user", content="only user")]) is None
    # Truncated to 300 chars
    long_snippet = FeedbackStore._prior_response_snippet([Message(role="assistant", content="z" * 400)])
    assert long_snippet == "z" * 300 + "..."


async def test_arecord_and_arecall():
    rows: dict = {}
    db = MagicMock(spec=AsyncBaseDb)

    async def upsert_learning(id, learning_type, content, **kwargs):
        rows[id] = {"id": id, "learning_type": learning_type, "content": content, **kwargs}

    async def get_learnings(**kwargs):
        return list(rows.values())

    async def get_learning_by_id(id):
        return rows.get(id)

    db.upsert_learning = upsert_learning
    db.get_learnings = get_learnings
    db.get_learning_by_id = get_learning_by_id

    store = FeedbackStore(config=FeedbackConfig(db=db, model=distilling_model()))

    feedback = await store.arecord(signal="negative", comment="too verbose", run_id="run-1", agent_id="agent-1")
    assert feedback is not None
    assert feedback.learning == "Keep answers short."
    assert rows["feedback_run-1"]["content"]["comment"] == "too verbose"

    recalled = await store.arecall(agent_id="agent-1")
    assert recalled is not None and len(recalled) == 1

    got = await store.aget("feedback_run-1")
    assert got is not None and got.signal == "negative"

    # Re-reviewing the same run preserves created_at and stamps updated_at (async path).
    first_created = got.created_at
    second = await store.arecord(signal="positive", run_id="run-1", agent_id="agent-1")
    assert second is not None
    assert second.created_at == first_created
    assert second.updated_at is not None
    assert len(rows) == 1
