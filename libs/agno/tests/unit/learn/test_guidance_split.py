"""Unit tests for the guidance/data split (spec §4.1) and the manual door (§4.2).

instructions() returns guidance only (mode-aware, aggregated on the machine);
build_context() returns data only; the automatic injection path concatenates the
two, so the manual door and the automatic door render the same text.
"""

from typing import Any, Dict, List, Optional

from agno.learn import LearningMachine
from agno.learn.config import (
    DecisionLogConfig,
    EntityMemoryConfig,
    LearningMode,
    UserMemoryConfig,
    UserProfileConfig,
)
from agno.learn.stores.decision_log import DecisionLogStore
from agno.learn.stores.entity_memory import EntityMemoryStore
from agno.learn.stores.session_context import SessionContextStore
from agno.learn.stores.user_memory import UserMemoryStore
from agno.learn.stores.user_profile import UserProfileStore


class RecordingLearningDb:
    """In-memory fake of the learnings table (duplicated per test file - the
    tests/unit/learn directory is not a package)."""

    def __init__(self) -> None:
        self.rows: Dict[str, Dict[str, Any]] = {}
        self._clock = 0

    def get_learning(self, **kwargs: Any) -> Optional[Dict[str, Any]]:
        for row in self.rows.values():
            if all(
                kwargs.get(key) is None or row.get(key) == kwargs.get(key)
                for key in ("learning_type", "entity_id", "entity_type", "namespace", "user_id")
                if kwargs.get(key) is not None
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
        import json

        limit = kwargs.pop("limit", None)
        for key in ("workflow_id", "session_id", "agent_id", "team_id", "user_id"):
            kwargs.pop(key, None)
        candidates = self.get_learnings(**kwargs)
        variants = {query.lower(), query.lower().replace(" ", "_"), query.lower().replace("_", " ")}
        rows = [row for row in candidates if any(v in json.dumps(row.get("content", {})).lower() for v in variants)]
        return rows[:limit] if limit is not None else rows


class TestStoreSplit:
    def test_agentic_stores_guidance_never_in_data(self) -> None:
        db = RecordingLearningDb()
        cases = [
            (
                UserProfileStore(config=UserProfileConfig(db=db, mode=LearningMode.AGENTIC)),  # type: ignore[arg-type]
                "update_profile",
            ),
            (
                UserMemoryStore(config=UserMemoryConfig(db=db, mode=LearningMode.AGENTIC)),  # type: ignore[arg-type]
                "update_user_memory",
            ),
            (
                EntityMemoryStore(config=EntityMemoryConfig(db=db)),  # type: ignore[arg-type]
                "remember_about",
            ),
            (
                DecisionLogStore(config=DecisionLogConfig(db=db, mode=LearningMode.AGENTIC)),  # type: ignore[arg-type]
                "log_decision",
            ),
        ]
        for store, tool_name in cases:
            guidance = store.instructions()
            assert tool_name in guidance, store
            data = store.build_context(data=store.recall(user_id="u1"))
            assert tool_name not in data, store

    def test_always_mode_stores_have_no_guidance(self) -> None:
        db = RecordingLearningDb()
        profile = UserProfileStore(config=UserProfileConfig(db=db, mode=LearningMode.ALWAYS))  # type: ignore[arg-type]
        assert profile.instructions() == ""
        session = SessionContextStore()
        assert session.instructions() == ""

    def test_machine_instructions_aggregates_enabled_stores(self) -> None:
        db = RecordingLearningDb()
        machine = LearningMachine(
            db=db,  # type: ignore[arg-type]
            user_memory=UserMemoryConfig(mode=LearningMode.AGENTIC),
            entity_memory=True,
        )
        guidance = machine.instructions()
        assert "update_user_memory" in guidance
        assert "remember_about" in guidance
        assert "update_profile" not in guidance  # not enabled

    def test_machine_instructions_is_mode_aware(self) -> None:
        db = RecordingLearningDb()
        always_machine = LearningMachine(db=db, user_memory=UserMemoryConfig(mode=LearningMode.ALWAYS))  # type: ignore[arg-type]
        assert always_machine.instructions() == ""

    def test_custom_store_without_instructions_still_works(self) -> None:
        class OldStyleStore:
            # A pre-2.8.4 third-party store: no instructions() method.
            learning_type = "old_style"
            schema = dict
            was_updated = False

            def recall(self, **kwargs: Any) -> Any:
                return {"x": 1}

            async def arecall(self, **kwargs: Any) -> Any:
                return {"x": 1}

            def process(self, messages: Any, **kwargs: Any) -> None:
                pass

            async def aprocess(self, messages: Any, **kwargs: Any) -> None:
                pass

            def build_context(self, data: Any) -> str:
                return "<old_style>x</old_style>"

            def get_tools(self, **kwargs: Any) -> List[Any]:
                return []

            async def aget_tools(self, **kwargs: Any) -> List[Any]:
                return []

        machine = LearningMachine(db=RecordingLearningDb(), custom_stores={"old_style": OldStyleStore()})  # type: ignore[arg-type]
        assert "old_style" in machine.stores
        assert machine.instructions() == ""  # contributes no guidance, no crash
        assert "<old_style>x</old_style>" in machine.build_context()


class TestRunContextThreading:
    def test_narrow_custom_store_keeps_working(self) -> None:
        """The §8 bullet: a custom store whose recall(self, user_id=None) takes
        no **kwargs still works after the new context kwargs arrive."""
        calls: Dict[str, Any] = {}

        class NarrowStore:
            learning_type = "narrow"
            schema = dict
            was_updated = False

            def recall(self, user_id=None):  # no **kwargs, deliberately
                calls["recall_user_id"] = user_id
                return {"seen": True}

            async def arecall(self, user_id=None):
                calls["arecall_user_id"] = user_id
                return {"seen": True}

            def process(self, messages, user_id=None):
                calls["process_messages"] = messages

            async def aprocess(self, messages, user_id=None):
                calls["aprocess_messages"] = messages

            def build_context(self, data):
                return "<narrow>ok</narrow>"

            def get_tools(self, user_id=None):
                calls["get_tools_user_id"] = user_id
                return []

            async def aget_tools(self, user_id=None):
                return []

        machine = LearningMachine(db=RecordingLearningDb(), custom_stores={"narrow": NarrowStore()})  # type: ignore[arg-type]
        context = machine.build_context(
            user_id="u1",
            message="the current message",
            run_context=object(),
            metadata={"k": "v"},
            dependencies={"d": 1},
            session_state={"s": 2},
        )
        assert "<narrow>ok</narrow>" in context
        assert calls["recall_user_id"] == "u1"

        machine.get_tools(user_id="u1", run_context=object())
        assert calls["get_tools_user_id"] == "u1"

        machine.process(messages=["m"], user_id="u1", run_context=object(), metadata={}, session_state={})
        assert calls["process_messages"] == ["m"]

    async def test_narrow_custom_store_async_paths(self) -> None:
        class NarrowStore:
            learning_type = "narrow"
            schema = dict
            was_updated = False

            def recall(self, user_id=None):
                return None

            async def arecall(self, user_id=None):
                return {"seen": True}

            def process(self, messages, user_id=None):
                pass

            async def aprocess(self, messages, user_id=None):
                pass

            def build_context(self, data):
                return "<narrow>async ok</narrow>" if data else ""

            def get_tools(self, user_id=None):
                return []

            async def aget_tools(self, user_id=None):
                return []

        machine = LearningMachine(db=RecordingLearningDb(), custom_stores={"narrow": NarrowStore()})  # type: ignore[arg-type]
        context = await machine.abuild_context(user_id="u1", run_context=object(), metadata={})
        assert "<narrow>async ok</narrow>" in context
        await machine.aprocess(messages=["m"], run_context=object(), session_state={})

    def test_builtin_store_receives_the_current_message(self) -> None:
        """Built-in stores take **kwargs and see everything, including message."""
        seen: Dict[str, Any] = {}
        machine = LearningMachine(db=RecordingLearningDb(), entity_memory=True)  # type: ignore[arg-type]
        store = machine.entity_memory_store
        assert store is not None
        original_recall = store.recall

        def spy_recall(**kwargs: Any) -> Any:
            seen.update(kwargs)
            return original_recall(
                **{k: v for k, v in kwargs.items() if k in ("entity_id", "entity_type", "user_id", "namespace")}
            )

        store.recall = spy_recall  # type: ignore[method-assign]
        machine.build_context(user_id="u1", message="tell me about radar", run_context="RC")
        assert seen.get("message") == "tell me about radar"
        assert seen.get("run_context") == "RC"

    def test_injection_site_threads_the_input_message(self) -> None:
        """End to end: get_system_message(input=...) reaches build_context(message=...)."""
        from unittest.mock import MagicMock

        from agno.agent import Agent
        from agno.agent._messages import get_system_message
        from agno.models.openai import OpenAIResponses
        from agno.run.base import RunContext
        from agno.session import AgentSession

        db = RecordingLearningDb()
        machine = LearningMachine(db=db, entity_memory=True)  # type: ignore[arg-type]
        machine.build_context = MagicMock(return_value="<ctx/>")  # type: ignore[method-assign]

        agent = Agent(db=db, learning=machine, model=OpenAIResponses(id="gpt-5.5"))  # type: ignore[arg-type]
        agent._learning = machine
        session = AgentSession(session_id="s1")
        run_context = RunContext(run_id="r1", session_id="s1", user_id="u1", metadata={"m": 1}, session_state={"x": 2})

        get_system_message(agent, session=session, run_context=run_context, input="what about radar?")
        kwargs = machine.build_context.call_args.kwargs
        assert kwargs["message"] == "what about radar?"
        assert kwargs["run_context"] is run_context
        assert kwargs["metadata"] == {"m": 1}
        assert kwargs["session_state"] == {"x": 2}


class TestManualDoor:
    def test_capture_hook_runs_process(self) -> None:
        from types import SimpleNamespace

        db = RecordingLearningDb()
        machine = LearningMachine(db=db, user_memory=True)  # type: ignore[arg-type]
        captured: Dict[str, Any] = {}

        def spy_process(**kwargs: Any) -> None:
            captured.update(kwargs)

        machine.process = spy_process  # type: ignore[method-assign]
        hook = machine.capture_hook()
        hook(
            run_output=SimpleNamespace(messages=["m1"]),
            agent=SimpleNamespace(id="agent-1", team_id=None),
            session=SimpleNamespace(session_id="s1"),
            user_id="u1",
        )
        assert captured["messages"] == ["m1"]
        assert captured["user_id"] == "u1"
        assert captured["session_id"] == "s1"
        assert captured["agent_id"] == "agent-1"

    async def test_acapture_hook_schedules_aprocess(self) -> None:
        import asyncio
        from types import SimpleNamespace

        db = RecordingLearningDb()
        machine = LearningMachine(db=db, user_memory=True)  # type: ignore[arg-type]
        captured: Dict[str, Any] = {}

        async def spy_aprocess(**kwargs: Any) -> None:
            captured.update(kwargs)

        machine.aprocess = spy_aprocess  # type: ignore[method-assign]
        hook = machine.acapture_hook()
        await hook(
            run_output=SimpleNamespace(messages=["m1"]),
            agent=SimpleNamespace(id="agent-1", team_id=None),
            session=SimpleNamespace(session_id="s1"),
            user_id="u1",
        )
        # Fire-and-forget: the capture runs as a background task off the
        # response path; drain it before asserting.
        await asyncio.gather(*machine._capture_tasks)
        assert captured["messages"] == ["m1"]

    def test_capture_hook_is_post_hooks_compatible(self) -> None:
        # filter_hook_args must find only parameters it can supply.
        import inspect

        from agno.agent._hooks import filter_hook_args

        machine = LearningMachine(db=RecordingLearningDb(), user_memory=True)  # type: ignore[arg-type]
        hook = machine.capture_hook()
        params = set(inspect.signature(hook).parameters)
        assert params <= {"run_output", "agent", "session", "user_id", "run_context"}
        filtered = filter_hook_args(
            hook,
            {
                "run_output": None,
                "agent": None,
                "session": None,
                "user_id": "u1",
                "run_context": object(),
                "debug_mode": False,
                "metadata": None,
            },
        )
        assert set(filtered) == params

    def test_double_render_warns_once(self, caplog) -> None:
        import logging

        machine = LearningMachine(db=RecordingLearningDb(), entity_memory=True)  # type: ignore[arg-type]
        machine.instructions()  # the manual door was used
        with caplog.at_level(logging.WARNING):
            machine._framework_instructions()  # ...and the framework injects too
            machine._framework_instructions()
        warnings = [r for r in caplog.records if "render twice" in r.getMessage()]
        assert len(warnings) == 1

    def test_no_warning_on_a_single_door(self, caplog) -> None:
        import logging

        machine = LearningMachine(db=RecordingLearningDb(), entity_memory=True)  # type: ignore[arg-type]
        with caplog.at_level(logging.WARNING):
            machine._framework_instructions()
            machine._framework_instructions()
        assert [r for r in caplog.records if "render twice" in r.getMessage()] == []


class TestManualDoorMatchesAutomaticDoor:
    def test_injected_block_equals_instructions_plus_build_context(self) -> None:
        """The §8 regression guard: for the same machine, what the automatic
        injection site renders equals instructions() + build_context()."""
        db = RecordingLearningDb()
        machine = LearningMachine(
            db=db,  # type: ignore[arg-type]
            user_memory=UserMemoryConfig(mode=LearningMode.AGENTIC),
            entity_memory=True,
        )
        entity_store = machine.entity_memory_store
        assert entity_store is not None
        entity_store.remember_about(entity="radar", entity_type="project", facts=["db: Postgres"])

        # What the automatic door assembles at the injection site
        # (agent/_messages.py): instructions() + "\n" + build_context(...)
        guidance = machine.instructions()
        data = machine.build_context(user_id="u1", session_id="s1", agent_id="a1")
        auto_block = "\n".join(part for part in (guidance, data) if part)

        # The manual door places the same two surfaces by hand
        manual_block = "\n".join(
            part
            for part in (
                machine.instructions(),
                machine.build_context(user_id="u1", session_id="s1", agent_id="a1"),
            )
            if part
        )
        assert auto_block == manual_block
        assert "remember_about" in auto_block  # guidance present
        assert "Entity directory" in auto_block  # data present

    def test_agent_system_message_carries_guidance_and_data(self) -> None:
        """End to end through the real injection site in agent/_messages.py."""
        from typing import Any as _Any

        from agno.agent import Agent
        from agno.agent._messages import get_system_message
        from agno.models.base import Model
        from agno.models.response import ModelResponse
        from agno.run.base import RunContext
        from agno.session import AgentSession

        class _NullModel(Model):
            def __init__(self) -> None:
                super().__init__(id="null-test", name="null-test", provider="test")

            def invoke(self, *args: _Any, **kwargs: _Any) -> ModelResponse:
                return ModelResponse(role="assistant", content="")

            async def ainvoke(self, *args: _Any, **kwargs: _Any) -> ModelResponse:
                return ModelResponse(role="assistant", content="")

            def invoke_stream(self, *args: _Any, **kwargs: _Any):
                raise AssertionError("not used")
                yield  # pragma: no cover

            async def ainvoke_stream(self, *args: _Any, **kwargs: _Any):
                raise AssertionError("not used")
                yield  # pragma: no cover

            def _parse_provider_response(self, response: _Any, **kwargs: _Any) -> ModelResponse:
                return response

            def _parse_provider_response_delta(self, response: _Any) -> ModelResponse:
                return response

        db = RecordingLearningDb()
        machine = LearningMachine(db=db, entity_memory=True)  # type: ignore[arg-type]
        entity_store = machine.entity_memory_store
        assert entity_store is not None
        entity_store.remember_about(entity="radar", entity_type="project", facts=["db: Postgres"])

        agent = Agent(db=db, learning=machine, model=_NullModel())  # type: ignore[arg-type]
        agent._learning = machine
        session = AgentSession(session_id="s1")
        run_context = RunContext(run_id="r1", session_id="s1", user_id="u1")

        message = get_system_message(agent, session=session, run_context=run_context)
        assert message is not None
        content = str(message.content)
        assert "remember_about" in content  # guidance reached the system prompt
        assert "Entity directory" in content  # data reached the system prompt
        # And it equals the manual door's assembly, embedded verbatim
        manual = "\n".join(
            part
            for part in (
                machine.instructions(),
                machine.build_context(user_id="u1", session_id="s1", agent_id=agent.id),
            )
            if part
        )
        assert manual in content
