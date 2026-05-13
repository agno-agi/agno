"""Path-safety helpers for filesystem-touching tools."""

import re
import unicodedata
from pathlib import Path, PureWindowsPath
from typing import Union

from agno.exceptions import PathSecurityError
from agno.utils.log import log_debug

_WIN_RESERVED_RE = re.compile(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\.|$)", re.IGNORECASE)
_WIN_DRIVE_OR_UNC_RE = re.compile(r"^([A-Za-z]:|\\\\)")


def _has_control_chars(text: str) -> bool:
    return any(unicodedata.category(c) == "Cc" for c in text)


def _has_drive_or_unc(text: str) -> bool:
    if _WIN_DRIVE_OR_UNC_RE.match(text):
        return True
    pwp = PureWindowsPath(text)
    return bool(pwp.drive) or pwp.is_absolute()


def _validate_segment(segment: str) -> str:
    if _has_control_chars(segment):
        raise PathSecurityError(f"Invalid path segment: {segment!r}")
    if _has_drive_or_unc(segment):
        raise PathSecurityError(f"Invalid path segment: {segment!r}")
    stripped = segment.rstrip(". ")
    if not stripped:
        raise PathSecurityError(f"Invalid path segment: {segment!r}")
    if _WIN_RESERVED_RE.match(stripped):
        raise PathSecurityError(f"Invalid path segment: {segment!r}")
    return stripped


def sanitize_filename(filename: str) -> str:
    """Validate ``filename`` and return the safe basename.

    Applies the same validation as ``safe_join`` without resolving against
    a directory. Use when the caller needs a sanitized name but no disk
    write happens.
    """
    filename = unicodedata.normalize("NFKC", filename)
    if _has_control_chars(filename):
        raise PathSecurityError(f"Invalid filename: {filename!r}")
    if _has_drive_or_unc(filename):
        raise PathSecurityError(f"Invalid filename: {filename!r}")
    if "/" in filename or "\\" in filename:
        log_debug(f"safe_join discarded path components from {filename!r}")
    safe = Path(filename.replace("\\", "/")).name.rstrip(". ")
    if not safe or safe.strip(".") == "":
        raise PathSecurityError(f"Invalid filename: {filename!r}")
    return _validate_segment(safe)


def safe_join(directory: Union[str, Path], filename: str) -> Path:
    """Join ``directory`` with the sanitized basename of ``filename``.

    Path components in ``filename`` are discarded. Use for filenames
    received from LLM output. For multi-segment paths, use
    ``safe_join_subpath``.
    """
    base = Path(directory)
    safe = sanitize_filename(filename)
    file_path = base / safe
    try:
        resolved_file = file_path.resolve()
        resolved_dir = base.resolve()
    except (OSError, UnicodeEncodeError) as e:
        raise PathSecurityError(f"Cannot resolve path {filename!r}: {e}") from e
    try:
        resolved_file.relative_to(resolved_dir)
    except ValueError:
        raise PathSecurityError(f"Filename {filename!r} resolves outside {directory}") from None
    return resolved_file


def safe_join_subpath(directory: Union[str, Path], subpath: str) -> Path:
    """Join ``directory`` with ``subpath``, preserving multi-segment paths.

    Allows inputs like ``"docs/report.md"`` and enforces containment by
    resolving both ``directory`` and the target before comparison.
    """
    if not subpath or not subpath.strip():
        raise PathSecurityError(f"Invalid subpath: {subpath!r}")
    subpath = unicodedata.normalize("NFKC", subpath)
    if _has_control_chars(subpath):
        raise PathSecurityError(f"Invalid subpath: {subpath!r}")
    pwp = PureWindowsPath(subpath)
    if pwp.drive or pwp.is_absolute():
        raise PathSecurityError(f"Subpath must be relative: {subpath!r}")
    subpath = subpath.replace("\\", "/")
    cleaned_parts = []
    for segment in subpath.split("/"):
        if segment in ("", ".", ".."):
            cleaned_parts.append(segment)
            continue
        cleaned_parts.append(_validate_segment(segment))
    base = Path(directory)
    target = base / "/".join(cleaned_parts)
    try:
        resolved_base = base.resolve()
        resolved_target = target.resolve()
    except (OSError, UnicodeEncodeError) as e:
        raise PathSecurityError(f"Cannot resolve subpath {subpath!r}: {e}") from e
    try:
        resolved_target.relative_to(resolved_base)
    except ValueError:
        raise PathSecurityError(f"Subpath {subpath!r} resolves outside {directory}") from None
    return resolved_target
