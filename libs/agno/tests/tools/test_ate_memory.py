"""Comprehensive tests for AteMemoryTools — unittest only, all subprocess calls mocked."""

from __future__ import annotations

import json
import os
import subprocess
import unittest
from typing import Any
from unittest.mock import MagicMock, patch, PropertyMock


class TestAteMemoryToolsConstruction(unittest.TestCase):
    """Tests for __init__ and constructor behaviour."""

    @patch("ate_memory.shutil.which", return_value="/usr/local/bin/ate")
    def test_constructor_default_flags(self, _mock_which: Any) -> None:
        from ate_memory import AteMemoryTools

        tools = AteMemoryTools(memory_path="/tmp/test.mv2")
        self.assertEqual(tools.memory_path, os.path.abspath("/tmp/test.mv2"))
        self.assertTrue(tools.auto_init)
        # All five tool methods should be registered
        self.assertEqual(len(tools._tools), 5)

    @patch("ate_memory.shutil.which", return_value="/usr/local/bin/ate")
    def test_constructor_disable_all(self, _mock_which: Any) -> None:
        from ate_memory import AteMemoryTools

        tools = AteMemoryTools(
            memory_path="/tmp/test.mv2",
            enable_add=False,
            enable_search=False,
            enable_list=False,
            enable_export=False,
            enable_think=False,
        )
        self.assertEqual(len(tools._tools), 0)

    @patch("ate_memory.shutil.which", return_value="/usr/local/bin/ate")
    def test_constructor_partial_enable(self, _mock_which: Any) -> None:
        from ate_memory import AteMemoryTools

        tools = AteMemoryTools(
            memory_path="/tmp/test.mv2",
            enable_add=True,
            enable_search=True,
            enable_list=False,
            enable_export=False,
            enable_think=False,
        )
        self.assertEqual(len(tools._tools), 2)

    @patch("ate_memory.shutil.which", return_value=None)
    def test_constructor_ate_not_found(self, _mock_which: Any) -> None:
        from ate_memory import AteMemoryTools

        with self.assertRaises(FileNotFoundError) as ctx:
            AteMemoryTools(memory_path="/tmp/test.mv2")
        self.assertIn("ate", str(ctx.exception))

    @patch("ate_memory.shutil.which", return_value="/usr/local/bin/ate")
    def test_constructor_auto_init_false(self, _mock_which: Any) -> None:
        from ate_memory import AteMemoryTools

        tools = AteMemoryTools(memory_path="/tmp/test.mv2", auto_init=False)
        self.assertFalse(tools.auto_init)

    @patch("ate_memory.shutil.which", return_value="/usr/local/bin/ate")
    def test_memory_path_is_absolute(self, _mock_which: Any) -> None:
        from ate_memory import AteMemoryTools

        tools = AteMemoryTools(memory_path="relative/path.mv2")
        self.assertTrue(os.path.isabs(tools.memory_path))

    @patch("ate_memory.shutil.which", return_value="/usr/local/bin/ate")
    def test_toolkit_name(self, _mock_which: Any) -> None:
        from ate_memory import AteMemoryTools

        tools = AteMemoryTools(memory_path="/tmp/test.mv2")
        self.assertEqual(tools.name, "ate_memory")

    @patch("ate_memory.shutil.which", return_value="/usr/local/bin/ate")
    def test_instructions_set(self, _mock_which: Any) -> None:
        from ate_memory import AteMemoryTools

        tools = AteMemoryTools(memory_path="/tmp/test.mv2")
        self.assertIsNotNone(tools.instructions)
        self.assertIn("add_memory", tools.instructions)


class TestAutoInit(unittest.TestCase):
    """Tests for auto-init behaviour."""

    @patch("ate_memory.shutil.which", return_value="/usr/local/bin/ate")
    @patch("ate_memory.os.path.exists", return_value=False)
    @patch("ate_memory.subprocess.run")
    def test_auto_init_creates_file(
        self, mock_run: Any, _mock_exists: Any, _mock_which: Any
    ) -> None:
        from ate_memory import AteMemoryTools

        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="{}", stderr=""
        )
        tools = AteMemoryTools(memory_path="/tmp/test.mv2", auto_init=True)
        tools._ensure_initialized()
        # Should have called ate memory init
        init_call = mock_run.call_args_list[0]
        cmd = init_call[0][0]
        self.assertIn("init", cmd)

    @patch("ate_memory.shutil.which", return_value="/usr/local/bin/ate")
    @patch("ate_memory.os.path.exists", return_value=True)
    @patch("ate_memory.subprocess.run")
    def test_auto_init_skips_existing(
        self, mock_run: Any, _mock_exists: Any, _mock_which: Any
    ) -> None:
        from ate_memory import AteMemoryTools

        tools = AteMemoryTools(memory_path="/tmp/test.mv2", auto_init=True)
        tools._ensure_initialized()
        mock_run.assert_not_called()

    @patch("ate_memory.shutil.which", return_value="/usr/local/bin/ate")
    @patch("ate_memory.os.path.exists", return_value=False)
    @patch("ate_memory.subprocess.run")
    def test_auto_init_disabled_no_call(
        self, mock_run: Any, _mock_exists: Any, _mock_which: Any
    ) -> None:
        from ate_memory import AteMemoryTools

        tools = AteMemoryTools(memory_path="/tmp/test.mv2", auto_init=False)
        tools._ensure_initialized()
        mock_run.assert_not_called()

    @patch("ate_memory.shutil.which", return_value="/usr/local/bin/ate")
    @patch("ate_memory.os.path.exists", return_value=False)
    @patch("ate_memory.subprocess.run")
    def test_auto_init_runs_only_once(
        self, mock_run: Any, _mock_exists: Any, _mock_which: Any
    ) -> None:
        from ate_memory import AteMemoryTools

        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="{}", stderr=""
        )
        tools = AteMemoryTools(memory_path="/tmp/test.mv2", auto_init=True)
        tools._ensure_initialized()
        tools._ensure_initialized()
        # init should only be called once
        self.assertEqual(mock_run.call_count, 1)


class TestAddMemory(unittest.TestCase):
    """Tests for the add_memory tool."""

    def _make_tools(self) -> Any:
        from ate_memory import AteMemoryTools

        with patch("ate_memory.shutil.which", return_value="/usr/local/bin/ate"):
            tools = AteMemoryTools(memory_path="/tmp/test.mv2")
        tools._initialized = True  # skip auto-init
        return tools

    @patch("ate_memory.subprocess.run")
    def test_add_basic(self, mock_run: Any) -> None:
        response_data = {"id": "abc123", "status": "stored"}
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=json.dumps(response_data), stderr=""
        )
        tools = self._make_tools()
        result = tools.add_memory(None, text="Remember this fact")
        self.assertIn("abc123", result)
        cmd = mock_run.call_args[0][0]
        self.assertIn("--text", cmd)
        self.assertIn("Remember this fact", cmd)
        self.assertIn("--format", cmd)
        self.assertIn("json", cmd)

    @patch("ate_memory.subprocess.run")
    def test_add_with_tags(self, mock_run: Any) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout='{"id":"x"}', stderr=""
        )
        tools = self._make_tools()
        tools.add_memory(None, text="tagged memory", tags="work,important")
        cmd = mock_run.call_args[0][0]
        self.assertIn("--tags", cmd)
        self.assertIn("work,important", cmd)

    @patch("ate_memory.subprocess.run")
    def test_add_with_title(self, mock_run: Any) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout='{"id":"x"}', stderr=""
        )
        tools = self._make_tools()
        tools.add_memory(None, text="content", title="My Title")
        cmd = mock_run.call_args[0][0]
        self.assertIn("--title", cmd)
        self.assertIn("My Title", cmd)

    @patch("ate_memory.subprocess.run")
    def test_add_without_optional_args(self, mock_run: Any) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout='{"id":"x"}', stderr=""
        )
        tools = self._make_tools()
        tools.add_memory(None, text="simple")
        cmd = mock_run.call_args[0][0]
        self.assertNotIn("--tags", cmd)
        self.assertNotIn("--title", cmd)

    @patch("ate_memory.subprocess.run")
    def test_add_failure_raises(self, mock_run: Any) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="disk full"
        )
        tools = self._make_tools()
        with self.assertRaises(RuntimeError) as ctx:
            tools.add_memory(None, text="will fail")
        self.assertIn("disk full", str(ctx.exception))


class TestSearchMemory(unittest.TestCase):
    """Tests for the search_memory tool."""

    def _make_tools(self) -> Any:
        from ate_memory import AteMemoryTools

        with patch("ate_memory.shutil.which", return_value="/usr/local/bin/ate"):
            tools = AteMemoryTools(memory_path="/tmp/test.mv2")
        tools._initialized = True
        return tools

    @patch("ate_memory.subprocess.run")
    def test_search_basic(self, mock_run: Any) -> None:
        results = [{"id": "1", "text": "hello", "score": 0.95}]
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=json.dumps(results), stderr=""
        )
        tools = self._make_tools()
        result = tools.search_memory(None, query="hello")
        self.assertIn("hello", result)
        cmd = mock_run.call_args[0][0]
        self.assertIn("--query", cmd)
        self.assertIn("hello", cmd)

    @patch("ate_memory.subprocess.run")
    def test_search_custom_top_k(self, mock_run: Any) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="[]", stderr=""
        )
        tools = self._make_tools()
        tools.search_memory(None, query="test", top_k=10)
        cmd = mock_run.call_args[0][0]
        self.assertIn("--top-k", cmd)
        self.assertIn("10", cmd)

    @patch("ate_memory.subprocess.run")
    def test_search_default_top_k(self, mock_run: Any) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="[]", stderr=""
        )
        tools = self._make_tools()
        tools.search_memory(None, query="test")
        cmd = mock_run.call_args[0][0]
        self.assertIn("5", cmd)

    @patch("ate_memory.subprocess.run")
    def test_search_failure_raises(self, mock_run: Any) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="index corrupt"
        )
        tools = self._make_tools()
        with self.assertRaises(RuntimeError):
            tools.search_memory(None, query="fail")


class TestListMemories(unittest.TestCase):
    """Tests for the list_memories tool."""

    def _make_tools(self) -> Any:
        from ate_memory import AteMemoryTools

        with patch("ate_memory.shutil.which", return_value="/usr/local/bin/ate"):
            tools = AteMemoryTools(memory_path="/tmp/test.mv2")
        tools._initialized = True
        return tools

    @patch("ate_memory.subprocess.run")
    def test_list_returns_info(self, mock_run: Any) -> None:
        info = {"count": 42, "size_bytes": 102400}
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=json.dumps(info), stderr=""
        )
        tools = self._make_tools()
        result = tools.list_memories(None)
        self.assertIn("42", result)
        cmd = mock_run.call_args[0][0]
        self.assertIn("info", cmd)

    @patch("ate_memory.subprocess.run")
    def test_list_includes_path(self, mock_run: Any) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="{}", stderr=""
        )
        tools = self._make_tools()
        tools.list_memories(None)
        cmd = mock_run.call_args[0][0]
        self.assertIn("--path", cmd)
        self.assertIn(tools.memory_path, cmd)


class TestExportMemory(unittest.TestCase):
    """Tests for the export_memory tool."""

    def _make_tools(self) -> Any:
        from ate_memory import AteMemoryTools

        with patch("ate_memory.shutil.which", return_value="/usr/local/bin/ate"):
            tools = AteMemoryTools(memory_path="/tmp/test.mv2")
        tools._initialized = True
        return tools

    @patch("ate_memory.subprocess.run")
    def test_export_returns_data(self, mock_run: Any) -> None:
        memories = [{"id": "1", "text": "first"}, {"id": "2", "text": "second"}]
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=json.dumps(memories), stderr=""
        )
        tools = self._make_tools()
        result = tools.export_memory(None)
        self.assertIn("first", result)
        self.assertIn("second", result)

    @patch("ate_memory.subprocess.run")
    def test_export_cmd_structure(self, mock_run: Any) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="[]", stderr=""
        )
        tools = self._make_tools()
        tools.export_memory(None)
        cmd = mock_run.call_args[0][0]
        self.assertEqual(cmd[0], "ate")
        self.assertIn("export", cmd)
        self.assertIn("--format", cmd)


class TestThink(unittest.TestCase):
    """Tests for the think tool (reasoning scratchpad)."""

    def _make_tools(self) -> Any:
        from ate_memory import AteMemoryTools

        with patch("ate_memory.shutil.which", return_value="/usr/local/bin/ate"):
            tools = AteMemoryTools(memory_path="/tmp/test.mv2")
        tools._initialized = True
        return tools

    def test_think_returns_thought(self) -> None:
        tools = self._make_tools()
        result = tools.think(None, thought="The user wants X because Y")
        self.assertIn("The user wants X because Y", result)

    def test_think_no_subprocess(self) -> None:
        tools = self._make_tools()
        with patch("ate_memory.subprocess.run") as mock_run:
            tools.think(None, thought="internal reasoning")
            mock_run.assert_not_called()

    def test_think_returns_string(self) -> None:
        tools = self._make_tools()
        result = tools.think(None, thought="test")
        self.assertIsInstance(result, str)


class TestRunAteHelper(unittest.TestCase):
    """Tests for the internal _run_ate helper."""

    def _make_tools(self) -> Any:
        from ate_memory import AteMemoryTools

        with patch("ate_memory.shutil.which", return_value="/usr/local/bin/ate"):
            tools = AteMemoryTools(memory_path="/tmp/test.mv2")
        tools._initialized = True
        return tools

    @patch("ate_memory.subprocess.run")
    def test_run_ate_appends_format_json(self, mock_run: Any) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="{}", stderr=""
        )
        tools = self._make_tools()
        tools._run_ate(["memory", "info"])
        cmd = mock_run.call_args[0][0]
        # last two args should be --format json
        self.assertEqual(cmd[-2], "--format")
        self.assertEqual(cmd[-1], "json")

    @patch("ate_memory.subprocess.run")
    def test_run_ate_nonzero_raises_with_stderr(self, mock_run: Any) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=2, stdout="", stderr="something broke"
        )
        tools = self._make_tools()
        with self.assertRaises(RuntimeError) as ctx:
            tools._run_ate(["memory", "info"])
        self.assertIn("something broke", str(ctx.exception))

    @patch("ate_memory.subprocess.run")
    def test_run_ate_nonzero_fallback_message(self, mock_run: Any) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=3, stdout="", stderr=""
        )
        tools = self._make_tools()
        with self.assertRaises(RuntimeError) as ctx:
            tools._run_ate(["memory", "info"])
        self.assertIn("exited with code 3", str(ctx.exception))


class TestFormatJson(unittest.TestCase):
    """Tests for the _format_json helper."""

    def _make_tools(self) -> Any:
        from ate_memory import AteMemoryTools

        with patch("ate_memory.shutil.which", return_value="/usr/local/bin/ate"):
            tools = AteMemoryTools(memory_path="/tmp/test.mv2")
        tools._initialized = True
        return tools

    def test_valid_json_pretty_printed(self) -> None:
        tools = self._make_tools()
        result = tools._format_json('{"a":1}')
        self.assertIn('"a": 1', result)

    def test_invalid_json_returns_raw(self) -> None:
        tools = self._make_tools()
        result = tools._format_json("not json at all")
        self.assertEqual(result, "not json at all")

    def test_strips_whitespace(self) -> None:
        tools = self._make_tools()
        result = tools._format_json("  raw output  ")
        self.assertEqual(result, "raw output")


class TestReturnTypes(unittest.TestCase):
    """All tool methods must return str — Agno convention."""

    def _make_tools(self) -> Any:
        from ate_memory import AteMemoryTools

        with patch("ate_memory.shutil.which", return_value="/usr/local/bin/ate"):
            tools = AteMemoryTools(memory_path="/tmp/test.mv2")
        tools._initialized = True
        return tools

    @patch("ate_memory.subprocess.run")
    def test_add_returns_str(self, mock_run: Any) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout='{"ok":true}', stderr=""
        )
        tools = self._make_tools()
        self.assertIsInstance(tools.add_memory(None, text="x"), str)

    @patch("ate_memory.subprocess.run")
    def test_search_returns_str(self, mock_run: Any) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="[]", stderr=""
        )
        tools = self._make_tools()
        self.assertIsInstance(tools.search_memory(None, query="x"), str)

    @patch("ate_memory.subprocess.run")
    def test_list_returns_str(self, mock_run: Any) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="{}", stderr=""
        )
        tools = self._make_tools()
        self.assertIsInstance(tools.list_memories(None), str)

    @patch("ate_memory.subprocess.run")
    def test_export_returns_str(self, mock_run: Any) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="[]", stderr=""
        )
        tools = self._make_tools()
        self.assertIsInstance(tools.export_memory(None), str)

    def test_think_returns_str(self) -> None:
        tools = self._make_tools()
        self.assertIsInstance(tools.think(None, thought="x"), str)


if __name__ == "__main__":
    unittest.main()
