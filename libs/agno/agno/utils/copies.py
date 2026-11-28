"""Strict-load fidelity check for registry copies."""

from typing import Any, FrozenSet, List, Optional

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


# Workflow.deep_copy mints a fresh step_id for every step, so ids are dropped
# before a workflow copy is compared with its original.
_REGENERATED_WORKFLOW_KEYS: FrozenSet[str] = frozenset({"step_id"})

# Runtime state the divergence decision leaves out. The guard exists to catch a
# copy that lost the work - its steps, their executors and their configuration.
# These keys hold caller-supplied runtime state whose values are frequently
# unhashable, unequal under identity, or deliberately per-instance, so a
# difference there says nothing about whether the copy can still do the job.
_RUNTIME_STATE_WORKFLOW_KEYS: FrozenSet[str] = frozenset({"session_state", "dependencies", "metadata"})

_UNCOMPARED_WORKFLOW_KEYS: FrozenSet[str] = _REGENERATED_WORKFLOW_KEYS | _RUNTIME_STATE_WORKFLOW_KEYS


def _without_keys(value: Any, keys: FrozenSet[str]) -> Any:
    """Rebuild value with every mapping entry named in keys dropped, at any depth."""
    if isinstance(value, dict):
        return {key: _without_keys(item, keys) for key, item in value.items() if key not in keys}
    if isinstance(value, list):
        return [_without_keys(item, keys) for item in value]
    return value


def workflow_copy_divergence(original: Any, copied: Any) -> Optional[str]:
    """How a workflow copy's serialized form differs from its original, or None.

    What this catches is a copy that lost the work the stored config names:
    its id, its name, a step's own configuration, and - when the original's
    steps are a plain list - the steps themselves. Workflow.to_dict emits a
    'steps' key only for a list, so when the original's steps are a Steps
    container or a callable neither side carries a serialized step list and a
    copy that emptied them is admitted.

    How much of a child is compared depends on how the step named it. A step
    that references a child - Step(agent=...), Step(team=...) or
    Step(workflow=...) - serializes only that child's agent_id, team_id or
    workflow_id, so a child that keeps its id while losing its own state reads
    as identical here. A child that is the step - the Workflow(steps=[Agent(...)])
    shorthand - is serialized by its own to_dict, so its internals are compared.

    Step ids are dropped at any nesting depth before comparing, because
    deep_copy regenerates them; containers such as Loop, Parallel, Condition,
    Steps and Router serialize their children's step configs inside nested
    lists, so the drop has to reach through those too. Session state,
    dependencies and metadata are dropped as well: they carry runtime state
    the caller supplied, not the work the copy has to be able to do.

    An original that cannot be serialized leaves the copy unmeasured rather
    than condemned, and so does a single key whose comparison cannot produce a
    bool - a value whose __eq__ returns something else - while every other key
    is still judged. A copy whose own to_dict raises is a divergence: a copy
    that cannot serialize is not a faithful one.
    """
    try:
        original_dict = _without_keys(original.to_dict(), _UNCOMPARED_WORKFLOW_KEYS)
    except Exception as e:
        log_debug(f"Could not compare a workflow copy against its original (to_dict failed: {e})")
        return None
    try:
        copied_dict = _without_keys(copied.to_dict(), _UNCOMPARED_WORKFLOW_KEYS)
    except Exception as e:
        return f"the copy could not be serialized (to_dict failed: {e})"
    diverging: List[str] = []
    for key in sorted(set(original_dict) | set(copied_dict)):
        try:
            if original_dict.get(key) != copied_dict.get(key):
                diverging.append(key)
        except Exception as e:
            # One unmeasurable value only leaves its own key unjudged; every
            # other key is still judged, so a copy that dropped its steps is
            # still refused.
            log_debug(f"Could not compare the workflow copy's '{key}' against the original ({e})")
    if not diverging:
        return None
    return f"the copy diverges from the original on: {', '.join(diverging[:5])}"
