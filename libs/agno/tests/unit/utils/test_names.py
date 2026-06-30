from agno.utils.names import _ADJECTIVES, _NAMES, generate_human_readable_id


def test_word_list_sizes():
    """Word lists should be 64 entries each"""
    assert len(_ADJECTIVES) == 64
    assert len(_NAMES) == 64


def test_word_lists_all_lowercase_alpha():
    """All words should be lowercase alphabetic"""
    for word in _ADJECTIVES + _NAMES:
        assert word.isalpha() and word.islower(), f"Invalid word: {word}"


def test_word_lists_no_duplicates():
    """No duplicates within each list"""
    assert len(set(_ADJECTIVES)) == len(_ADJECTIVES)
    assert len(set(_NAMES)) == len(_NAMES)


def test_generate_human_readable_id_format():
    """Generated ID should match adjective-name-hex8 format"""
    result = generate_human_readable_id()
    parts = result.split("-")
    assert len(parts) == 3
    assert parts[0] in _ADJECTIVES
    assert parts[1] in _NAMES
    assert len(parts[2]) == 8
    int(parts[2], 16)  # must be valid hex


def test_generate_human_readable_id_uniqueness():
    """1000 generated IDs should all be unique"""
    ids = {generate_human_readable_id() for _ in range(1000)}
    assert len(ids) == 1000
