"""Unit tests for metadata utility functions in agno.knowledge.utils."""

from agno.knowledge.utils import (
    RESERVED_AGNO_KEY,
    get_agno_metadata,
    merge_user_metadata,
    set_agno_metadata,
    strip_agno_metadata,
)

# =============================================================================
# merge_user_metadata
# =============================================================================


class TestMergeUserMetadata:
    def test_none_existing_returns_incoming(self):
        incoming = {"key": "value"}
        assert merge_user_metadata(None, incoming) == incoming

    def test_empty_existing_returns_incoming(self):
        incoming = {"key": "value"}
        assert merge_user_metadata({}, incoming) == incoming

    def test_none_incoming_returns_existing(self):
        existing = {"key": "value"}
        assert merge_user_metadata(existing, None) == existing

    def test_empty_incoming_returns_existing(self):
        existing = {"key": "value"}
        assert merge_user_metadata(existing, {}) == existing

    def test_both_none_returns_none(self):
        assert merge_user_metadata(None, None) is None

    def test_incoming_overwrites_existing_keys(self):
        existing = {"a": 1, "b": 2}
        incoming = {"b": 99, "c": 3}
        result = merge_user_metadata(existing, incoming)
        assert result == {"a": 1, "b": 99, "c": 3}

    def test_agno_keys_are_deep_merged(self):
        existing = {"_agno": {"source_type": "s3", "bucket": "my-bucket"}, "user_key": "x"}
        incoming = {"_agno": {"source_url": "https://example.com"}, "user_key": "y"}
        result = merge_user_metadata(existing, incoming)
        assert result["_agno"] == {
            "source_type": "s3",
            "bucket": "my-bucket",
            "source_url": "https://example.com",
        }
        assert result["user_key"] == "y"

    def test_agno_incoming_overwrites_conflicting_agno_keys(self):
        existing = {"_agno": {"status": "old"}}
        incoming = {"_agno": {"status": "new"}}
        result = merge_user_metadata(existing, incoming)
        assert result["_agno"]["status"] == "new"

    def test_agno_non_dict_incoming_treated_as_empty(self):
        existing = {"_agno": {"key": "value"}}
        incoming = {"_agno": "not-a-dict"}
        result = merge_user_metadata(existing, incoming)
        assert result["_agno"] == {"key": "value"}

    def test_does_not_mutate_existing(self):
        existing = {"a": 1, "_agno": {"x": 1}}
        incoming = {"a": 2, "_agno": {"y": 2}}
        original_existing = {"a": 1, "_agno": {"x": 1}}
        merge_user_metadata(existing, incoming)
        assert existing == original_existing


# =============================================================================
# set_agno_metadata
# =============================================================================


class TestSetAgnoMetadata:
    def test_sets_key_on_none_metadata(self):
        result = set_agno_metadata(None, "source_type", "url")
        assert result == {"_agno": {"source_type": "url"}}

    def test_sets_key_on_empty_metadata(self):
        result = set_agno_metadata({}, "source_type", "s3")
        assert result == {"_agno": {"source_type": "s3"}}

    def test_sets_key_preserving_existing_user_metadata(self):
        metadata = {"user_key": "value"}
        result = set_agno_metadata(metadata, "source_type", "gcs")
        assert result["user_key"] == "value"
        assert result["_agno"]["source_type"] == "gcs"

    def test_sets_key_preserving_existing_agno_keys(self):
        metadata = {"_agno": {"existing_key": "keep"}}
        result = set_agno_metadata(metadata, "new_key", "added")
        assert result["_agno"] == {"existing_key": "keep", "new_key": "added"}

    def test_overwrites_existing_agno_key(self):
        metadata = {"_agno": {"status": "old"}}
        result = set_agno_metadata(metadata, "status", "new")
        assert result["_agno"]["status"] == "new"

    def test_returns_same_dict_reference(self):
        metadata = {"key": "value"}
        result = set_agno_metadata(metadata, "x", 1)
        assert result is metadata

    def test_handles_none_agno_value_in_metadata(self):
        metadata = {"_agno": None}
        result = set_agno_metadata(metadata, "key", "value")
        assert result["_agno"] == {"key": "value"}


# =============================================================================
# get_agno_metadata
# =============================================================================


class TestGetAgnoMetadata:
    def test_returns_none_for_none_metadata(self):
        assert get_agno_metadata(None, "key") is None

    def test_returns_none_for_empty_metadata(self):
        assert get_agno_metadata({}, "key") is None

    def test_returns_none_when_agno_missing(self):
        assert get_agno_metadata({"user_key": "value"}, "key") is None

    def test_returns_none_when_agno_is_not_dict(self):
        assert get_agno_metadata({"_agno": "string"}, "key") is None

    def test_returns_none_when_key_not_in_agno(self):
        assert get_agno_metadata({"_agno": {"other": "value"}}, "key") is None

    def test_returns_value_for_existing_key(self):
        metadata = {"_agno": {"source_type": "url", "source_url": "https://example.com"}}
        assert get_agno_metadata(metadata, "source_type") == "url"
        assert get_agno_metadata(metadata, "source_url") == "https://example.com"

    def test_returns_falsy_values_correctly(self):
        metadata = {"_agno": {"count": 0, "flag": False, "empty": ""}}
        assert get_agno_metadata(metadata, "count") == 0
        assert get_agno_metadata(metadata, "flag") is False
        assert get_agno_metadata(metadata, "empty") == ""


# =============================================================================
# strip_agno_metadata
# =============================================================================


class TestStripAgnoMetadata:
    def test_returns_none_for_none(self):
        assert strip_agno_metadata(None) is None

    def test_returns_empty_for_empty(self):
        result = strip_agno_metadata({})
        assert result is not None
        assert result == {}

    def test_strips_agno_key(self):
        metadata = {"user_key": "value", "_agno": {"source_type": "s3"}}
        result = strip_agno_metadata(metadata)
        assert result == {"user_key": "value"}
        assert "_agno" not in result

    def test_returns_copy_not_original(self):
        metadata = {"key": "value", "_agno": {"x": 1}}
        result = strip_agno_metadata(metadata)
        assert result is not metadata

    def test_preserves_all_non_agno_keys(self):
        metadata = {"a": 1, "b": "two", "c": [3], "_agno": {"internal": True}}
        result = strip_agno_metadata(metadata)
        assert result == {"a": 1, "b": "two", "c": [3]}

    def test_no_agno_key_returns_copy(self):
        metadata = {"key": "value"}
        result = strip_agno_metadata(metadata)
        assert result == {"key": "value"}
        assert result is not metadata

    def test_does_not_mutate_original(self):
        metadata = {"key": "value", "_agno": {"x": 1}}
        strip_agno_metadata(metadata)
        assert "_agno" in metadata


# =============================================================================
# RESERVED_AGNO_KEY constant
# =============================================================================


def test_reserved_agno_key_value():
    assert RESERVED_AGNO_KEY == "_agno"
