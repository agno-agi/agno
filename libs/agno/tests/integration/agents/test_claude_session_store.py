"""Real two-process transcript verification, requiring configured Claude credentials."""

import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.skipif(
    os.getenv("AGNO_TEST_CLAUDE_SDK") != "1", reason="Set AGNO_TEST_CLAUDE_SDK=1 with Claude credentials"
)
def test_two_process_resume():
    root = Path(__file__).resolve().parents[5]
    subprocess.run(
        [sys.executable, str(root / "cookbook/frameworks/claude-agent-sdk/session_store.py"), "--verify"],
        check=True,
        timeout=180,
    )
