from typing import Dict, List, Optional, Tuple

import pytest

from agno.db.base import AsyncBaseDb, BaseDb
from agno.memory import MemoryManager, UserMemory


class DummySyncMemoryDb(BaseDb):
    def __init__(self):
        super().__init__()
        self._memories: Dict[str, Dict[str, UserMemory]] = {}
        self._delete_calls: List[Tuple[str, Optional[str]]] = []

    def table_exists(self, table_name: str) -> bool:
        return True

    def upsert_user_memory(self, memory: UserMemory, deserialize: Optional[bool] = True):
        user_id = memory.user_id or "default"
        user_memories = self._memories.setdefault(user_id, {})
        memory_id = memory.memory_id or f"mem-{len(user_memories) + 1}"
        memory.memory_id = memory_id
        user_memories[memory_id] = memory
        return memory if deserialize else memory.to_dict()

    def delete_user_memory(self, memory_id: str, user_id: Optional[str] = None) -> None:
        self._delete_calls.append((memory_id, user_id))
        user = user_id or "default"
        self._memories.get(user, {}).pop(memory_id, None)

    def clear_memories(self):
        self._memories.clear()

    def delete_user_memories(self, *args, **kwargs):
        raise NotImplementedError

    def get_all_memory_topics(self, *args, **kwargs) -> List[str]:
        raise NotImplementedError

    def get_user_memory(self, *args, **kwargs):
        raise NotImplementedError

    def get_user_memories(self, *args, **kwargs):
        raise NotImplementedError

    def get_user_memory_stats(self, *args, **kwargs) -> Tuple[List[Dict], int]:
        raise NotImplementedError

    def upsert_memories(self, *args, **kwargs):
        raise NotImplementedError

    def delete_session(self, *args, **kwargs):
        raise NotImplementedError

    def delete_sessions(self, *args, **kwargs):
        raise NotImplementedError

    def get_session(self, *args, **kwargs):
        raise NotImplementedError

    def get_sessions(self, *args, **kwargs):
        raise NotImplementedError

    def rename_session(self, *args, **kwargs):
        raise NotImplementedError

    def upsert_session(self, *args, **kwargs):
        raise NotImplementedError

    def upsert_sessions(self, *args, **kwargs):
        raise NotImplementedError

    def get_metrics(self, *args, **kwargs):
        raise NotImplementedError

    def calculate_metrics(self, *args, **kwargs):
        raise NotImplementedError

    def delete_knowledge_content(self, *args, **kwargs):
        raise NotImplementedError

    def get_knowledge_content(self, *args, **kwargs):
        raise NotImplementedError

    def get_knowledge_contents(self, *args, **kwargs):
        raise NotImplementedError

    def upsert_knowledge_content(self, *args, **kwargs):
        raise NotImplementedError

    def create_eval_run(self, *args, **kwargs):
        raise NotImplementedError

    def delete_eval_runs(self, *args, **kwargs):
        raise NotImplementedError

    def get_eval_run(self, *args, **kwargs):
        raise NotImplementedError

    def get_eval_runs(self, *args, **kwargs):
        raise NotImplementedError

    def rename_eval_run(self, *args, **kwargs):
        raise NotImplementedError

    def clear_cultural_knowledge(self, *args, **kwargs):
        raise NotImplementedError

    def delete_cultural_knowledge(self, *args, **kwargs):
        raise NotImplementedError

    def get_cultural_knowledge(self, *args, **kwargs):
        raise NotImplementedError

    def get_all_cultural_knowledge(self, *args, **kwargs):
        raise NotImplementedError

    def upsert_cultural_knowledge(self, *args, **kwargs):
        raise NotImplementedError

    def upsert_trace(self, *args, **kwargs):
        raise NotImplementedError

    def get_trace(self, *args, **kwargs):
        raise NotImplementedError

    def get_traces(self, *args, **kwargs):
        raise NotImplementedError

    def get_trace_stats(self, *args, **kwargs):
        raise NotImplementedError

    def create_span(self, *args, **kwargs):
        raise NotImplementedError

    def create_spans(self, *args, **kwargs):
        raise NotImplementedError

    def get_span(self, *args, **kwargs):
        raise NotImplementedError

    def get_spans(self, *args, **kwargs):
        raise NotImplementedError

    def get_latest_schema_version(self, *args, **kwargs):
        raise NotImplementedError

    def upsert_schema_version(self, *args, **kwargs):
        raise NotImplementedError

    def get_learning(self, *args, **kwargs):
        raise NotImplementedError

    def upsert_learning(self, *args, **kwargs):
        raise NotImplementedError

    def delete_learning(self, *args, **kwargs):
        raise NotImplementedError

    def get_learnings(self, *args, **kwargs):
        raise NotImplementedError


class DummyAsyncMemoryDb(AsyncBaseDb):
    def __init__(self):
        super().__init__()
        self._memories: Dict[str, Dict[str, UserMemory]] = {}
        self._delete_calls: List[Tuple[str, Optional[str]]] = []

    async def table_exists(self, table_name: str) -> bool:
        return True

    async def upsert_user_memory(self, memory: UserMemory, deserialize: Optional[bool] = True):
        user_id = memory.user_id or "default"
        user_memories = self._memories.setdefault(user_id, {})
        memory_id = memory.memory_id or f"mem-{len(user_memories) + 1}"
        memory.memory_id = memory_id
        user_memories[memory_id] = memory
        return memory if deserialize else memory.to_dict()

    async def delete_user_memory(self, memory_id: str, user_id: Optional[str] = None) -> None:
        self._delete_calls.append((memory_id, user_id))
        user = user_id or "default"
        self._memories.get(user, {}).pop(memory_id, None)

    async def clear_memories(self):
        self._memories.clear()

    async def delete_user_memories(self, *args, **kwargs):
        raise NotImplementedError

    async def get_all_memory_topics(self, *args, **kwargs) -> List[str]:
        raise NotImplementedError

    async def get_user_memory(self, *args, **kwargs):
        raise NotImplementedError

    async def get_user_memories(self, *args, **kwargs):
        raise NotImplementedError

    async def get_user_memory_stats(self, *args, **kwargs) -> Tuple[List[Dict], int]:
        raise NotImplementedError

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

    async def upsert_trace(self, *args, **kwargs):
        raise NotImplementedError

    async def get_trace(self, *args, **kwargs):
        raise NotImplementedError

    async def get_traces(self, *args, **kwargs):
        raise NotImplementedError

    async def get_trace_stats(self, *args, **kwargs):
        raise NotImplementedError

    async def create_span(self, *args, **kwargs):
        raise NotImplementedError

    async def create_spans(self, *args, **kwargs):
        raise NotImplementedError

    async def get_span(self, *args, **kwargs):
        raise NotImplementedError

    async def get_spans(self, *args, **kwargs):
        raise NotImplementedError

    async def get_latest_schema_version(self, *args, **kwargs):
        raise NotImplementedError

    async def upsert_schema_version(self, *args, **kwargs):
        raise NotImplementedError

    async def get_learning(self, *args, **kwargs):
        raise NotImplementedError

    async def upsert_learning(self, *args, **kwargs):
        raise NotImplementedError

    async def delete_learning(self, *args, **kwargs):
        raise NotImplementedError

    async def get_learnings(self, *args, **kwargs):
        raise NotImplementedError


def test_sync_update_memory_includes_identity_fields():
    db = DummySyncMemoryDb()
    manager = MemoryManager()

    tools = manager._get_db_tools(
        user_id="user-1",
        db=db,
        input_string="test input",
        agent_id="agent-1",
        team_id="team-1",
    )

    update_fn = next(fn for fn in tools if fn.__name__ == "update_memory")
    result = update_fn(memory_id="mem-1", memory="updated content", topics=["name"])

    assert result == "Memory updated successfully"
    mem = db._memories["user-1"]["mem-1"]
    assert mem.user_id == "user-1"
    assert mem.agent_id == "agent-1"
    assert mem.team_id == "team-1"
    assert mem.memory == "updated content"
    assert mem.topics == ["name"]


@pytest.mark.asyncio
async def test_async_update_memory_includes_identity_fields():
    db = DummyAsyncMemoryDb()
    manager = MemoryManager()

    tools = await manager._aget_db_tools(
        user_id="user-1",
        db=db,
        input_string="test input",
        agent_id="agent-1",
        team_id="team-1",
    )

    update_fn = next(fn for fn in tools if fn.__name__ == "update_memory")
    result = await update_fn(memory_id="mem-1", memory="updated content", topics=["name"])

    assert result == "Memory updated successfully"
    mem = db._memories["user-1"]["mem-1"]
    assert mem.user_id == "user-1"
    assert mem.agent_id == "agent-1"
    assert mem.team_id == "team-1"
    assert mem.memory == "updated content"
    assert mem.topics == ["name"]


@pytest.mark.asyncio
async def test_async_update_memory_with_sync_db_fallback():
    db = DummySyncMemoryDb()
    manager = MemoryManager()

    tools = await manager._aget_db_tools(
        user_id="user-1",
        db=db,
        input_string="test input",
        agent_id="agent-1",
        team_id="team-1",
    )

    update_fn = next(fn for fn in tools if fn.__name__ == "update_memory")
    result = await update_fn(memory_id="mem-1", memory="updated content", topics=["name"])

    assert result == "Memory updated successfully"
    mem = db._memories["user-1"]["mem-1"]
    assert mem.user_id == "user-1"
    assert mem.agent_id == "agent-1"
    assert mem.team_id == "team-1"


@pytest.mark.asyncio
async def test_async_delete_memory_passes_user_id():
    db = DummyAsyncMemoryDb()
    manager = MemoryManager()

    tools = await manager._aget_db_tools(
        user_id="user-1",
        db=db,
        input_string="test input",
        agent_id="agent-1",
        team_id="team-1",
    )

    delete_fn = next(fn for fn in tools if fn.__name__ == "delete_memory")
    result = await delete_fn(memory_id="mem-to-delete")

    assert result == "Memory deleted successfully"
    assert db._delete_calls == [("mem-to-delete", "user-1")]


@pytest.mark.asyncio
async def test_async_delete_memory_with_sync_db_fallback_passes_user_id():
    db = DummySyncMemoryDb()
    manager = MemoryManager()

    tools = await manager._aget_db_tools(
        user_id="user-1",
        db=db,
        input_string="test input",
        agent_id="agent-1",
        team_id="team-1",
    )

    delete_fn = next(fn for fn in tools if fn.__name__ == "delete_memory")
    result = await delete_fn(memory_id="mem-to-delete")

    assert result == "Memory deleted successfully"
    assert db._delete_calls == [("mem-to-delete", "user-1")]
