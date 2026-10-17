from copy import deepcopy
from typing import Any, Dict, List


def merge_dictionaries(a: Dict[str, Any], b: Dict[str, Any]) -> None:
    """
    Recursively merges two dictionaries.
    If there are conflicting keys, values from 'b' will take precedence.

    Args:
        a (Dict[str, Any]): The first dictionary to be merged.
        b (Dict[str, Any]): The second dictionary, whose values will take precedence.

    Returns:
        None: The function modifies the first dictionary in place.
    """
    for key in b:
        if key in a and isinstance(a[key], dict) and isinstance(b[key], dict):
            merge_dictionaries(a[key], b[key])
        else:
            a[key] = b[key]


_MISSING = object()


def _apply_state_changes(
    target: Dict[str, Any],
    baseline: Dict[str, Any],
    modified: Dict[str, Any],
    apply_removals: bool = False,
) -> None:
    """Apply the keys that modified changed relative to baseline to target, recursing into nested dicts.

    Every parallel step works on its own copy of the state, so a step that
    changed one key of a nested dict hands back the whole dict. Assigning that
    dict wholesale would carry the step's untouched keys over its siblings'
    changes to the same dict, so a nested dict is descended into and only the
    keys that actually changed are applied.

    Inside a nested dict, a key that is in baseline and gone from modified was
    removed by the step, and the removal is applied. Top level keys are only
    ever added or overwritten, which is how the merge behaved before nested
    dicts were descended into.
    """
    for key, value in modified.items():
        baseline_value = baseline.get(key, _MISSING)
        target_value = target.get(key, _MISSING)
        if isinstance(value, dict) and isinstance(target_value, dict):
            nested_baseline = baseline_value if isinstance(baseline_value, dict) else {}
            _apply_state_changes(target_value, nested_baseline, value, apply_removals=True)
        elif baseline_value is _MISSING or baseline_value != value:
            target[key] = value

    if apply_removals:
        for key in baseline:
            if key not in modified:
                target.pop(key, None)


def merge_parallel_session_states(original_state: Dict[str, Any], modified_states: List[Dict[str, Any]]) -> None:
    """
    Smart merge for parallel session states that only applies actual changes.
    This prevents parallel steps from overwriting each other's changes.
    """
    if not original_state or not modified_states:
        return

    # Changes are measured against the state as it was before the parallel steps
    # ran, so applying one step's change does not make the next step's untouched
    # values look changed.
    baseline = deepcopy(original_state)
    for modified_state in modified_states:
        if modified_state:
            _apply_state_changes(original_state, baseline, modified_state)
