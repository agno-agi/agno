"""Unit tests for fact supersession on EntityMemoryStore.

The judge is one structured model call in the write path: given the entity's
live facts and the newly stated ones, it marks superseded fact ids with
confidences, and only entries at or above supersession_threshold are retired.
The fake model must subclass Model so the real tool-execution loop runs.
"""

import json
from typing import Any, AsyncIterator, Dict, Iterator, List, Optional, Tuple

import pytest

from agno.learn.config import EntityMemoryConfig
from agno.learn.stores.entity_memory import EntityMemoryStore
from agno.models.base import Model
from agno.models.response import ModelResponse


class RecordingLearningDb:
    """In-memory fake of the learnings table (duplicated per test file - the
    tests/unit/learn directory is not a package)."""

    def __init__(self) -> None:
        self.rows: Dict[str, Dict[str, Any]] = {}
        self._clock = 0

    def get_learning(self, **kwargs: Any) -> Optional[Dict[str, Any]]:
        for row in self.rows.values():
            if (
                row.get("learning_type") == kwargs.get("learning_type")
                and row.get("entity_id") == kwargs.get("entity_id")
                and row.get("entity_type") == kwargs.get("entity_type")
                and row.get("namespace") == kwargs.get("namespace")
            ):
                return row
        return None

    def upsert_learning(self, id: str, **kwargs: Any) -> None:
        existing = self.rows.get(id, {})
        row = {**existing, **kwargs, "learning_id": id}
        self._clock += 1
        row["updated_at"] = self._clock
        self.rows[id] = row

    def get_learnings(self, **kwargs: Any) -> List[Dict[str, Any]]:
        rows = [
            row
            for row in self.rows.values()
            if all(
                kwargs.get(key) is None or row.get(key) == kwargs.get(key)
                for key in ("learning_type", "entity_id", "entity_type", "namespace")
            )
        ]
        rows.sort(key=lambda r: r.get("updated_at", 0), reverse=True)
        limit = kwargs.get("limit")
        return rows[:limit] if limit is not None else rows

    def delete_learning(self, id: str) -> bool:
        return self.rows.pop(id, None) is not None

    def search_learnings(self, query: str, **kwargs: Any) -> List[Dict[str, Any]]:
        limit = kwargs.pop("limit", None)
        for key in ("workflow_id", "session_id", "agent_id", "team_id", "user_id"):
            kwargs.pop(key, None)
        candidates = self.get_learnings(**kwargs)
        variants = {query.lower(), query.lower().replace(" ", "_"), query.lower().replace("_", " ")}
        rows = [row for row in candidates if any(v in json.dumps(row.get("content", {})).lower() for v in variants)]
        return rows[:limit] if limit is not None else rows


class SupersessionJudgeModel(Model):
    """Calls mark_superseded once with a canned verdict, then stops."""

    def __init__(
        self,
        verdict: List[Tuple[str, float]],
        provider_calls: Optional[List[dict]] = None,
        verdict_by_content: Optional[Tuple[str, float]] = None,
    ) -> None:
        super().__init__(id="supersession-judge-test", name="supersession-judge-test", provider="test")
        self.verdict = verdict
        self.provider_calls = provider_calls if provider_calls is not None else []
        self.verdict_by_content = verdict_by_content

    def __deepcopy__(self, memo: dict) -> "SupersessionJudgeModel":
        # Share mutable state so the recorder survives the store's deepcopy
        return type(self)(
            verdict=self.verdict, provider_calls=self.provider_calls, verdict_by_content=self.verdict_by_content
        )

    def _resolve_verdict(self, messages: Any) -> List[Tuple[str, float]]:
        if self.verdict_by_content is None:
            return self.verdict
        # Find the fact id whose content contains the marker, judge that id.
        marker, confidence = self.verdict_by_content
        user_text = next(m.content for m in messages if m.role == "user")
        for line in user_text.splitlines():
            if marker in line and line.strip().startswith("- ["):
                fact_id = line.strip()[3 : line.strip().index("]")]
                return [(fact_id, confidence)]
        return []

    def _response_for_call(self, messages: Any) -> ModelResponse:
        call_number = len(self.provider_calls) + 1
        self.provider_calls.append({"call": call_number, "messages": messages})
        if call_number == 1:
            verdict = self._resolve_verdict(messages)
            return ModelResponse(
                role="assistant",
                tool_calls=[
                    {
                        "id": "mark-superseded-1",
                        "type": "function",
                        "function": {
                            "name": "mark_superseded",
                            "arguments": json.dumps(
                                {
                                    "fact_ids": [fact_id for fact_id, _ in verdict],
                                    "confidences": [confidence for _, confidence in verdict],
                                }
                            ),
                        },
                    }
                ],
            )
        return ModelResponse(role="assistant", content="Judged.")

    def invoke(self, *args: Any, messages: Any = None, **kwargs: Any) -> ModelResponse:
        return self._response_for_call(messages)

    async def ainvoke(self, *args: Any, messages: Any = None, **kwargs: Any) -> ModelResponse:
        return self._response_for_call(messages)

    def invoke_stream(self, *args: Any, **kwargs: Any) -> Iterator[ModelResponse]:
        raise AssertionError("streaming should not be used")
        yield  # pragma: no cover

    async def ainvoke_stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[ModelResponse]:
        raise AssertionError("streaming should not be used")
        yield  # pragma: no cover

    def _parse_provider_response(self, response: Any, **kwargs: Any) -> ModelResponse:
        return response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response


class RaisingModel(Model):
    def __init__(self) -> None:
        super().__init__(id="raising-test", name="raising-test", provider="test")

    def __deepcopy__(self, memo: dict) -> "RaisingModel":
        return self

    def invoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        raise RuntimeError("judge model unavailable")

    async def ainvoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        raise RuntimeError("judge model unavailable")

    def invoke_stream(self, *args: Any, **kwargs: Any) -> Iterator[ModelResponse]:
        raise AssertionError("streaming should not be used")
        yield  # pragma: no cover

    async def ainvoke_stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[ModelResponse]:
        raise AssertionError("streaming should not be used")
        yield  # pragma: no cover

    def _parse_provider_response(self, response: Any, **kwargs: Any) -> ModelResponse:
        return response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response


def _store_with_judge(db: RecordingLearningDb, model: Model, **config_kwargs: Any) -> EntityMemoryStore:
    return EntityMemoryStore(config=EntityMemoryConfig(db=db, model=model, **config_kwargs))  # type: ignore[arg-type]


@pytest.fixture
def db() -> RecordingLearningDb:
    return RecordingLearningDb()


def test_supersession_retires_contradicted_fact(db: RecordingLearningDb) -> None:
    model = SupersessionJudgeModel(verdict=[], verdict_by_content=("radar is blocked", 0.95))
    store = _store_with_judge(db, model)

    store.remember_about(entity="radar", entity_type="project", facts=["radar is blocked on review"])
    store.remember_about(entity="radar", entity_type="project", facts=["radar shipped"])

    entity = store.get(entity_id="radar", entity_type="project")
    assert entity is not None
    live = entity.live_facts()
    assert [f["content"] for f in live] == ["radar shipped"]
    # Both facts are still in the record; the superseded one carries the marker
    assert len(entity.facts) == 2
    retired = [f for f in entity.facts if f.get("superseded_at")]
    assert len(retired) == 1
    assert retired[0]["content"] == "radar is blocked on review"
    # With one new fact, superseded_by points at the new fact's id
    new_fact_id = live[0]["id"]
    assert retired[0]["superseded_by"] == new_fact_id


def test_supersession_below_threshold_keeps_fact(db: RecordingLearningDb) -> None:
    model = SupersessionJudgeModel(verdict=[], verdict_by_content=("radar is blocked", 0.5))
    store = _store_with_judge(db, model)

    store.remember_about(entity="radar", entity_type="project", facts=["radar is blocked on review"])
    message = store.remember_about(entity="radar", entity_type="project", facts=["radar shipped"])

    assert "Superseded" not in message
    entity = store.get(entity_id="radar", entity_type="project")
    assert entity is not None
    assert len(entity.live_facts()) == 2


def test_supersession_threshold_is_configurable(db: RecordingLearningDb) -> None:
    model = SupersessionJudgeModel(verdict=[], verdict_by_content=("radar is blocked", 0.95))
    store = _store_with_judge(db, model, supersession_threshold=0.99)

    store.remember_about(entity="radar", entity_type="project", facts=["radar is blocked on review"])
    store.remember_about(entity="radar", entity_type="project", facts=["radar shipped"])

    entity = store.get(entity_id="radar", entity_type="project")
    assert entity is not None
    assert len(entity.live_facts()) == 2


def test_judge_skipped_when_entity_is_new(db: RecordingLearningDb) -> None:
    calls: List[dict] = []
    model = SupersessionJudgeModel(verdict=[], provider_calls=calls)
    store = _store_with_judge(db, model)

    store.remember_about(entity="radar", entity_type="project", facts=["first fact"])
    assert calls == []


def test_judge_skipped_when_write_has_no_facts(db: RecordingLearningDb) -> None:
    calls: List[dict] = []
    model = SupersessionJudgeModel(verdict=[], provider_calls=calls)
    store = _store_with_judge(db, model)

    store.remember_about(entity="radar", entity_type="project", facts=["first fact"])
    store.remember_about(entity="radar", entity_type="project", events=["shipped v1"])
    assert calls == []


def test_judge_skipped_without_model(db: RecordingLearningDb) -> None:
    store = EntityMemoryStore(config=EntityMemoryConfig(db=db))  # type: ignore[arg-type]
    store.remember_about(entity="radar", entity_type="project", facts=["a"])
    message = store.remember_about(entity="radar", entity_type="project", facts=["b"])
    assert "Recorded 1 fact(s)" in message


def test_judge_failure_does_not_lose_the_write(db: RecordingLearningDb) -> None:
    store = _store_with_judge(db, RaisingModel())
    store.remember_about(entity="radar", entity_type="project", facts=["first fact"])
    message = store.remember_about(entity="radar", entity_type="project", facts=["second fact"])

    assert "Recorded 1 fact(s)" in message
    entity = store.get(entity_id="radar", entity_type="project")
    assert entity is not None
    assert len(entity.live_facts()) == 2


def test_exact_duplicate_fact_not_appended_and_judge_skipped(db: RecordingLearningDb) -> None:
    calls: List[dict] = []
    model = SupersessionJudgeModel(verdict=[], provider_calls=calls)
    store = _store_with_judge(db, model)

    store.remember_about(entity="radar", entity_type="project", facts=["db: Postgres"])
    message = store.remember_about(entity="radar", entity_type="project", facts=["DB:  Postgres"])

    assert "already-recorded" in message
    assert calls == []  # nothing novel to judge
    entity = store.get(entity_id="radar", entity_type="project")
    assert entity is not None
    assert len(entity.facts) == 1


def test_hallucinated_fact_id_cannot_retire_new_fact(db: RecordingLearningDb) -> None:
    store_no_model = EntityMemoryStore(config=EntityMemoryConfig(db=db))  # type: ignore[arg-type]
    store_no_model.remember_about(entity="radar", entity_type="project", facts=["old fact"])
    entity = store_no_model.get(entity_id="radar", entity_type="project")
    assert entity is not None

    # Judge marks an id that does not belong to any pre-existing fact
    model = SupersessionJudgeModel(verdict=[("not_a_real_id", 0.99)])
    store = _store_with_judge(db, model)
    store.remember_about(entity="radar", entity_type="project", facts=["new fact"])

    entity = store.get(entity_id="radar", entity_type="project")
    assert entity is not None
    assert len(entity.live_facts()) == 2


def test_custom_system_message_reaches_the_judge(db: RecordingLearningDb) -> None:
    calls: List[dict] = []
    model = SupersessionJudgeModel(verdict=[], provider_calls=calls)
    store = _store_with_judge(db, model, system_message="CUSTOM JUDGE PROMPT")

    store.remember_about(entity="radar", entity_type="project", facts=["a"])
    store.remember_about(entity="radar", entity_type="project", facts=["b"])

    assert calls
    system = next(m for m in calls[0]["messages"] if m.role == "system")
    assert system.content == "CUSTOM JUDGE PROMPT"


async def test_async_supersession_retires_contradicted_fact(db: RecordingLearningDb) -> None:
    model = SupersessionJudgeModel(verdict=[], verdict_by_content=("radar is blocked", 0.95))
    store = _store_with_judge(db, model)

    await store.aremember_about(entity="radar", entity_type="project", facts=["radar is blocked on review"])
    message = await store.aremember_about(entity="radar", entity_type="project", facts=["radar shipped"])

    assert "Superseded 1 earlier fact(s)" in message
    entity = await store.aget(entity_id="radar", entity_type="project")
    assert entity is not None
    assert [f["content"] for f in entity.live_facts()] == ["radar shipped"]
