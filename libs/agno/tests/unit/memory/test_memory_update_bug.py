"""BUG-011: Memory update_memory missing user_id/agent_id/team_id.

Sync update_memory passes user_id but NOT agent_id/team_id.
Async update_memory passes NONE of user_id/agent_id/team_id.
Async delete_memory missing user_id (ownership bypass).
"""

import inspect
import re

import pytest


class TestBUG011MemoryUpdateMissingFields:
    @pytest.fixture
    def manager_source(self):
        source = inspect.getsource(__import__("agno.memory.manager", fromlist=["manager"]))
        return source

    def test_sync_add_memory_has_all_fields(self, manager_source):
        """Control: sync add_memory correctly passes all 3 fields."""
        functions = self._get_db_tool_functions(manager_source)
        add_sync = [f for f in functions if f["name"] == "add_memory" and not f["is_async"]]
        assert len(add_sync) == 1
        src = add_sync[0]["source"]
        assert "user_id=" in src
        assert "agent_id=" in src
        assert "team_id=" in src

    def test_sync_update_memory_missing_agent_id_and_team_id(self, manager_source):
        """BUG: sync update_memory has user_id but NOT agent_id/team_id."""
        functions = self._get_db_tool_functions(manager_source)
        update_sync = [f for f in functions if f["name"] == "update_memory" and not f["is_async"]]
        assert len(update_sync) == 1
        src = update_sync[0]["source"]
        assert "user_id=" in src, "sync update_memory should have user_id"
        assert "agent_id=" not in src, "Bug already fixed — agent_id now present"
        assert "team_id=" not in src, "Bug already fixed — team_id now present"

    def test_async_update_memory_missing_all_three(self, manager_source):
        """BUG: async update_memory missing user_id, agent_id, AND team_id."""
        functions = self._get_db_tool_functions(manager_source)
        update_async = [f for f in functions if f["name"] == "update_memory" and f["is_async"]]
        assert len(update_async) == 1
        src = update_async[0]["source"]
        user_memory_calls = re.findall(r"UserMemory\([^)]*\)", src, re.DOTALL)
        assert len(user_memory_calls) >= 1
        for call in user_memory_calls:
            assert "agent_id=" not in call, "Bug already fixed — agent_id now in async update_memory"
            assert "team_id=" not in call, "Bug already fixed — team_id now in async update_memory"
            assert "user_id=" not in call, "Bug already fixed — user_id now in async update_memory"

    def test_async_delete_memory_missing_user_id(self, manager_source):
        """BUG: async delete_memory doesn't pass user_id to delete_user_memory()."""
        functions = self._get_db_tool_functions(manager_source)
        delete_async = [f for f in functions if f["name"] == "delete_memory" and f["is_async"]]
        assert len(delete_async) == 1
        src = delete_async[0]["source"]
        delete_calls = re.findall(r"delete_user_memory\([^)]*\)", src, re.DOTALL)
        assert len(delete_calls) >= 1
        for call in delete_calls:
            assert "user_id=" not in call, "Bug already fixed — user_id now passed"

    def test_sync_delete_memory_has_user_id(self, manager_source):
        """Control: sync delete_memory correctly passes user_id."""
        functions = self._get_db_tool_functions(manager_source)
        delete_sync = [f for f in functions if f["name"] == "delete_memory" and not f["is_async"]]
        assert len(delete_sync) == 1
        src = delete_sync[0]["source"]
        assert "memory_id=memory_id" in src

    def test_async_add_memory_has_all_fields(self, manager_source):
        """Control: async add_memory correctly passes all 3 fields."""
        functions = self._get_db_tool_functions(manager_source)
        add_async = [f for f in functions if f["name"] == "add_memory" and f["is_async"]]
        assert len(add_async) == 1
        src = add_async[0]["source"]
        assert "user_id=" in src
        assert "agent_id=" in src
        assert "team_id=" in src

    def test_field_count_disparity(self, manager_source):
        """Summary: count UserMemory() constructions with missing fields."""
        user_memory_constructions = re.findall(r"UserMemory\([^)]+\)", manager_source, re.DOTALL)
        missing_agent_id = sum(1 for c in user_memory_constructions if "agent_id=" not in c)
        assert missing_agent_id >= 2, (
            f"Expected at least 2 UserMemory() calls missing agent_id, found {missing_agent_id}"
        )

    def _get_db_tool_functions(self, source):
        """Extract inner function definitions from _get_db_tools and _aget_db_tools."""
        results = []
        lines = source.split("\n")
        i = 0
        while i < len(lines):
            stripped = lines[i].strip()
            if stripped.startswith("async def ") or stripped.startswith("def "):
                is_async = stripped.startswith("async def ")
                name_match = re.match(r"(?:async )?def (\w+)\(", stripped)
                if name_match:
                    name = name_match.group(1)
                    if name in ("add_memory", "update_memory", "delete_memory", "clear_memory"):
                        func_lines = [lines[i]]
                        indent = len(lines[i]) - len(lines[i].lstrip())
                        j = i + 1
                        while j < len(lines):
                            if lines[j].strip() and (len(lines[j]) - len(lines[j].lstrip())) <= indent:
                                if not lines[j].strip().startswith("@"):
                                    break
                            func_lines.append(lines[j])
                            j += 1
                        results.append(
                            {
                                "name": name,
                                "is_async": is_async,
                                "source": "\n".join(func_lines),
                            }
                        )
            i += 1
        return results
