"""Unit tests for ToolAuditHook."""

import json
import os
import tempfile
from unittest.mock import MagicMock

import pytest

from agno.hooks.audit import ToolAuditHook

# ---------------------------------------------------------------------------
# Init Tests
# ---------------------------------------------------------------------------


class TestToolAuditHookInit:
    def test_init_with_file(self):
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            hook = ToolAuditHook(log_file=f.name)
            assert hook.log_file == f.name
            os.unlink(f.name)

    def test_init_with_callback(self):
        cb = MagicMock()
        hook = ToolAuditHook(callback=cb)
        assert hook.callback is cb

    def test_init_requires_file_or_callback(self):
        with pytest.raises(ValueError, match="at least one"):
            ToolAuditHook()

    def test_init_defaults(self):
        cb = MagicMock()
        hook = ToolAuditHook(callback=cb)
        assert hook.log_arguments is True
        assert hook.log_results is True
        assert hook.max_result_length == 1000
        assert hook.include_tools is None
        assert hook.exclude_tools is None


# ---------------------------------------------------------------------------
# Filtering Tests
# ---------------------------------------------------------------------------


class TestFiltering:
    def test_include_tools(self):
        cb = MagicMock()
        hook = ToolAuditHook(callback=cb, include_tools=["search"])

        def mock_tool(**kwargs):
            return "result"

        # Included tool — should log
        hook("search", mock_tool, {"q": "test"})
        assert cb.call_count == 1

        # Excluded tool — should not log
        hook("other_tool", mock_tool, {"q": "test"})
        assert cb.call_count == 1  # Still 1

    def test_exclude_tools(self):
        cb = MagicMock()
        hook = ToolAuditHook(callback=cb, exclude_tools=["internal_tool"])

        def mock_tool(**kwargs):
            return "result"

        # Not excluded — should log
        hook("search", mock_tool, {"q": "test"})
        assert cb.call_count == 1

        # Excluded — should not log
        hook("internal_tool", mock_tool, {"q": "test"})
        assert cb.call_count == 1  # Still 1

    def test_filtered_tool_still_executes(self):
        cb = MagicMock()
        hook = ToolAuditHook(callback=cb, include_tools=["allowed"])

        call_count = 0

        def mock_tool(**kwargs):
            nonlocal call_count
            call_count += 1
            return "done"

        # Not in include list — should still execute, just not log
        result = hook("not_allowed", mock_tool, {})
        assert result == "done"
        assert call_count == 1
        assert cb.call_count == 0


# ---------------------------------------------------------------------------
# Logging Tests
# ---------------------------------------------------------------------------


class TestLogging:
    def test_logs_success(self):
        cb = MagicMock()
        hook = ToolAuditHook(callback=cb)

        def mock_tool(**kwargs):
            return '{"data": "hello"}'

        hook("my_tool", mock_tool, {"arg1": "val1"})

        record = cb.call_args[0][0]
        assert record["tool_name"] == "my_tool"
        assert record["status"] == "success"
        assert record["arguments"] == {"arg1": "val1"}
        assert "result" in record
        assert "duration_ms" in record
        assert "timestamp" in record
        assert "error" not in record

    def test_logs_error(self):
        cb = MagicMock()
        hook = ToolAuditHook(callback=cb)

        def failing_tool(**kwargs):
            raise RuntimeError("connection failed")

        with pytest.raises(RuntimeError, match="connection failed"):
            hook("bad_tool", failing_tool, {"x": 1})

        record = cb.call_args[0][0]
        assert record["tool_name"] == "bad_tool"
        assert record["status"] == "error"
        assert "connection failed" in record["error"]
        assert "duration_ms" in record

    def test_no_arguments_when_disabled(self):
        cb = MagicMock()
        hook = ToolAuditHook(callback=cb, log_arguments=False)

        def mock_tool(**kwargs):
            return "ok"

        hook("tool", mock_tool, {"secret": "password123"})

        record = cb.call_args[0][0]
        assert "arguments" not in record

    def test_no_result_when_disabled(self):
        cb = MagicMock()
        hook = ToolAuditHook(callback=cb, log_results=False)

        def mock_tool(**kwargs):
            return "sensitive data"

        hook("tool", mock_tool, {})

        record = cb.call_args[0][0]
        assert "result" not in record

    def test_result_truncation(self):
        cb = MagicMock()
        hook = ToolAuditHook(callback=cb, max_result_length=20)

        def mock_tool(**kwargs):
            return "x" * 100

        hook("tool", mock_tool, {})

        record = cb.call_args[0][0]
        assert len(record["result"]) < 100
        assert "truncated" in record["result"]

    def test_no_truncation_when_disabled(self):
        cb = MagicMock()
        hook = ToolAuditHook(callback=cb, max_result_length=0)

        long_result = "x" * 5000

        def mock_tool(**kwargs):
            return long_result

        hook("tool", mock_tool, {})

        record = cb.call_args[0][0]
        assert record["result"] == long_result

    def test_duration_is_positive(self):
        cb = MagicMock()
        hook = ToolAuditHook(callback=cb)

        def mock_tool(**kwargs):
            return "ok"

        hook("tool", mock_tool, {})

        record = cb.call_args[0][0]
        assert record["duration_ms"] >= 0

    def test_timestamp_is_utc_iso(self):
        cb = MagicMock()
        hook = ToolAuditHook(callback=cb)

        def mock_tool(**kwargs):
            return "ok"

        hook("tool", mock_tool, {})

        record = cb.call_args[0][0]
        # Should be parseable as ISO format
        from datetime import datetime

        dt = datetime.fromisoformat(record["timestamp"])
        assert dt is not None


# ---------------------------------------------------------------------------
# File Output Tests
# ---------------------------------------------------------------------------


class TestFileOutput:
    def test_writes_jsonl(self):
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False, mode="w") as f:
            log_path = f.name

        try:
            hook = ToolAuditHook(log_file=log_path)

            def mock_tool(**kwargs):
                return "result1"

            hook("tool_a", mock_tool, {"key": "val"})
            hook("tool_b", mock_tool, {})

            with open(log_path) as f:
                lines = f.readlines()

            assert len(lines) == 2
            record1 = json.loads(lines[0])
            record2 = json.loads(lines[1])
            assert record1["tool_name"] == "tool_a"
            assert record2["tool_name"] == "tool_b"
        finally:
            os.unlink(log_path)

    def test_appends_to_existing_file(self):
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False, mode="w") as f:
            f.write('{"existing": true}\n')
            log_path = f.name

        try:
            hook = ToolAuditHook(log_file=log_path)

            def mock_tool(**kwargs):
                return "ok"

            hook("new_tool", mock_tool, {})

            with open(log_path) as f:
                lines = f.readlines()

            assert len(lines) == 2
            assert json.loads(lines[0])["existing"] is True
            assert json.loads(lines[1])["tool_name"] == "new_tool"
        finally:
            os.unlink(log_path)

    def test_creates_parent_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = os.path.join(tmpdir, "subdir", "audit.jsonl")
            hook = ToolAuditHook(log_file=log_path)

            def mock_tool(**kwargs):
                return "ok"

            hook("tool", mock_tool, {})

            assert os.path.exists(log_path)
            with open(log_path) as f:
                record = json.loads(f.readline())
            assert record["tool_name"] == "tool"


# ---------------------------------------------------------------------------
# Dual Output Tests
# ---------------------------------------------------------------------------


class TestDualOutput:
    def test_file_and_callback(self):
        cb = MagicMock()
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False, mode="w") as f:
            log_path = f.name

        try:
            hook = ToolAuditHook(log_file=log_path, callback=cb)

            def mock_tool(**kwargs):
                return "ok"

            hook("tool", mock_tool, {})

            # Callback was called
            assert cb.call_count == 1

            # File was written
            with open(log_path) as f:
                lines = f.readlines()
            assert len(lines) == 1
        finally:
            os.unlink(log_path)


# ---------------------------------------------------------------------------
# Error Resilience Tests
# ---------------------------------------------------------------------------


class TestErrorResilience:
    def test_callback_error_does_not_break_tool(self):
        def bad_callback(record):
            raise RuntimeError("callback crashed")

        hook = ToolAuditHook(callback=bad_callback)

        def mock_tool(**kwargs):
            return "ok"

        # Should not raise even though callback fails
        result = hook("tool", mock_tool, {})
        assert result == "ok"

    def test_file_write_error_does_not_break_tool(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = os.path.join(tmpdir, "audit.jsonl")
            hook = ToolAuditHook(log_file=log_path)
            # Point to an unwritable path after init
            hook.log_file = "/dev/null/impossible/audit.jsonl"

            def mock_tool(**kwargs):
                return "ok"

            # Should not raise even though file write fails
            result = hook("tool", mock_tool, {})
            assert result == "ok"

    def test_tool_error_still_logs(self):
        cb = MagicMock()
        hook = ToolAuditHook(callback=cb)

        def failing_tool(**kwargs):
            raise ValueError("bad input")

        with pytest.raises(ValueError):
            hook("tool", failing_tool, {})

        # Should still have logged the error
        assert cb.call_count == 1
        record = cb.call_args[0][0]
        assert record["status"] == "error"


# ---------------------------------------------------------------------------
# Fail on Log Error Tests
# ---------------------------------------------------------------------------


class TestFailOnLogError:
    def test_callback_error_raises_when_fail_on_log_error(self):
        def bad_callback(record):
            raise RuntimeError("callback crashed")

        hook = ToolAuditHook(callback=bad_callback, fail_on_log_error=True)

        def mock_tool(**kwargs):
            return "ok"

        with pytest.raises(RuntimeError, match="audit callback failed"):
            hook("tool", mock_tool, {})

    def test_file_error_raises_when_fail_on_log_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = os.path.join(tmpdir, "audit.jsonl")
            hook = ToolAuditHook(log_file=log_path, fail_on_log_error=True)
            hook.log_file = "/dev/null/impossible/audit.jsonl"

            def mock_tool(**kwargs):
                return "ok"

            with pytest.raises(RuntimeError, match="failed to write audit log"):
                hook("tool", mock_tool, {})

    def test_silent_by_default(self):
        def bad_callback(record):
            raise RuntimeError("callback crashed")

        hook = ToolAuditHook(callback=bad_callback, fail_on_log_error=False)

        def mock_tool(**kwargs):
            return "ok"

        # Should NOT raise
        result = hook("tool", mock_tool, {})
        assert result == "ok"


# ---------------------------------------------------------------------------
# Extract Subject Tests
# ---------------------------------------------------------------------------


class TestExtractSubject:
    def test_subject_added_to_record(self):
        cb = MagicMock()
        hook = ToolAuditHook(
            callback=cb,
            extract_subject=lambda name, args: args.get("sobject"),
        )

        def mock_tool(**kwargs):
            return "ok"

        hook("create_record", mock_tool, {"sobject": "Account", "data": "{}"})

        record = cb.call_args[0][0]
        assert record["subject"] == "Account"

    def test_subject_not_added_when_none(self):
        cb = MagicMock()
        hook = ToolAuditHook(
            callback=cb,
            extract_subject=lambda name, args: args.get("record_id"),
        )

        def mock_tool(**kwargs):
            return "ok"

        hook("list_objects", mock_tool, {})

        record = cb.call_args[0][0]
        assert "subject" not in record

    def test_subject_not_added_without_callback(self):
        cb = MagicMock()
        hook = ToolAuditHook(callback=cb)

        def mock_tool(**kwargs):
            return "ok"

        hook("tool", mock_tool, {"record_id": "123"})

        record = cb.call_args[0][0]
        assert "subject" not in record

    def test_subject_extraction_error_does_not_break(self):
        cb = MagicMock()

        def bad_extractor(name, args):
            raise KeyError("boom")

        hook = ToolAuditHook(callback=cb, extract_subject=bad_extractor)

        def mock_tool(**kwargs):
            return "ok"

        # Should not raise
        result = hook("tool", mock_tool, {})
        assert result == "ok"
        assert cb.call_count == 1
        assert "subject" not in cb.call_args[0][0]


# ---------------------------------------------------------------------------
# Fixture Validation Tests
# ---------------------------------------------------------------------------


class TestFixture:
    def test_sample_fixture_is_valid_jsonl(self):
        fixture_path = os.path.join(os.path.dirname(__file__), "..", "..", "fixtures", "tool_audit_sample.jsonl")
        with open(fixture_path) as f:
            lines = f.readlines()

        assert len(lines) >= 3
        for line in lines:
            record = json.loads(line)
            assert "timestamp" in record
            assert "tool_name" in record
            assert "status" in record
            assert record["status"] in ("success", "error")
