"""Real SDK interrupt smoke tests; credentials and installed SDKs are required."""

import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "framework,gate", [("claude-agent-sdk", "AGNO_TEST_CLAUDE_SDK"), ("codex", "AGNO_TEST_CODEX_SDK")]
)
def test_live_cancel(framework, gate):
    if os.getenv(gate) != "1":
        pytest.skip("Set " + gate + "=1 with SDK credentials")
    root = Path(__file__).resolve().parents[5]
    subprocess.run(
        [sys.executable, str(root / "cookbook/frameworks" / framework / "background_cancel.py"), "--verify"],
        check=True,
        timeout=150,
    )
