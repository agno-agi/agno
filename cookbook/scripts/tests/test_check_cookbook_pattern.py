"""Regression tests for the cookbook pattern checker."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

CHECKER_PATH = Path(__file__).parents[1] / "check_cookbook_pattern.py"


def _load_checker() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "check_cookbook_pattern", CHECKER_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


checker = _load_checker()


def _codes(path: Path) -> set[str]:
    return {violation.code for violation in checker.validate_file(path)}


def test_underscore_support_module_may_omit_main_gate(tmp_path: Path) -> None:
    support_module = tmp_path / "_client.py"
    support_module.write_text(
        '''"""Shared HTTP helpers."""

# ---------------------------------------------------------------------------
# Create Helpers
# ---------------------------------------------------------------------------

BASE_URL = "http://localhost:7777"

# ---------------------------------------------------------------------------
# Run Helpers
# ---------------------------------------------------------------------------


def get_base_url() -> str:
    return BASE_URL
''',
        encoding="utf-8",
    )

    assert _codes(support_module) == set()


def test_underscore_support_module_still_fails_other_rules(tmp_path: Path) -> None:
    support_module = tmp_path / "_client.py"
    support_module.write_text(
        """# ---------------------------------------------------------------------------
# Create Helpers
# ---------------------------------------------------------------------------

BASE_URL = "http://localhost:7777"

# ---------------------------------------------------------------------------
# Run Helpers
# ---------------------------------------------------------------------------
""",
        encoding="utf-8",
    )

    codes = _codes(support_module)
    assert "missing_docstring" in codes
    assert "missing_main_gate" not in codes


def test_runnable_module_still_requires_main_gate(tmp_path: Path) -> None:
    runnable_module = tmp_path / "example.py"
    runnable_module.write_text(
        '''"""Runnable example."""

# ---------------------------------------------------------------------------
# Create Example
# ---------------------------------------------------------------------------

message = "hello"

# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------


def run() -> None:
    print(message)
''',
        encoding="utf-8",
    )

    assert _codes(runnable_module) == {"missing_main_gate"}
