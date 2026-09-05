"""Tests for ``include_user_scoped``, the LearningMachine's incognito switch.

An incognito run must not reach the stores keyed to the individual user. The
namespace- and session-scoped stores belong to the agent rather than the user,
so they stay available.
"""

from typing import Any, Dict, List, Optional

from agno.learn.machine import USER_SCOPED_STORES, LearningMachine


class FakeStore:
    """Minimal LearningStore stand-in that records which calls reached it."""

    def __init__(self, name: str):
        self.name = name
        self.recalled = 0
        self.processed = 0

    def recall(self, **kwargs) -> str:
        self.recalled += 1
        return f"{self.name}-data"

    async def arecall(self, **kwargs) -> str:
        return self.recall(**kwargs)

    def build_context(self, data: Any = None, **kwargs) -> str:
        return str(data) if data else ""

    def get_tools(self, **kwargs) -> List[Any]:
        def _tool() -> str:
            return self.name

        _tool.__name__ = f"{self.name}_tool"
        return [_tool]

    async def aget_tools(self, **kwargs) -> List[Any]:
        return self.get_tools(**kwargs)

    def process(self, **kwargs) -> None:
        self.processed += 1

    async def aprocess(self, **kwargs) -> None:
        self.process(**kwargs)


def _machine() -> tuple[LearningMachine, Dict[str, FakeStore]]:
    stores = {
        name: FakeStore(name)
        for name in ("user_profile", "user_memory", "session_context", "entity_memory", "learned_knowledge")
    }
    machine = LearningMachine()
    machine._stores = dict(stores)  # type: ignore[assignment]
    return machine, stores


def _tool_names(tools: List[Any]) -> List[str]:
    return [getattr(tool, "name", getattr(tool, "__name__", "")) for tool in tools]


class TestUserScopedStoreSet:
    def test_names_the_user_keyed_stores(self):
        assert USER_SCOPED_STORES == frozenset({"user_profile", "user_memory"})


class TestRecall:
    def test_all_stores_recalled_by_default(self):
        machine, stores = _machine()
        results = machine.recall(user_id="u1")
        assert set(results) == set(stores)

    def test_user_scoped_stores_skipped_when_excluded(self):
        machine, stores = _machine()
        results = machine.recall(user_id="u1", include_user_scoped=False)
        assert "user_profile" not in results
        assert "user_memory" not in results
        assert stores["user_profile"].recalled == 0
        assert stores["user_memory"].recalled == 0

    def test_non_user_scoped_stores_still_recalled_when_excluded(self):
        machine, stores = _machine()
        results = machine.recall(user_id="u1", include_user_scoped=False)
        assert {"session_context", "entity_memory", "learned_knowledge"} <= set(results)
        assert stores["learned_knowledge"].recalled == 1


class TestTools:
    def test_user_scoped_tools_withheld_when_excluded(self):
        machine, _ = _machine()
        names = _tool_names(machine.get_tools(user_id="u1", include_user_scoped=False))
        assert "user_profile_tool" not in names
        assert "user_memory_tool" not in names
        assert "learned_knowledge_tool" in names


class TestProcess:
    def test_user_scoped_stores_not_written_when_excluded(self):
        machine, stores = _machine()
        machine.process(messages=[], user_id="u1", include_user_scoped=False)
        assert stores["user_profile"].processed == 0
        assert stores["user_memory"].processed == 0
        assert stores["entity_memory"].processed == 1

    def test_all_stores_written_by_default(self):
        machine, stores = _machine()
        machine.process(messages=[], user_id="u1")
        assert all(store.processed == 1 for store in stores.values())


class TestBuildContext:
    def test_context_omits_user_scoped_data_when_excluded(self):
        machine, _ = _machine()
        context = machine.build_context(user_id="u1", include_user_scoped=False)
        assert "user_profile-data" not in context
        assert "user_memory-data" not in context

    def test_context_includes_user_scoped_data_by_default(self):
        machine, _ = _machine()
        context = machine.build_context(user_id="u1")
        assert "user_profile-data" in context


class TestNoUserIdWarningWhenExcluded:
    def test_missing_user_id_is_not_warned_about_when_excluded(self, monkeypatch):
        """An incognito run has no user to warn about, so the nag must not fire."""
        machine, _ = _machine()
        warned: List[Optional[str]] = []
        monkeypatch.setattr(machine, "_warn_if_user_id_missing", lambda user_id: warned.append(user_id))
        machine.get_tools(user_id=None, include_user_scoped=False)
        assert warned == []
        machine.get_tools(user_id=None)
        assert warned == [None]
