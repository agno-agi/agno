"""Path-safety helpers for filesystem-touching tools.

Any tool that joins a directory with untrusted user input should route
through ``safe_join`` (filename only) or ``safe_join_subpath`` (multi-segment).
"""

import re
import unicodedata
from pathlib import Path, PureWindowsPath
from typing import Union

from agno.exceptions import PathSecurityError
from agno.utils.log import log_error, log_warning

_WIN_RESERVED_RE = re.compile(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\.|$)", re.IGNORECASE)
_WIN_DRIVE_OR_UNC_RE = re.compile(r"^([A-Za-z]:|\\\\)")


def _has_control_chars(text: str) -> bool:
    """Cross-platform check for Unicode control characters (category Cc)."""
    return any(unicodedata.category(c) == "Cc" for c in text)


def _has_drive_or_unc(text: str) -> bool:
    """Check for Windows drive letters or UNC prefixes. Uses ``PureWindowsPath`` so the same input is rejected on POSIX and Windows."""
    if _WIN_DRIVE_OR_UNC_RE.match(text):
        return True
    pwp = PureWindowsPath(text)
    return bool(pwp.drive) or pwp.is_absolute()


def _validate_segment(segment: str) -> str:
    """Validate a single path segment and return the trailing-dot-stripped form."""
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
    if _WIN_RESERVED_RE.match(stripped):
        log_error(f"Security violation: Windows reserved name {stripped!r}")
        raise PathSecurityError(f"Segment {segment!r} is a Windows reserved name")
    return stripped


def safe_join(directory: Union[str, Path], filename: str) -> Path:
    """Join ``directory`` with ``filename``, keeping only the basename.

    Path components in ``filename`` are discarded (use ``safe_join_subpath``
    if you need to preserve sub-directories). Use this for filenames received
    from LLM output (FileGenerationTools, Slack uploads). When components
    are stripped, a warning is emitted via ``log_warning``.

    Args:
        directory: The base directory the file must land inside.
        filename: The filename to join. Path components are discarded.

    Returns:
        The resolved file path inside ``directory``.

    Raises:
        PathSecurityError: If the input contains control characters, a
            Windows drive letter or UNC prefix, resolves to an empty or
            dot-only name, or escapes ``directory`` (e.g. via a symlink).
    """
    base = Path(directory)
    filename = unicodedata.normalize("NFKC", filename)
    if _has_control_chars(filename):
        log_error(f"Security violation: control char in filename {filename!r}")
        raise PathSecurityError(f"Invalid filename (control chars): {filename!r}")
    if _has_drive_or_unc(filename):
        log_error(f"Security violation: Windows drive/UNC in {filename!r}")
        raise PathSecurityError(f"Filename {filename!r} contains drive letter or UNC prefix")
    if "/" in filename or "\\" in filename:
        log_warning(
            f"safe_join discarded path components from {filename!r}; "
            "using basename only. Use safe_join_subpath if you need to "
            "preserve sub-directories."
        )
    # Normalize Windows separators so basename extraction is OS-independent
    # (Path("a\\b").name == "b" on Windows but "a\\b" on POSIX otherwise).
    safe = Path(filename.replace("\\", "/")).name.rstrip(". ")
    if not safe or safe.strip(".") == "":
        log_error(f"Security violation: empty/dot-only filename {filename!r}")
        raise PathSecurityError(f"Invalid filename after sanitization: {filename!r}")
    safe = _validate_segment(safe)
    file_path = base / safe
    try:
        resolved_file = file_path.resolve()
        resolved_dir = base.resolve()
    except (OSError, UnicodeEncodeError) as e:
        log_error(f"Security violation: cannot resolve {filename!r}: {e}")
        raise PathSecurityError(f"Cannot resolve path {filename!r}: {e}") from e
    try:
        resolved_file.relative_to(resolved_dir)
    except ValueError:
        log_error(f"Security violation: path {filename!r} resolves outside {directory}")
        raise PathSecurityError(f"Filename {filename!r} resolves outside directory (possible symlink escape)") from None
    return resolved_file


def safe_join_subpath(directory: Union[str, Path], subpath: str) -> Path:
    """Join ``directory`` with ``subpath``, preserving multi-segment paths.

    Allows inputs like ``"docs/report.md"`` but enforces containment by
    resolving both ``directory`` and the target before comparison. Use for
    tool callers that accept relative paths into a base directory
    (``Toolkit._check_path``, ``is_safe_path``, ``FileTools``, ``CodingTools``).

    Args:
        directory: The base directory the target must land inside.
        subpath: A relative subpath. Segments are validated individually.

    Returns:
        The resolved target path inside ``directory``.

    Raises:
        PathSecurityError: If the input is empty, contains control
            characters, is absolute or contains a drive/UNC prefix, has a
            Windows-reserved segment, or escapes ``directory`` (e.g. via a
            symlink).
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
    # Normalize backslashes so segment validation and the join agree on boundaries.
    subpath = subpath.replace("\\", "/")
    # Preserve "", ".", ".." so the resolve + relative_to check still catches escapes.
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
        log_error(f"Security violation: cannot resolve subpath {subpath!r}: {e}")
        raise PathSecurityError(f"Cannot resolve subpath {subpath!r}: {e}") from e
    try:
        resolved_target.relative_to(resolved_base)
    except ValueError:
        log_error(f"Security violation: subpath {subpath!r} escapes {directory}")
        raise PathSecurityError(f"Subpath {subpath!r} resolves outside {directory} (possible symlink escape)") from None
    return resolved_target
