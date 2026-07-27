"""
Learning Machine Utilities
==========================
Helper functions for safe data handling.

All functions are designed to never raise exceptions -
they return None on any failure. This prevents learning
extraction errors from crashing the main agent.
"""

from dataclasses import asdict, fields
from typing import Any, Dict, List, Optional, Type, TypeVar

T = TypeVar("T")

# Default sharing namespace used by the learning stores when none is configured/provided.
DEFAULT_LEARNING_NAMESPACE = "global"

# Learning types whose records are keyed by a deterministic id derived from their identity
# fields (see build_learning_id). Anything creating these must use that id, or the record
# won't reconcile with the agent's store. Other types (e.g. decision_log) use a generated id.
IDENTITY_KEYED_LEARNING_TYPES = frozenset({"user_profile", "user_memory", "session_context", "entity_memory"})


def build_learning_id(
    learning_type: str,
    *,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    entity_id: Optional[str] = None,
    entity_type: Optional[str] = None,
    namespace: Optional[str] = None,
) -> Optional[str]:
    """Deterministic primary key for the framework's identity-keyed learning stores.

    The learning stores key each record in ``agno_learnings`` by an id derived from its
    identity fields -- NOT a random uuid. So anything else writing to that table (e.g. the
    REST create endpoint) must compute the same id, otherwise the record won't reconcile
    with what the agent reads/writes and duplicate rows appear.

    This is the single source of truth: the stores' ``_build_*_id`` helpers delegate here.

    Returns ``None`` for learning types that do not use a deterministic id (e.g.
    ``decision_log``, which keys each entry by its own uuid) or when the identity fields
    required for the id are missing -- callers should fall back to a generated id then.
    """
    if learning_type == "user_profile":
        return f"user_profile_{user_id}" if user_id else None
    if learning_type == "user_memory":
        return f"memories_{user_id}" if user_id else None
    if learning_type == "session_context":
        return f"session_context_{session_id}" if session_id else None
    if learning_type == "entity_memory":
        if entity_id and entity_type:
            return f"entity_{namespace or DEFAULT_LEARNING_NAMESPACE}_{entity_type}_{entity_id}"
        return None
    return None


def content_values_text(content: Any) -> str:
    """Flatten a content payload to a lowercased text of its VALUES only.

    Used to verify text-search hits: the db-side ILIKE matches the whole
    serialized JSON document, keys included, so a query like "facts" or "name"
    would match every row. Matching against the value projection restores
    value-scoped precision without dropping any field.
    """
    parts: List[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, (list, tuple)):
            for value in node:
                walk(value)
        elif node is not None:
            parts.append(str(node))

    walk(content)
    # casefold, not lower: a stored "Ος" has to match a query of "ΟΣ".
    return "\n".join(parts).casefold()


def separator_folded(text: str) -> str:
    """Collapse runs of space, underscore and hyphen to one space, casefolded.

    The db-side pattern turns each separator run into the LIKE single-char
    wildcard, which matches ANY separator. A verifier that enumerates uniform
    rewrites cannot express mixed-separator text, so it threw away hits the
    server had legitimately found: "end-to-end tests" stored and "end to end
    tests" asked (or the reverse) verified as a miss, and the store answered
    "no entities matching" for a fact it was holding. Folding both sides is
    what the wildcard already means.

    Newlines are left alone: they separate one stored value from the next, and
    a match must not span two of them.
    """
    import re

    return re.sub(r"[ \t\r\f\v_\-]+", " ", text.casefold())


def values_match_query(content: Any, query: str) -> bool:
    """Whether the content's VALUES contain the query, separator-insensitively.

    The value-scoped half of the loose-prefilter/precise-verify pair: the
    db-side ILIKE matches the whole serialized document, key names included,
    so "facts" or "name" would otherwise match every row.
    """
    needle = separator_folded(query).strip()
    if not needle:
        return False
    return needle in separator_folded(content_values_text(content))


def query_variants(query: str) -> List[str]:
    """Lowercased query variants with word separators swapped.

    Mirrors the space/underscore(/hyphen) crossing the db-side search performs
    with the LIKE single-char wildcard, so a client-side verification pass does
    not drop hits the server legitimately matched ("sarah chen" vs sarah_chen).

    The query itself is the first variant. Rewriting every separator to one
    character produces no form that matches a query which MIXES them - the db
    matches "end-to-end tests" through the single-char wildcard, and a verifier
    that only knows "end to end tests" / "end_to_end_tests" throws that hit
    away.
    """
    import re

    lowered = query.strip().casefold()
    if not lowered:
        return []
    variants: List[str] = [lowered]
    for separator in (" ", "_", "-"):
        variant = re.sub(r"[\s_\-]+", separator, lowered)
        if variant and variant not in variants:
            variants.append(variant)
    return variants


def _safe_get(data: Any, key: str, default: Any = None) -> Any:
    """Safely get a key from dict-like data.

    Args:
        data: Dict or object with attributes.
        key: Key or attribute name to get.
        default: Value to return if not found.

    Returns:
        The value, or default if not found.
    """
    if isinstance(data, dict):
        return data.get(key, default)
    return getattr(data, key, default)


def _parse_json(data: Any) -> Optional[Dict]:
    """Parse JSON string to dict, or return dict as-is.

    Args:
        data: JSON string, dict, or None.

    Returns:
        Parsed dict, or None if parsing fails.
    """
    if data is None:
        return None
    if isinstance(data, dict):
        return data
    if isinstance(data, str):
        import json

        try:
            return json.loads(data)
        except Exception:
            return None
    return None


def from_dict_safe(cls: Type[T], data: Any) -> Optional[T]:
    """Safely create a dataclass instance from dict-like data.

    Works with any dataclass - automatically handles subclass fields.
    Never raises - returns None on any failure.

    Args:
        cls: The dataclass type to instantiate.
        data: Dict, JSON string, or existing instance.

    Returns:
        Instance of cls, or None if parsing fails.

    Example:
        >>> profile = from_dict_safe(UserProfile, {"user_id": "123"})
        >>> profile.user_id
        '123'
    """
    if data is None:
        return None

    # Already the right type
    if isinstance(data, cls):
        return data

    try:
        # Parse JSON string if needed
        parsed = _parse_json(data)
        if parsed is None:
            return None

        # Get valid field names for this class
        field_names = {f.name for f in fields(cls)}  # type: ignore

        # Filter to only valid fields
        kwargs = {k: v for k, v in parsed.items() if k in field_names}

        return cls(**kwargs)
    except Exception:
        return None


def print_panel(
    title: str,
    subtitle: str,
    lines: List[str],
    *,
    empty_message: str = "No data",
    raw_data: Any = None,
    raw: bool = False,
) -> None:
    """Print formatted panel output for learning stores.

    Uses rich library for formatted output with a bordered panel.
    Falls back to pprint when raw=True or rich is unavailable.

    Args:
        title: Panel title (e.g., "User Profile", "Session Context")
        subtitle: Panel subtitle (e.g., user_id, session_id)
        lines: Content lines to display inside the panel
        empty_message: Message shown when lines is empty
        raw_data: Object to pprint when raw=True
        raw: If True, use pprint instead of formatted panel

    Example:
        >>> print_panel(
        ...     title="User Profile",
        ...     subtitle="alice@example.com",
        ...     lines=["Name: Alice", "Memories:", "  [abc123] Loves Python"],
        ...     raw_data=profile,
        ... )
        ╭──────────────── User Profile ─────────────────╮
        │ Name: Alice                                   │
        │ Memories:                                     │
        │   [abc123] Loves Python                       │
        ╰─────────────── alice@example.com ─────────────╯
    """
    if raw and raw_data is not None:
        from pprint import pprint

        pprint(to_dict_safe(raw_data) or raw_data)
        return

    try:
        from rich.console import Console
        from rich.panel import Panel

        console = Console()

        if not lines:
            content = f"[dim]{empty_message}[/dim]"
        else:
            content = "\n".join(lines)

        panel = Panel(
            content,
            title=f"[bold]{title}[/bold]",
            subtitle=f"[dim]{subtitle}[/dim]",
            border_style="blue",
        )
        console.print(panel)

    except ImportError:
        # Fallback if rich not installed
        from pprint import pprint

        print(f"=== {title} ({subtitle}) ===")
        if not lines:
            print(f"  {empty_message}")
        else:
            for line in lines:
                print(f"  {line}")
        print()


def to_dict_safe(obj: Any) -> Optional[Dict[str, Any]]:
    """Safely convert a dataclass to dict.

    Works with any dataclass. Never raises - returns None on failure.

    Args:
        obj: Dataclass instance to convert.

    Returns:
        Dict representation, or None if conversion fails.

    Example:
        >>> profile = UserProfile(user_id="123")
        >>> to_dict_safe(profile)
        {'user_id': '123', 'name': None, ...}
    """
    if obj is None:
        return None

    try:
        # Already a dict
        if isinstance(obj, dict):
            return obj

        # Has to_dict method
        if hasattr(obj, "to_dict"):
            return obj.to_dict()

        # Is a dataclass
        if hasattr(obj, "__dataclass_fields__"):
            return asdict(obj)

        # Has __dict__
        if hasattr(obj, "__dict__"):
            return dict(obj.__dict__)

        return None
    except Exception:
        return None
