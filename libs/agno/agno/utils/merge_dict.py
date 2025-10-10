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


def merge_parallel_session_states(original_state: Dict[str, Any], modified_states: List[Dict[str, Any]]) -> None:
    """
    Smart merge for parallel session states that only applies actual changes.
    This prevents parallel steps from overwriting each other's changes.
    """
    if not original_state or not modified_states:
        return

    # Collect all actual changes (keys where value differs from original)
    all_changes = {}
    for modified_state in modified_states:
        if modified_state:
            for key, value in modified_state.items():
                if key not in original_state or original_state[key] != value:
                    all_changes[key] = value

    # Apply all collected changes to the original state
    for key, value in all_changes.items():
        original_state[key] = value
