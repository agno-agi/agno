from types import MethodType
from typing import TYPE_CHECKING, Any, AsyncIterator, Dict, Iterator, List, Optional, Tuple

import pytest

from agno.agent.agent import Agent
from agno.db.base import AsyncBaseDb
from agno.db.sqlite import SqliteDb
from agno.memory import MemoryManager, UserMemory
from agno.metrics import RunMetrics
from agno.models.base import Model
from agno.models.message import Message, MessageMetrics
from agno.models.response import ModelResponse

if TYPE_CHECKING:
    from agno.tracing.schemas import Span, Trace


class ScriptedModel(Model):
    """Minimal offline model: answers each call with the next of the given responses."""

    def __init__(self, responses: List[ModelResponse]):
        super().__init__(id="test-model", name="test-model", provider="test")
        self.instructions = None
        self._responses = responses

    def get_instructions_for_model(self, *args, **kwargs):
        return None

    def get_system_message_for_model(self, *args, **kwargs):
        return None

    async def aget_instructions_for_model(self, *args, **kwargs):
        return None

    async def aget_system_message_for_model(self, *args, **kwargs):
        return None

    def parse_args(self, *args, **kwargs):
        return {}

    def invoke(self, *args, **kwargs) -> ModelResponse:
        return self._responses.pop(0)

    async def ainvoke(self, *args, **kwargs) -> ModelResponse:
        return self._responses.pop(0)

    def invoke_stream(self, *args, **kwargs) -> Iterator[ModelResponse]:
        yield self._responses.pop(0)

    async def ainvoke_stream(self, *args, **kwargs) -> AsyncIterator[ModelResponse]:
        yield self._responses.pop(0)

    def _parse_provider_response(self, response: Any, **kwargs) -> ModelResponse:
        return response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response


class DummyAsyncMemoryDb(AsyncBaseDb):
    def __init__(self):
        super().__init__()
        self.calls: List[Tuple[str, Optional[str]]] = []
        self._memories: Dict[str, Dict[str, UserMemory]] = {}

    async def table_exists(self, table_name: str) -> bool:
        """Check if a table exists - dummy implementation always returns True."""
        return True

    async def delete_session(self, *args, **kwargs):
        raise NotImplementedError

    async def delete_sessions(self, *args, **kwargs):
        raise NotImplementedError

    async def get_session(self, *args, **kwargs):
        raise NotImplementedError

    async def get_sessions(self, *args, **kwargs):
        raise NotImplementedError

    async def rename_session(self, *args, **kwargs):
        raise NotImplementedError

    async def upsert_session(self, *args, **kwargs):
        raise NotImplementedError

    async def clear_memories(self):
        self._memories.clear()

    async def delete_user_memory(self, memory_id: str, user_id: Optional[str] = None) -> None:
        user = user_id or "default"
        self._memories.get(user, {}).pop(memory_id, None)

    async def delete_user_memories(self, memory_ids, user_id: Optional[str] = None) -> None:
        user = user_id or "default"
        user_memories = self._memories.get(user, {})
        for memory_id in memory_ids:
            user_memories.pop(memory_id, None)

    async def get_all_memory_topics(self, *args, **kwargs) -> List[str]:
        topics = set()
        for memories in self._memories.values():
            for memory in memories.values():
                if memory.topics:
                    topics.update(memory.topics)
        return sorted(topics)

    async def get_user_memory(self, memory_id: str, deserialize: Optional[bool] = True, user_id: Optional[str] = None):
        user = user_id or "default"
        memory = self._memories.get(user, {}).get(memory_id)
        if memory is None:
            return None
        return memory if deserialize else memory.to_dict()

    async def get_user_memories(
        self,
        user_id: Optional[str] = None,
        *args,
        **kwargs,
    ):
        self.calls.append(("get_user_memories", user_id))
        if user_id is None:
            return [memory for memories in self._memories.values() for memory in memories.values()]
        return list(self._memories.get(user_id, {}).values())

    async def get_user_memory_stats(self, *args, **kwargs) -> Tuple[List[Dict], int]:
        return [], 0

    async def upsert_user_memory(self, memory: UserMemory, deserialize: Optional[bool] = True):
        user_id = memory.user_id or "default"
        user_memories = self._memories.setdefault(user_id, {})
        memory_id = memory.memory_id or f"mem-{len(user_memories) + 1}"
        memory.memory_id = memory_id
        user_memories[memory_id] = memory
        return memory if deserialize else memory.to_dict()

    async def get_metrics(self, *args, **kwargs):
        raise NotImplementedError

    async def calculate_metrics(self, *args, **kwargs):
        raise NotImplementedError

    async def delete_knowledge_content(self, *args, **kwargs):
        raise NotImplementedError

    async def get_knowledge_content(self, *args, **kwargs):
        raise NotImplementedError

    async def get_knowledge_contents(self, *args, **kwargs):
        raise NotImplementedError

    async def upsert_knowledge_content(self, *args, **kwargs):
        raise NotImplementedError

    async def create_eval_run(self, *args, **kwargs):
        raise NotImplementedError

    async def delete_eval_runs(self, *args, **kwargs):
        raise NotImplementedError

    async def get_eval_run(self, *args, **kwargs):
        raise NotImplementedError

    async def get_eval_runs(self, *args, **kwargs):
        raise NotImplementedError

    async def rename_eval_run(self, *args, **kwargs):
        raise NotImplementedError

    # --- Traces ---
    async def upsert_trace(self, trace: "Trace") -> None:
        raise NotImplementedError

    async def get_trace(self, trace_id: str):
        raise NotImplementedError

    async def get_traces(
        self,
        run_id: Optional[str] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        status: Optional[str] = None,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
        limit: Optional[int] = 100,
    ) -> List:
        raise NotImplementedError

    async def get_trace_stats(self, *args, **kwargs):
        raise NotImplementedError

    # --- Spans ---
    async def create_span(self, span: "Span") -> None:
        raise NotImplementedError

    async def create_spans(self, spans: List) -> None:
        raise NotImplementedError

    async def get_span(self, span_id: str):
        raise NotImplementedError

    async def get_spans(
        self,
        trace_id: Optional[str] = None,
        parent_span_id: Optional[str] = None,
        limit: Optional[int] = 1000,
    ) -> List:
        raise NotImplementedError

    # -----------

    async def get_latest_schema_version(self, *args, **kwargs):
        raise NotImplementedError

    async def upsert_schema_version(self, *args, **kwargs):
        raise NotImplementedError

    # --- Learnings ---
    async def get_learning(self, *args, **kwargs):
        raise NotImplementedError

    async def upsert_learning(self, *args, **kwargs):
        raise NotImplementedError

    async def delete_learning(self, *args, **kwargs):
        raise NotImplementedError

    async def get_learnings(self, *args, **kwargs):
        raise NotImplementedError


@pytest.mark.asyncio
async def test_acreate_user_memories_with_async_db():
    async_db = DummyAsyncMemoryDb()
    manager = MemoryManager(db=async_db)

    async def fake_acreate_or_update_memories(
        self,
        *,
        messages,
        existing_memories,
        user_id,
        agent_id,
        team_id,
        db,
        update_memories,
        add_memories,
        run_response=None,
        run_metrics=None,
    ):
        await db.upsert_user_memory(
            UserMemory(
                memory=f"Stored: {messages[0].get_content_string()}",
                user_id=user_id,
                memory_id="mem-1",
            )
        )
        return "ok"

    manager.acreate_or_update_memories = MethodType(fake_acreate_or_update_memories, manager)

    result = await manager.acreate_user_memories(message="Remember the milk", user_id="user-1")

    assert result == "ok"
    assert async_db.calls[:2] == [("get_user_memories", "user-1"), ("get_user_memories", "user-1")]

    user_memories = await manager.aget_user_memories(user_id="user-1")
    assert len(user_memories) == 1
    assert user_memories[0].memory.startswith("Stored:")


@pytest.mark.asyncio
async def test_aupdate_memory_task_refreshes_async_db():
    async_db = DummyAsyncMemoryDb()
    manager = MemoryManager(db=async_db)

    async def fake_arun_memory_task(
        self,
        *,
        task,
        existing_memories,
        user_id,
        db,
        delete_memories,
        update_memories,
        add_memories,
        clear_memories,
        run_metrics,
    ):
        await db.upsert_user_memory(
            UserMemory(
                memory=f"Task: {task}",
                user_id=user_id,
                memory_id="task-1",
            )
        )
        return "updated"

    manager.arun_memory_task = MethodType(fake_arun_memory_task, manager)

    response = await manager.aupdate_memory_task(task="Sync state", user_id="user-2")

    assert response == "updated"
    assert async_db.calls[:2] == [("get_user_memories", "user-2"), ("get_user_memories", "user-2")]

    saved_memories = await manager.aget_user_memories(user_id="user-2")
    assert len(saved_memories) == 1
    assert saved_memories[0].memory == "Task: Sync state"


def test_memory_model_tool_loop_counts_every_call(tmp_path):
    """Every call of the memory model's tool loop is counted, not only the last one."""

    usage = MessageMetrics(input_tokens=6, output_tokens=4, total_tokens=10)
    add_memory_call = ModelResponse(
        role="assistant",
        tool_calls=[
            {"id": "call-1", "type": "function", "function": {"name": "add_memory", "arguments": '{"memory": "tea"}'}}
        ],
        response_usage=usage,
    )
    answer = ModelResponse(role="assistant", content="done", response_usage=usage)
    memory_manager = MemoryManager(model=ScriptedModel([add_memory_call, answer]))
    run_metrics = RunMetrics()

    memory_manager.create_or_update_memories(
        messages=[Message(role="user", content="I like tea")],
        existing_memories=[],
        user_id="user-1",
        db=SqliteDb(db_file=str(tmp_path / "memory.db")),
        run_metrics=run_metrics,
    )

    assert run_metrics.total_tokens == 20


def test_agentic_memory_tool_counts_every_memory_model_call(tmp_path):
    """The memory model calls behind the update_user_memory tool are counted on the run that called the tool."""

    usage = MessageMetrics(input_tokens=6, output_tokens=4, total_tokens=10)

    def call(name: str, arguments: str) -> ModelResponse:
        return ModelResponse(
            role="assistant",
            tool_calls=[{"id": f"call-{name}", "type": "function", "function": {"name": name, "arguments": arguments}}],
            response_usage=usage,
        )

    agent = Agent(
        model=ScriptedModel(
            [
                call("update_user_memory", '{"task": "Remember that I like tea"}'),
                ModelResponse(role="assistant", content="noted", response_usage=usage),
            ]
        ),
        memory_manager=MemoryManager(
            model=ScriptedModel(
                [
                    call("add_memory", '{"memory": "tea"}'),
                    ModelResponse(role="assistant", content="done", response_usage=usage),
                ]
            )
        ),
        enable_agentic_memory=True,
        db=SqliteDb(db_file=str(tmp_path / "agent.db")),
        telemetry=False,
    )

    run_output = agent.run("I like tea", user_id="user-1")

    assert run_output.metrics.total_tokens == 40
    assert run_output.metrics.details["memory_model"][0].total_tokens == 20
