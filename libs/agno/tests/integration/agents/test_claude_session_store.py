"""Real transcript mirror and resume verification, requiring configured Claude credentials."""

import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.skipif(
    os.getenv("AGNO_TEST_CLAUDE_SDK") != "1", reason="Set AGNO_TEST_CLAUDE_SDK=1 with Claude credentials"
)
def test_transcript_mirror_and_resume():
    root = Path(__file__).resolve().parents[5]
    subprocess.run(
        [sys.executable, str(root / "cookbook/frameworks/claude-agent-sdk/transcript_store.py")],
        check=True,
        timeout=180,
    )
