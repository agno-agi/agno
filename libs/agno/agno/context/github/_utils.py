"""Shared helpers for GitHubContextProvider."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import List, Optional


def _run_git(
    args: List[str],
    *,
    cwd: Path,
    timeout: int = 60,
    env: Optional[dict] = None,
) -> subprocess.CompletedProcess[str]:
    """Run a git command with capture + timeout. Never raises on non-zero exit."""
    return subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        cwd=str(cwd),
        timeout=timeout,
        env=env,
    )
