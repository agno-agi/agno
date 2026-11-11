"""Tests for same_user, the owner-id comparison used by the learnings scope guard."""

from uuid import UUID

from agno.learn.utils import build_learning_id, same_user


class TestSameUser:
    def test_matching_strings(self):
        assert same_user("user-A", "user-A") is True

    def test_different_strings(self):
        assert same_user("user-A", "user-B") is False

    def test_non_string_matches_its_str(self):
        # A writer that passed an int user_id leaves an int in stores that do not type the
        # column; the same identity arrives from the request as the JWT subject string.
        assert same_user(123, "123") is True
        assert same_user("123", 123) is True

    def test_non_string_does_not_match_a_different_id(self):
        assert same_user(123, "456") is False
        assert same_user(456, "123") is False

    def test_uuid_matches_its_canonical_string(self):
        uid = UUID("2f8a1b7c-0d3e-4f5a-9b6c-7d8e9f0a1b2c")
        assert same_user(uid, str(uid)) is True
        assert same_user(uid, "2f8a1b7c-0d3e-4f5a-9b6c-7d8e9f0a1b2c") is True

    def test_none_never_matches(self):
        assert same_user(None, "user-A") is False
        assert same_user("user-A", None) is False
        assert same_user(None, None) is False

    def test_empty_string_is_not_none(self):
        assert same_user("", "") is True
        assert same_user("", "user-A") is False

    def test_zero_is_not_none(self):
        assert same_user(0, "0") is True
        assert same_user(0, None) is False

    def test_bool_and_int_are_distinct_ids(self):
        assert same_user(True, "1") is False
        assert same_user(1, "True") is False

    def test_agrees_with_the_entity_key(self):
        # The record id derived for a non-string user_id is the same one derived for its
        # str(), so a record written by either reconciles with the other.
        assert build_learning_id("user_profile", user_id=123) == build_learning_id("user_profile", user_id="123")  # type: ignore[arg-type]
        assert same_user(123, "123") is True
