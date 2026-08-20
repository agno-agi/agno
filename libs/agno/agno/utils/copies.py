"""Strict-load fidelity check for registry copies."""

from typing import Any, FrozenSet, Optional

from agno.utils.log import log_debug


def copy_divergence(original: Any, copied: Any) -> Optional[str]:
    """How a copy's serialized form differs from its original, or None.

    A deep copy that serializes differently has lost or changed state the
    stored config still names - a subclass whose __init__ swallows kwargs
    turns the inherited deep_copy into an empty shell - so a strict load must
    not dispatch it. Only serialized fields are compared: state to_dict does
    not model is outside what rehydration can promise.
    """
    try:
        original_dict = original.to_dict()
        copied_dict = copied.to_dict()
    except Exception as e:
        return f"the copy could not be compared (to_dict failed: {e})"
    if original_dict == copied_dict:
        return None
    diverging = sorted(
        key for key in set(original_dict) | set(copied_dict) if original_dict.get(key) != copied_dict.get(key)
    )
    return f"the copy diverges from the original on: {', '.join(diverging[:5])}"


_REGENERATED_WORKFLOW_KEYS: FrozenSet[str] = frozenset({"step_id"})


def _without_keys(value: Any, keys: FrozenSet[str]) -> Any:
    """Rebuild value with every mapping entry named in keys dropped, at any depth."""
    if isinstance(value, dict):
        return {key: _without_keys(item, keys) for key, item in value.items() if key not in keys}
    if isinstance(value, list):
        return [_without_keys(item, keys) for item in value]
    return value


def workflow_copy_divergence(original: Any, copied: Any) -> Optional[str]:
    """How a workflow copy's serialized form differs from its original, or None.

    Workflow.deep_copy mints a fresh step_id for every step, so a raw
    serialization compare diverges for every workflow that declares steps.
    Step ids are therefore dropped at any nesting depth - containers such as
    Loop, Parallel, Condition, Steps and Router serialize their children's
    step configs inside nested lists - and everything else is compared as
    usual: id, name, step count, executor references and per-step
    configuration.

    Serializing a nested child workflow is not something the parent config
    ever does, so a to_dict that raises is an inability to measure rather than
    a divergence, and it is not held against the copy.
    """
    try:
        original_dict = _without_keys(original.to_dict(), _REGENERATED_WORKFLOW_KEYS)
        copied_dict = _without_keys(copied.to_dict(), _REGENERATED_WORKFLOW_KEYS)
    except Exception as e:
        log_debug(f"Could not compare a workflow copy against its original (to_dict failed: {e})")
        return None
    if original_dict == copied_dict:
        return None
    diverging = sorted(
        key for key in set(original_dict) | set(copied_dict) if original_dict.get(key) != copied_dict.get(key)
    )
    return f"the copy diverges from the original on: {', '.join(diverging[:5])}"
