"""Unit tests for the user_id filter merge logic in ``Knowledge.search`` /
``asearch``.

These pin the load-bearing contract for K2 vector-DB isolation:

- When ``user_id`` is passed to search, the resulting filter must include
  ``OR(EQ("user_id", caller), EQ("user_id", SHARED_KNOWLEDGE_USER_ID))``
  so the caller sees their own chunks PLUS shared content.
- When ``user_id`` is ``None``, no owner predicate is added (admin /
  isolation-off behaviour).
- ``linked_to`` (instance scope) and ``user_id`` (owner scope) compose
  correctly without clobbering each other.

We test the filter-construction layer directly, not the SQL-execution
layer — the pgvector-side translation of these DSL filters to SQL is
already covered by pgvector's own tests.
"""

from typing import List

import pytest

from agno.filters import EQ, OR, FilterExpr
from agno.knowledge.knowledge import SHARED_KNOWLEDGE_USER_ID, Knowledge


@pytest.fixture
def kb_named():
    """A Knowledge instance with a name and vector-search isolation on.
    ``contents_db`` / ``vector_db`` are unset because these tests only
    exercise the in-memory filter-merging code."""
    kb = Knowledge(name="docs", isolate_vector_search=True)
    return kb


@pytest.fixture
def kb_unnamed():
    """Knowledge instance with no name — linked_to injection is disabled."""
    kb = Knowledge(name=None, isolate_vector_search=True)
    return kb


def _find_user_scope_or(filters: List[FilterExpr]) -> OR:
    """Locate the ``OR(EQ(user_id, X), EQ(user_id, '__shared__'))`` filter
    in the merged filter list. Asserts there's exactly one."""
    matches = [f for f in filters if isinstance(f, OR)]
    assert len(matches) == 1, (
        f"Expected exactly one OR filter for user scope; found {len(matches)}: {matches}"
    )
    return matches[0]


class TestUserIdNone:
    """Passing ``user_id=None`` must NOT add any owner predicate. This is
    the admin / RBAC-off path — admins see everything."""

    def test_no_filters_no_user_id(self, kb_unnamed):
        merged = kb_unnamed._inject_search_scope_filters(None, user_id=None)
        assert merged is None

    def test_dict_filters_no_user_id_preserved(self, kb_unnamed):
        original = {"topic": "ml"}
        merged = kb_unnamed._inject_search_scope_filters(original, user_id=None)
        # Should be unchanged
        assert merged == {"topic": "ml"}

    def test_list_filters_no_user_id_preserved(self, kb_unnamed):
        original = [EQ("topic", "ml")]
        merged = kb_unnamed._inject_search_scope_filters(original, user_id=None)
        assert len(merged) == 1
        assert isinstance(merged[0], EQ)
        assert merged[0].key == "topic"
        assert merged[0].value == "ml"


class TestUserIdInjection:
    """Passing a ``user_id`` string must add the user-scope OR filter."""

    def test_user_id_alone_promotes_to_list(self, kb_unnamed):
        merged = kb_unnamed._inject_search_scope_filters(None, user_id="alice")
        assert isinstance(merged, list)
        assert len(merged) == 1
        user_scope = _find_user_scope_or(merged)
        # The OR must contain exactly two EQ branches
        assert len(user_scope.expressions) == 2

    def test_user_scope_contains_caller_and_shared_sentinel(self, kb_unnamed):
        merged = kb_unnamed._inject_search_scope_filters(None, user_id="alice")
        user_scope = _find_user_scope_or(merged)

        # Extract the two branches' (key, value) pairs to compare set-wise
        branches = {(eq.key, eq.value) for eq in user_scope.expressions}
        assert branches == {
            ("user_id", "alice"),
            ("user_id", SHARED_KNOWLEDGE_USER_ID),
        }

    def test_dict_filters_get_promoted_to_list_when_user_id_passed(self, kb_unnamed):
        """Dict filters can't express OR, so the moment user_id is in the
        picture we have to convert to a list."""
        merged = kb_unnamed._inject_search_scope_filters({"topic": "ml"}, user_id="alice")
        assert isinstance(merged, list)
        # User scope OR should be present
        _find_user_scope_or(merged)
        # The original "topic": "ml" should still be there as an EQ
        topic_eqs = [f for f in merged if isinstance(f, EQ) and f.key == "topic"]
        assert len(topic_eqs) == 1
        assert topic_eqs[0].value == "ml"

    def test_list_filters_get_user_scope_prepended(self, kb_unnamed):
        existing_topic = EQ("topic", "ml")
        existing_cat = EQ("category", "research")
        merged = kb_unnamed._inject_search_scope_filters([existing_topic, existing_cat], user_id="alice")
        # User scope first, then existing (identity-preserving since we
        # don't mutate the input list).
        assert len(merged) == 3
        assert isinstance(merged[0], OR)
        assert merged[1] is existing_topic
        assert merged[2] is existing_cat


class TestLinkedToAndUserIdCompose:
    """``linked_to`` (instance scope) and ``user_id`` (owner scope) must
    coexist without clobbering each other."""

    def test_both_inject_when_both_apply(self, kb_named):
        merged = kb_named._inject_search_scope_filters(None, user_id="alice")
        assert isinstance(merged, list)

        # User scope OR present
        user_scope = _find_user_scope_or(merged)
        assert user_scope is not None

        # linked_to EQ present
        linked_to_eqs = [f for f in merged if isinstance(f, EQ) and f.key == "linked_to"]
        assert len(linked_to_eqs) == 1
        assert linked_to_eqs[0].value == "docs"

    def test_dict_filters_compose_with_both_scopes(self, kb_named):
        merged = kb_named._inject_search_scope_filters({"topic": "ml"}, user_id="alice")

        # user scope OR + linked_to EQ + topic EQ — all three
        assert isinstance(merged, list)
        _find_user_scope_or(merged)

        keys_present = {f.key for f in merged if isinstance(f, EQ)}
        assert "linked_to" in keys_present
        assert "topic" in keys_present

    def test_linked_to_only_when_no_user_id(self, kb_named):
        """When only instance scope applies (no user_id), the dict path is
        preserved for backward compatibility."""
        merged = kb_named._inject_search_scope_filters(None, user_id=None)
        # Should be a dict with linked_to
        assert merged == {"linked_to": "docs"}


class TestSharedSentinelValue:
    """The shared sentinel must be exactly the documented constant value —
    inserts and searches both depend on this string matching."""

    def test_sentinel_is_double_underscore_shared(self):
        # If this value changes, every chunk previously inserted with the
        # old sentinel becomes invisible. Pin it explicitly.
        assert SHARED_KNOWLEDGE_USER_ID == "__shared__"


class TestBuildUserScopeFilterHelper:
    """The helper used by ``_inject_search_scope_filters`` — used directly
    by anyone who needs to construct the predicate themselves (e.g. agent
    tool customisation)."""

    def test_helper_returns_or_with_two_eq_branches(self, kb_unnamed):
        f = kb_unnamed._build_user_scope_filter("bob")
        assert isinstance(f, OR)
        assert len(f.expressions) == 2

    def test_helper_branches_are_caller_and_shared(self, kb_unnamed):
        f = kb_unnamed._build_user_scope_filter("bob")
        branches = {(eq.key, eq.value) for eq in f.expressions}
        assert branches == {
            ("user_id", "bob"),
            ("user_id", SHARED_KNOWLEDGE_USER_ID),
        }
