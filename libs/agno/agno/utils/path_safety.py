"""Centralized path-safety primitives for filesystem-touching tools.

This module is a SECURITY BOUNDARY. Any tool that joins a directory with
untrusted user input MUST route through one of these helpers.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path, PureWindowsPath
from typing import Union

from agno.exceptions import PathSecurityError
from agno.utils.log import log_error

__all__ = ["safe_join", "safe_join_subpath"]

_WIN_RESERVED = re.compile(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\.|$)", re.IGNORECASE)
_WIN_DRIVE_OR_UNC = re.compile(r"^([A-Za-z]:|\\\\)")


def _has_control_chars(text: str) -> bool:
    """Cross-platform check for Unicode control characters (category Cc)."""
    return any(unicodedata.category(c) == "Cc" for c in text)


def _has_drive_or_unc(text: str) -> bool:
    """Cross-platform check for Windows drive letters / UNC prefixes.

    Uses ``PureWindowsPath`` so the same input is rejected identically on
    POSIX CI and Windows production. The regex is kept as a fast-path /
    documentation of the literal patterns we reject.
    """
    if _WIN_DRIVE_OR_UNC.match(text):
        return True
    pwp = PureWindowsPath(text)
    return bool(pwp.drive) or pwp.is_absolute()


def _validate_segment(segment: str) -> str:
    """Per-segment validation: control chars, drive/UNC, reserved name, MagicDot.

    Used by both ``safe_join`` (called once on the basename) and
    ``safe_join_subpath`` (called per segment after splitting on ``/`` and
    ``\\``). Returns the MagicDot-stripped segment.
    """
    if _has_control_chars(segment):
        log_error(f"Security violation: control char in segment {segment!r}")
        raise PathSecurityError(f"Invalid segment (control chars): {segment!r}")
    if _has_drive_or_unc(segment):
        log_error(f"Security violation: drive/UNC in segment {segment!r}")
        raise PathSecurityError(f"Segment {segment!r} contains drive letter or UNC prefix")
    stripped = segment.rstrip(". ")
    if not stripped:
        log_error(f"Security violation: empty segment after MagicDot strip: {segment!r}")
        raise PathSecurityError(f"Empty segment after MagicDot strip: {segment!r}")
    if _WIN_RESERVED.match(stripped):
        log_error(f"Security violation: Windows reserved name {stripped!r}")
        raise PathSecurityError(f"Segment {segment!r} is a Windows reserved name")
    return stripped


def safe_join(directory: Union[str, Path], filename: str) -> Path:
    """Filename-only safe join.

    Strips any path components from ``filename`` (uses ``Path(filename).name``).
    Use this for filenames received from LLM output (FileGenerationTools, Slack uploads).

    Validation order (CWE-179 compliant: validate before destructive transform):
        1. NFKC normalize the raw input.
        2. Reject control chars on the RAW input (would otherwise be hidden
           by ``Path.name``).
        3. Reject drive letters / UNC on the RAW input (``Path.name`` strips
           the drive on Windows, hiding the attack).
        4. Strip path components via ``Path(filename).name`` and reject
           empty / dot-only basenames.
        5. ``_validate_segment`` on the basename (control chars + drive/UNC
           re-check + MagicDot strip + Windows reserved name).
        6. Resolve and verify containment in ``directory``.

    Returns the RESOLVED file path. Raises PathSecurityError on rejection.
    """
    base = Path(directory)
    filename = unicodedata.normalize("NFKC", filename)
    if _has_control_chars(filename):
        log_error(f"Security violation: control char in filename {filename!r}")
        raise PathSecurityError(f"Invalid filename (control chars): {filename!r}")
    if _has_drive_or_unc(filename):
        log_error(f"Security violation: Windows drive/UNC in {filename!r}")
        raise PathSecurityError(f"Filename {filename!r} contains drive letter or UNC prefix")
    safe = Path(filename).name.rstrip(". ")
    if not safe or safe.strip(".") == "":
        log_error(f"Security violation: empty/dot-only filename {filename!r}")
        raise PathSecurityError(f"Invalid filename after sanitization: {filename!r}")
    safe = _validate_segment(safe)
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

    Validation order:
        1. Reject empty/whitespace-only and NFKC-normalize.
        2. Reject control chars on the raw subpath.
        3. Reject absolute paths / drive letters / UNC via ``PureWindowsPath``
           (cross-platform).
        4. Per-segment validation (control chars, drive/UNC, MagicDot strip,
           Windows reserved names) — applied to every non-empty / non-``.``
           segment after splitting on both ``/`` and ``\\``.
        5. Resolve BOTH base and target; verify containment (defeats
           symlinked base_dir bypasses).

    Returns the RESOLVED target path. Raises PathSecurityError on rejection.
    """
    if not subpath or not subpath.strip():
        log_error(f"Security violation: empty subpath {subpath!r}")
        raise PathSecurityError(f"Empty subpath: {subpath!r}")
    subpath = unicodedata.normalize("NFKC", subpath)
    if _has_control_chars(subpath):
        log_error(f"Security violation: control char in subpath {subpath!r}")
        raise PathSecurityError(f"Invalid subpath (control chars): {subpath!r}")
    pwp = PureWindowsPath(subpath)
    if pwp.drive or pwp.is_absolute():
        log_error(f"Security violation: subpath must be relative: {subpath!r}")
        raise PathSecurityError(f"Subpath must be relative (no drive/absolute): {subpath!r}")
    # Skip empty (from "//" or trailing "/"), "." (current dir), and ".." (parent).
    # ".." is a legitimate traversal marker — the downstream resolve() +
    # is_relative_to() containment check catches actual escapes.
    for segment in subpath.replace("\\", "/").split("/"):
        if segment in ("", ".", ".."):
            continue
        _validate_segment(segment)
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
