"""Path, namespace-name, directory and line normalization for FileSystem.

Pure string logic — no disk, no database. One grammar covers file paths,
namespace names and directory parameters; one line transform covers both
appended content and ``check_lines`` inputs so exact-line dedupe cannot drift.
"""

from __future__ import annotations

import re
import unicodedata
from typing import List, Sequence, Tuple

from agno.fs.errors import InvalidPathError

MAX_PATH_CHARS = 512
MAX_SEGMENTS = 16
MAX_SEGMENT_CHARS = 128
MAX_CHECK_LINES = 200

TEMPLATE_PLACEHOLDERS: Tuple[str, ...] = ("user_id", "agent_id", "team_id")

_PLACEHOLDER_RE = re.compile(r"\{([^{}]*)\}")


def _invalid_path(original: object, reason: str) -> InvalidPathError:
    return InvalidPathError(f"invalid path {original!r}: {reason}. Use relative paths like notes/topic.md.")


def normalize_path(path: str) -> str:
    """Validate and canonicalize a file path (or namespace name) per the FileSystem grammar.

    Canonical form has no leading slash. Raises ``InvalidPathError`` on any violation.
    """
    original = path
    if not isinstance(path, str):
        raise _invalid_path(original, "path must be a string")
    value = unicodedata.normalize("NFC", path)
    for ch in value:
        if unicodedata.category(ch) == "Cc":
            raise _invalid_path(original, "control characters are not allowed")
    if "\\" in value:
        raise _invalid_path(original, "backslashes are not allowed, use forward slashes")
    while "//" in value:
        value = value.replace("//", "/")
    if value.startswith("/"):
        value = value[1:]
    if value.endswith("/"):
        raise _invalid_path(original, "trailing slashes are not allowed, paths address files")
    if not value:
        raise _invalid_path(original, "path is empty")
    if len(value) > MAX_PATH_CHARS:
        raise _invalid_path(original, f"path is longer than {MAX_PATH_CHARS} characters")
    segments = value.split("/")
    if len(segments) > MAX_SEGMENTS:
        raise _invalid_path(original, f"path has more than {MAX_SEGMENTS} segments")
    for segment in segments:
        if segment in (".", ".."):
            raise _invalid_path(original, "segments '.' and '..' are not allowed")
        if len(segment) > MAX_SEGMENT_CHARS:
            raise _invalid_path(original, f"a segment is longer than {MAX_SEGMENT_CHARS} characters")
    return value


def parse_namespace_template(name: str) -> Tuple[str, ...]:
    """Return the template placeholders embedded in a namespace name, in order.

    Raises ``InvalidPathError`` on unknown placeholders or stray braces — braces
    are reserved in namespace names (they remain legal in file paths).
    """
    placeholders = tuple(_PLACEHOLDER_RE.findall(name))
    for placeholder in placeholders:
        if placeholder not in TEMPLATE_PLACEHOLDERS:
            raise _invalid_path(
                name,
                f"unknown placeholder {{{placeholder}}}, valid placeholders are "
                f"{', '.join('{' + p + '}' for p in TEMPLATE_PLACEHOLDERS)}",
            )
    remainder = _PLACEHOLDER_RE.sub("", name)
    if "{" in remainder or "}" in remainder:
        raise _invalid_path(name, "braces are reserved in namespace names")
    return placeholders


def normalize_namespace(name: str) -> str:
    """Validate a namespace name, which may embed template placeholders.

    Untemplated names are canonicalized by ``normalize_path``. Templated names are
    validated against the grammar with each placeholder standing in for one segment
    character, and returned with the placeholders intact.
    """
    if not isinstance(name, str):
        raise _invalid_path(name, "namespace must be a string")
    value = unicodedata.normalize("NFC", name)
    placeholders = parse_namespace_template(value)
    if not placeholders:
        return normalize_path(value)
    stand_in = value
    for placeholder in set(placeholders):
        stand_in = stand_in.replace("{" + placeholder + "}", "x")
    normalize_path(stand_in)
    return value


def normalize_template_value(placeholder: str, value: object) -> str:
    """Validate one interpolated template value: exactly one path segment, no braces."""
    if not isinstance(value, str) or not value:
        raise InvalidPathError(f"invalid {placeholder} value {value!r}: must be a non-empty string")
    normalized = unicodedata.normalize("NFC", value)
    if "/" in normalized:
        raise InvalidPathError(f"invalid {placeholder} value {value!r}: must be a single path segment")
    if "{" in normalized or "}" in normalized:
        raise InvalidPathError(f"invalid {placeholder} value {value!r}: braces are not allowed")
    try:
        as_path = normalize_path(normalized)
    except InvalidPathError:
        raise InvalidPathError(f"invalid {placeholder} value {value!r}: must be a single valid path segment") from None
    if as_path != normalized or "/" in as_path:
        raise InvalidPathError(f"invalid {placeholder} value {value!r}: must be a single valid path segment")
    return normalized


def normalize_directory(directory: str) -> str:
    """Validate a directory parameter. ``""`` and ``"."`` both mean the namespace root."""
    if not isinstance(directory, str):
        raise _invalid_path(directory, "directory must be a string")
    if directory in ("", "."):
        return ""
    return normalize_path(directory)


def normalize_line(line: str) -> str:
    """Strip trailing line terminators only — never leading or interior whitespace.

    Returns ``""`` for a line that is empty after the strip (callers drop those).
    Raises ``InvalidPathError`` for a line with an interior newline, so a record
    can never be stored in a form ``check_lines`` cannot match.
    """
    if not isinstance(line, str):
        raise InvalidPathError(f"invalid record {line!r}: records must be single lines with no newlines.")
    value = line.rstrip("\r\n")
    if "\n" in value or "\r" in value:
        raise InvalidPathError(f"invalid record {line!r}: records must be single lines with no newlines.")
    return value


def normalize_check_lines(lines: Sequence[str]) -> List[str]:
    """Normalize a ``check_lines`` input batch: cap 200, strip terminators, drop empties."""
    # A bare str is a Sequence[str] of single characters, so an unguarded call would
    # iterate it per character and report every char missing — a silent wrong answer
    # from the dedupe primitive. Reject any non list/tuple; the type checker cannot
    # catch this because str satisfies Sequence[str].
    if not isinstance(lines, (list, tuple)):
        raise InvalidPathError(
            f'invalid records {lines!r}: pass a list of lines, e.g. ["url-1", "url-2"], not a single string.'
        )
    if len(lines) > MAX_CHECK_LINES:
        raise InvalidPathError(
            f"too many records ({len(lines)} > {MAX_CHECK_LINES}). Check them in batches of {MAX_CHECK_LINES} or fewer."
        )
    normalized = [normalize_line(line) for line in lines]
    return [line for line in normalized if line]


def build_chunk(content: str) -> str:
    """Build the canonical append chunk from raw content.

    Splits on ``"\\n"``, strips trailing terminators per line (CRLF-safe), drops
    empty lines, re-joins with ``"\\n"`` and adds the trailing newline. Returns
    ``""`` when nothing remains to append. The same transform normalizes
    ``check_lines`` inputs, which is what makes exact-line dedupe symmetric.
    """
    if not isinstance(content, str):
        raise InvalidPathError(f"invalid record {content!r}: records must be single lines with no newlines.")
    lines = [normalize_line(piece) for piece in content.split("\n")]
    kept = [line for line in lines if line]
    if not kept:
        return ""
    return "\n".join(kept) + "\n"


def path_in_directory(path: str, directory: str) -> bool:
    """Real directory semantics at segment boundaries — never plain string-prefix.

    ``directory=""`` means the namespace root and matches everything;
    ``directory="seen"`` matches ``seen`` and ``seen/...`` but not ``seen-old/...``.
    """
    if not directory:
        return True
    return path == directory or path.startswith(directory + "/")


def path_sort_key(path: str) -> List[str]:
    """Sort key for path listings: compare by segments, not by raw string."""
    return path.split("/")
