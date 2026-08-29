"""Tool annotation hints (MCP ``ToolAnnotations``) and their validation.

Annotations tell a client what a tool DOES to the world -- whether it only reads,
whether a call can destroy something, whether it reaches outside the server. Assistant
marketplaces read them: a submission scan rejects tools that carry none, and reviewers
test the claim against the tool's real behaviour, so a wrong hint is worse than a
missing one.

Publish all three of ``readOnlyHint``, ``destructiveHint``, and ``openWorldHint`` on
every tool. A submission scan rejects a tool that leaves any of them unset, and an
omitted hint is not read as "unknown" by a client -- it falls back to a protocol
default, which answers for the tool whether or not that answer is true. Components
published through ``as_tool`` get all three from the serving surface; a plain callable
carries none, so a tool that is going to be listed should be an agno ``Function``
(``@tool(annotations=...)``) that states them.

The keys are fixed by the protocol. They are validated where the developer writes them
(``as_tool(annotations=...)``, ``@tool(annotations=...)``) rather than at registration,
because a silent typo -- ``readonlyHint`` for ``readOnlyHint`` -- forwards as an unknown
key, reads as "no annotation" to a reviewing client, and is only discovered when a
listing is rejected.
"""

from difflib import get_close_matches
from typing import Any, Dict, Mapping, Optional

# The MCP ToolAnnotations fields: a display title plus four behaviour hints.
TOOL_ANNOTATION_HINTS = ("readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint")
TOOL_ANNOTATION_KEYS = ("title",) + TOOL_ANNOTATION_HINTS


def validate_tool_annotations(annotations: Optional[Mapping[str, Any]], source: str) -> Optional[Dict[str, Any]]:
    """Return ``annotations`` as a plain dict, rejecting keys the protocol does not define.

    ``source`` names the call the developer wrote, so the error points at their code.
    A ``None`` VALUE is legal and meaningful: it removes a key the surface would
    otherwise supply by default. A ``None`` mapping means "no annotations given".
    """
    if annotations is None:
        return None
    if not isinstance(annotations, Mapping):
        raise TypeError(f"{source} expects a dict of tool annotations, got {type(annotations).__name__}.")

    validated: Dict[str, Any] = {}
    for key, value in annotations.items():
        if key not in TOOL_ANNOTATION_KEYS:
            suggestion = get_close_matches(str(key), TOOL_ANNOTATION_KEYS, n=1, cutoff=0.6)
            hint = f" Did you mean {suggestion[0]!r}?" if suggestion else ""
            raise ValueError(
                f"{source} got unknown tool annotation {key!r}.{hint} "
                f"Valid annotations: {', '.join(TOOL_ANNOTATION_KEYS)}."
            )
        if value is not None:
            if key == "title" and not isinstance(value, str):
                raise TypeError(f"{source} expects annotation 'title' to be a string, got {type(value).__name__}.")
            if key in TOOL_ANNOTATION_HINTS and not isinstance(value, bool):
                raise TypeError(f"{source} expects annotation {key!r} to be a bool, got {type(value).__name__}.")
        validated[key] = value
    return validated


def merge_tool_annotations(defaults: Mapping[str, Any], overrides: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """Merge developer overrides over a surface's defaults, per key.

    A key set to ``None`` in the overrides is REMOVED from the result rather than
    emitted as null -- the way to publish a tool without a hint the surface would
    otherwise assert on the developer's behalf.
    """
    merged: Dict[str, Any] = dict(defaults)
    for key, value in (overrides or {}).items():
        if value is None:
            merged.pop(key, None)
        else:
            merged[key] = value
    return merged


def tool_presentation(
    title: Optional[str],
    annotations: Optional[Mapping[str, Any]],
    defaults: Optional[Mapping[str, Any]] = None,
    fallback_title: Optional[str] = None,
    source: str = "annotations",
) -> "tuple[Optional[str], Optional[Dict[str, Any]]]":
    """The ``(title, annotations)`` a tool publishes, resolved and merged in one place.

    A tool carries its title in two protocol slots: its own ``title`` field, and the
    older ``annotations.title`` that pre-2025-06-18 clients read. They are one setting,
    not two -- whichever the developer wrote fills both, so no client can be shown a
    different name than another. Every surface that registers a tool goes through here,
    so the next one added cannot fill only one slot.

    Annotations are re-validated here, not only where they were first written. A
    carrier's dict stays mutable after it is validated -- ``Function.from_callable``
    hands back a Function precisely so callers can adjust it, and a frozen marker's
    dict is still a dict -- so publication, not construction, is the last point at
    which an unknown key can still be caught before a client sees it.
    """
    annotations = validate_tool_annotations(annotations, source)
    from_annotations = (annotations or {}).get("title")
    resolved_title = (
        title or (from_annotations if isinstance(from_annotations, str) else None) or fallback_title or None
    )
    merged = merge_tool_annotations(defaults or {}, annotations)
    if resolved_title:
        merged["title"] = resolved_title
    return resolved_title, (merged or None)
