from types import MethodType
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

import pytest

from agno.db.base import AsyncBaseDb
from agno.memory import MemoryManager, UserMemory

if TYPE_CHECKING:
    from agno.tracing.schemas import Span, Trace


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

    async def clear_cultural_knowledge(self, *args, **kwargs):
        raise NotImplementedError

    async def delete_cultural_knowledge(self, *args, **kwargs):
        raise NotImplementedError

    async def get_cultural_knowledge(self, *args, **kwargs):
        raise NotImplementedError

    async def get_all_cultural_knowledge(self, *args, **kwargs):
        raise NotImplementedError

    async def upsert_cultural_knowledge(self, *args, **kwargs):
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
