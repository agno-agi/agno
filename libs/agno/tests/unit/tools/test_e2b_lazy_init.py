"""Unit tests for E2BTools lazy sandbox initialization (issue #7215)."""

import sys
from importlib import reload
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Test 1 — no sandbox created at construction time
# ---------------------------------------------------------------------------


def test_lazy_init_no_sandbox_on_import():
    """Sandbox.create must NOT be called when E2BTools is merely instantiated."""
    mock_sandbox = MagicMock()
    mock_sandbox.id = "sbx-1"
    mock_create = MagicMock(return_value=mock_sandbox)

    mock_e2b_module = MagicMock()
    mock_e2b_module.Sandbox = MagicMock(create=mock_create)

    with patch.dict("sys.modules", {"e2b_code_interpreter": mock_e2b_module}):
        import agno.tools.e2b as e2b_module

        reload(e2b_module)

        _tools = e2b_module.E2BTools(api_key="fake-key")

    # The sandbox factory must not have been called yet
    mock_create.assert_not_called(), "Sandbox.create was called eagerly — lazy init broken!"


# ---------------------------------------------------------------------------
# Test 2 — sandbox created only when a tool method is first called
# ---------------------------------------------------------------------------


def test_lazy_init_sandbox_created_on_use():
    """Sandbox.create must be called exactly once, on first tool-method access."""
    mock_sandbox = MagicMock()
    mock_sandbox.id = "sbx-lazy"
    mock_sandbox.run_code.return_value = MagicMock(error=None, results=[], logs="")
    mock_create = MagicMock(return_value=mock_sandbox)

    mock_e2b_module = MagicMock()
    mock_e2b_module.Sandbox = MagicMock(create=mock_create)

    with patch.dict("sys.modules", {"e2b_code_interpreter": mock_e2b_module}):
        import agno.tools.e2b as e2b_module

        reload(e2b_module)

        tools = e2b_module.E2BTools(api_key="fake-key")

        # Still not created after construction
        mock_create.assert_not_called()

        # Trigger first tool call via sandbox property
        _ = tools.sandbox

    # Now it must have been created exactly once
    mock_create.assert_called_once()


# ---------------------------------------------------------------------------
# Test 3 — close() skips kill if sandbox was never started
# ---------------------------------------------------------------------------


def test_close_skips_kill_when_sandbox_never_started():
    """close() must not call Sandbox.create or sandbox.kill if no tool was ever called."""
    mock_sandbox = MagicMock()
    mock_sandbox.id = "sbx-3"
    mock_create = MagicMock(return_value=mock_sandbox)

    mock_e2b_module = MagicMock()
    mock_e2b_module.Sandbox = MagicMock(create=mock_create)

    with patch.dict("sys.modules", {"e2b_code_interpreter": mock_e2b_module}):
        import agno.tools.e2b as e2b_module

        reload(e2b_module)

        tools = e2b_module.E2BTools(api_key="fake-key")
        result = tools.close()

    # Sandbox was never created — close() should be a no-op
    mock_create.assert_not_called()
    assert "never started" in result or "closed" in result.lower()
