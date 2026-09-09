from agno.utils.merge_dict import merge_parallel_session_states


def test_merge_applies_changes_when_original_state_is_empty():
    """An empty starting state ({}) is the normal case for a fresh workflow;
    parallel-step changes must still be applied, not discarded."""
    original: dict = {}
    merge_parallel_session_states(original, [{"step_a": 1}, {"step_b": 2}])
    assert original == {"step_a": 1, "step_b": 2}


def test_merge_preserves_non_empty_original_state():
    original = {"x": 0}
    merge_parallel_session_states(original, [{"a": 1}])
    assert original == {"x": 0, "a": 1}


def test_merge_is_noop_without_modified_states():
    original = {"x": 1}
    merge_parallel_session_states(original, [])
    assert original == {"x": 1}


def test_merge_only_applies_actual_changes():
    original = {"x": 1}
    merge_parallel_session_states(original, [{"x": 1}, {"y": 2}])
    assert original == {"x": 1, "y": 2}
