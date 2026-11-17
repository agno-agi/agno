"""Tests for the Daytona SDK version bound used by DaytonaTools."""

from __future__ import annotations

import builtins
import importlib
import sys
from pathlib import Path

import pytest

LIBS_AGNO = Path(__file__).resolve().parents[3]
PYPROJECT = LIBS_AGNO / "pyproject.toml"


def test_daytona_extra_pins_sdk_below_v1():
    """`pip install agno[daytona]` must not resolve Daytona SDK 2.x.

    2.0 moved CodeLanguage, Sandbox and CreateSandboxFromSnapshotParams off
    the package root, which is what DaytonaTools still imports.
    """
    text = PYPROJECT.read_text()
    assert 'daytona = ["daytona<1"]' in text
    assert 'daytona = ["daytona"]' not in text


def test_missing_or_incompatible_daytona_hints_supported_version(monkeypatch):
    """The ImportError must name a supported pin, not `pip install daytona`.

    An unbounded hint reinstalls Daytona 2.x (once it is the default), which
    still fails the same root import and looks like a missing package.
    """
    # Isolate from test_daytona.py, which stubs `daytona` in sys.modules.
    for name in list(sys.modules):
        if name == "daytona" or name.startswith("daytona.") or name == "agno.tools.daytona":
            monkeypatch.delitem(sys.modules, name, raising=False)

    real_import = builtins.__import__

    def _hide_daytona(name, *args, **kwargs):
        if name == "daytona" or name.startswith("daytona."):
            raise ImportError("No module named daytona")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _hide_daytona)

    with pytest.raises(ImportError, match=r"pip install 'daytona<1'") as excinfo:
        importlib.import_module("agno.tools.daytona")

    assert "pip install daytona`" not in str(excinfo.value)
    assert "pip install daytona'" not in str(excinfo.value)
