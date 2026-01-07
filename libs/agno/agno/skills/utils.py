"""Utility functions for the skills module."""

import os
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


def is_safe_path(base_dir: Path, requested_path: str) -> bool:
    """Check if the requested path stays within the base directory.

    This prevents path traversal attacks where a malicious path like
    '../../../etc/passwd' could be used to access files outside the
    intended directory.

    Args:
        base_dir: The base directory that the path must stay within.
        requested_path: The user-provided path to validate.

    Returns:
        True if the path is safe (stays within base_dir), False otherwise.
    """
    try:
        full_path = (base_dir / requested_path).resolve()
        base_resolved = base_dir.resolve()
        return full_path.is_relative_to(base_resolved)
    except (ValueError, OSError):
        return False


def ensure_executable(file_path: Path) -> None:
    """Ensure a file has the executable bit set for the owner.

    Args:
        file_path: Path to the file to make executable.
    """
    current_mode = file_path.stat().st_mode
    if not (current_mode & stat.S_IXUSR):
        os.chmod(file_path, current_mode | stat.S_IXUSR)


@dataclass
class ScriptResult:
    """Result of a script execution."""

    stdout: str
    stderr: str
    returncode: int


def run_script(
    script_path: Path,
    args: Optional[List[str]] = None,
    timeout: int = 30,
    cwd: Optional[Path] = None,
) -> ScriptResult:
    """Execute a script and return the result.

    Args:
        script_path: Path to the script to execute.
        args: Optional list of arguments to pass to the script.
        timeout: Maximum execution time in seconds.
        cwd: Working directory for the script.

    Returns:
        ScriptResult with stdout, stderr, and returncode.

    Raises:
        subprocess.TimeoutExpired: If script exceeds timeout.
        FileNotFoundError: If script or interpreter not found.
    """
    ensure_executable(script_path)
    cmd = [str(script_path), *(args or [])]

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=cwd,
    )

    return ScriptResult(
        stdout=result.stdout,
        stderr=result.stderr,
        returncode=result.returncode,
    )


def read_file_safe(file_path: Path, encoding: str = "utf-8") -> str:
    """Read a file's contents safely.

    Args:
        file_path: Path to the file to read.
        encoding: File encoding (default: utf-8).

    Returns:
        The file contents as a string.

    Raises:
        FileNotFoundError: If file doesn't exist.
        PermissionError: If file can't be read.
        UnicodeDecodeError: If file can't be decoded.
    """
    return file_path.read_text(encoding=encoding)
