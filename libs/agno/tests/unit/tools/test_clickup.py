"""ClickUpTools._find_by_name must not crash when a literal name contains regex
metacharacters; the unconditional re.compile raised re.error and left the exact-match
path unreachable."""

from agno.tools.clickup import ClickUpTools

_find_by_name = ClickUpTools._find_by_name


def test_literal_name_with_regex_metacharacters_matches_exactly():
    for name in ["*Sprint", "Design [v2", "Sales (West"]:
        items = [{"name": name}, {"name": "Other"}]
        assert _find_by_name(None, items, name) == {"name": name}


def test_invalid_pattern_with_no_exact_match_returns_none():
    assert _find_by_name(None, [{"name": "other"}], "Sales (West") is None


def test_fuzzy_and_exact_matches_still_work():
    assert _find_by_name(None, [{"name": "Sprint 1"}], "Spr") == {"name": "Sprint 1"}
    assert _find_by_name(None, [{"name": "Backlog"}], "backlog") == {"name": "Backlog"}


def test_item_without_name_key_does_not_crash():
    assert _find_by_name(None, [{"id": 1}, {"name": "x"}], "x") == {"name": "x"}
