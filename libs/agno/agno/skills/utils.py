"""Utility functions for the skills module."""

import os
import platform
import stat
import subprocess
import sys
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


def parse_shebang(script_path: Path) -> Optional[str]:
    """Parse the shebang line from a script file to determine the interpreter.

    Handles various shebang formats:
    - #!/usr/bin/env python3  -> "python3"
    - #!/usr/bin/python3      -> "python3"
    - #!/bin/bash             -> "bash"
    - #!/usr/bin/env -S node  -> "node"

    Args:
        script_path: Path to the script file.

    Returns:
        The interpreter name (e.g., "python3", "bash") or None if no valid shebang.
    """
    try:
        with open(script_path, "r", encoding="utf-8") as f:
            first_line = f.readline().strip()
    except (OSError, UnicodeDecodeError):
        return None

    if not first_line.startswith("#!"):
        return None

    shebang = first_line[2:].strip()
    if not shebang:
        return None

    parts = shebang.split()

    # Handle /usr/bin/env style shebangs
    if Path(parts[0]).name == "env":
        # Skip any flags (like -S) and get the interpreter
        for part in parts[1:]:
            if not part.startswith("-"):
                return part
        return None

    # Handle direct path shebangs like #!/bin/bash or #!/usr/bin/python3
    # Extract the basename of the path
    interpreter_path = parts[0]
    return Path(interpreter_path).name


def get_interpreter_command(interpreter: str) -> List[str]:
    """Map an interpreter name to a Windows-compatible command.

    Args:
        interpreter: The interpreter name from shebang (e.g., "python3", "bash").

    Returns:
        A list representing the command to invoke the interpreter.
    """
    # Normalize interpreter name
    interpreter_lower = interpreter.lower()

    # Python interpreters - use current Python executable
    if interpreter_lower in ("python", "python3", "python2"):
        return [sys.executable]

    # Other interpreters - pass through as-is
    # This includes: bash, sh, node, ruby, perl, etc.
    # These need to be available in PATH on Windows
    return [interpreter]


def _build_windows_command(script_path: Path, args: List[str]) -> List[str]:
    """Build the command list for executing a script on Windows.

    On Windows, shebang lines are not processed by the OS, so we need to
    parse the shebang and explicitly invoke the interpreter.

    Args:
        script_path: Path to the script file.
        args: Arguments to pass to the script.

    Returns:
        A list representing the full command to execute.
    """
    interpreter = parse_shebang(script_path)

    if interpreter:
        cmd_prefix = get_interpreter_command(interpreter)
        return [*cmd_prefix, str(script_path), *args]

    # Fallback: try direct execution (may fail, but provides clear error)
    return [str(script_path), *args]


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

    On Unix-like systems, scripts are executed directly using their shebang.
    On Windows, the shebang is parsed to determine the interpreter since
    Windows does not natively support shebang lines.

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
    if platform.system() == "Windows":
        cmd = _build_windows_command(script_path, args or [])
    else:
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
