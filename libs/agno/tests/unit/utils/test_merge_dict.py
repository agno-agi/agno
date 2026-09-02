from agno.utils.merge_dict import merge_dictionaries, merge_parallel_session_states


def test_merge_dictionaries_nested_override():
    a = {"x": {"a": 1, "b": 2}, "y": 3}
    b = {"x": {"b": 20, "c": 30}, "z": 4}
    merge_dictionaries(a, b)
    assert a == {"x": {"a": 1, "b": 20, "c": 30}, "y": 3, "z": 4}


def test_merge_parallel_applies_changes_to_nonempty_state():
    original = {"x": 0}
    merge_parallel_session_states(original, [{"a": 1}, {"b": 2}])
    assert original == {"x": 0, "a": 1, "b": 2}


def test_merge_parallel_applies_changes_to_empty_state():
    # Regression: an empty starting state must still receive parallel changes.
    # `if not original_state` previously returned early for {}, so every parallel
    # step's writes were dropped whenever the workflow began with no session state.
    original: dict = {}
    merge_parallel_session_states(original, [{"a": 1}, {"b": 2}])
    assert original == {"a": 1, "b": 2}


def test_merge_parallel_only_applies_actual_changes():
    original = {"shared": 1}
    merge_parallel_session_states(original, [{"shared": 1}, {"new": 2}])
    assert original == {"shared": 1, "new": 2}


def test_merge_parallel_noops_without_modified_states():
    original = {"x": 1}
    merge_parallel_session_states(original, [])
    assert original == {"x": 1}