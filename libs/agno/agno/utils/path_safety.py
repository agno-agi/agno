"""Centralized path-safety primitives for filesystem-touching tools.

This module is a SECURITY BOUNDARY. Any tool that joins a directory with
untrusted user input MUST route through one of these helpers.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Union

from agno.exceptions import PathSecurityError
from agno.utils.log import log_error

__all__ = ["safe_join", "safe_join_subpath"]

_WIN_RESERVED = re.compile(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\.|$)", re.IGNORECASE)
_WIN_DRIVE_OR_UNC = re.compile(r"^([A-Za-z]:|\\\\)")


def _validate_filename_chars(filename: str) -> str:
    """Reject control chars (Cc), Windows-reserved names, drive letters, UNC."""
    if any(unicodedata.category(c) == "Cc" for c in filename):
        log_error(f"Security violation: control char in filename {filename!r}")
        raise PathSecurityError(f"Invalid filename (control chars): {filename!r}")
    if _WIN_DRIVE_OR_UNC.match(filename):
        log_error(f"Security violation: Windows drive/UNC in {filename!r}")
        raise PathSecurityError(f"Filename {filename!r} contains drive letter or UNC prefix")
    if _WIN_RESERVED.match(filename):
        log_error(f"Security violation: Windows reserved name {filename!r}")
        raise PathSecurityError(f"Filename {filename!r} is a Windows reserved name")
    return filename


def safe_join(directory: Union[str, Path], filename: str) -> Path:
    """Filename-only safe join.

    Strips any path components from ``filename`` (uses ``Path(filename).name``).
    Use this for filenames received from LLM output (FileGenerationTools, Slack uploads).

    Returns the RESOLVED file path. Raises PathSecurityError on rejection.
    """
    base = Path(directory)
    filename = unicodedata.normalize("NFKC", filename)
    # Strip path components FIRST, then validate (catches "subdir/CON" attack)
    safe = Path(filename).name
    safe = safe.rstrip(". ")
    if not safe.strip() or safe.strip(".") == "":
        log_error(f"Security violation: empty/dot-only filename {filename!r}")
        raise PathSecurityError(f"Invalid filename after sanitization: {filename!r}")
    _validate_filename_chars(safe)  # Validate stripped basename, not raw input
    file_path = base / safe
    try:
        resolved_file = file_path.resolve()
        resolved_dir = base.resolve()
    except OSError as e:
        log_error(f"Security violation: cannot resolve {filename!r}: {e}")
        raise PathSecurityError(f"Cannot resolve path {filename!r}: {e}") from e
    if not resolved_file.is_relative_to(resolved_dir):
        log_error(f"Security violation: path {filename!r} resolves outside {directory}")
        raise PathSecurityError(f"Filename {filename!r} resolves outside directory (possible symlink escape)")
    return resolved_file


def safe_join_subpath(directory: Union[str, Path], subpath: str) -> Path:
    """Multi-segment safe join.

    Allows multi-segment subpaths (e.g., ``"docs/report.md"``) but enforces
    containment via ``resolve()`` + ``is_relative_to()``. Use for tool callers
    that accept relative paths into a base directory (Toolkit._check_path,
    is_safe_path, FileTools, CodingTools).

    Resolves BOTH base and target before containment check (defeats symlinked
    base_dir bypasses). Returns the RESOLVED target path. Raises
    PathSecurityError on rejection.
    """
    if not subpath or not subpath.strip():
        log_error(f"Security violation: empty subpath {subpath!r}")
        raise PathSecurityError(f"Empty subpath: {subpath!r}")
    subpath = unicodedata.normalize("NFKC", subpath)
    if any(unicodedata.category(c) == "Cc" for c in subpath):
        log_error(f"Security violation: control char in subpath {subpath!r}")
        raise PathSecurityError(f"Invalid subpath (control chars): {subpath!r}")
    base = Path(directory)
    target = base / subpath
    try:
        resolved_base = base.resolve()
        resolved_target = target.resolve()
    except OSError as e:
        log_error(f"Security violation: cannot resolve subpath {subpath!r}: {e}")
        raise PathSecurityError(f"Cannot resolve subpath {subpath!r}: {e}") from e
    if not resolved_target.is_relative_to(resolved_base):
        log_error(f"Security violation: subpath {subpath!r} escapes {directory}")
        raise PathSecurityError(f"Subpath {subpath!r} resolves outside {directory} (possible symlink escape)")
    return resolved_target
