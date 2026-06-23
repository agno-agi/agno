"""Adversarial tests for DatabricksVectorDb -- edge cases designed to break the implementation."""

from unittest.mock import MagicMock, patch

import pytest

from agno.filters import AND, EQ, NOT, OR
from agno.knowledge.document import Document
from agno.vectordb.databricks import DatabricksVectorDb


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_embedder():
    embedder = MagicMock()
    embedder.dimensions = 3
    embedder.get_embedding.return_value = [0.1, 0.2, 0.3]
    embedder.get_embedding_and_usage.return_value = ([0.1, 0.2, 0.3], {"prompt_tokens": 3, "total_tokens": 3})
    return embedder


@pytest.fixture
def mock_vector_client():
    client = MagicMock()
    client.index_exists.return_value = False
    return client


@pytest.fixture
def mock_vector_index():
    index = MagicMock()
    index.wait_until_ready.return_value = None
    # Default: empty index (scan returns nothing)
    index.scan.return_value = {"data": [], "last_primary_key": None}
    index.similarity_search.return_value = {
        "manifest": {"columns": []},
        "result": {"data_array": []},
    }
    index.describe.return_value = {}
    return index


def _make_db(mock_embedder, mock_vector_client, mock_vector_index, **overrides):
    kwargs = dict(
        endpoint_name="vs-endpoint",
        index_name="catalog.schema.index",
        host="https://example.cloud.databricks.com",
        token="dapi-test",
        embedder=mock_embedder,
    )
    kwargs.update(overrides)
    with patch("agno.vectordb.databricks.databricks._get_vector_search_client_cls", return_value=MagicMock()):
        db = DatabricksVectorDb(**kwargs)
        db._client = mock_vector_client
        db._index = mock_vector_index
        # Mark defaults loaded so search doesn't try to auto-configure
        db._index_defaults_loaded = True
        db._auto_configure_index = False
    return db


@pytest.fixture
def db(mock_embedder, mock_vector_client, mock_vector_index):
    return _make_db(mock_embedder, mock_vector_client, mock_vector_index)


# ===========================================================================
# 1. Empty / None document content
# ===========================================================================


class TestEmptyNoneDocumentContent:
    def test_upsert_document_with_none_content(self, db, mock_embedder):
        """Document.content is typed as str but callers may pass None."""
        doc = Document(content=None)  # type: ignore[arg-type]
        db.upsert(content_hash="h1", documents=[doc])
        # embed() should have been called since embedding is None
        mock_embedder.get_embedding_and_usage.assert_called_once()
        db.index.upsert.assert_called_once()

    def test_upsert_document_with_empty_string_content(self, db, mock_embedder):
        doc = Document(content="")
        db.upsert(content_hash="h1", documents=[doc])
        db.index.upsert.assert_called_once()
        row = db.index.upsert.call_args.args[0][0]
        assert row["content"] == ""

    def test_upsert_document_with_whitespace_only_content(self, db, mock_embedder):
        doc = Document(content="   \n\t  ")
        db.upsert(content_hash="h1", documents=[doc])
        db.index.upsert.assert_called_once()
        row = db.index.upsert.call_args.args[0][0]
        assert row["content"] == "   \n\t  "


# ===========================================================================
# 2. Empty embedding
# ===========================================================================


class TestEmptyEmbedding:
    def test_document_with_empty_list_embedding_triggers_embed(self, db, mock_embedder):
        doc = Document(content="hello", embedding=[])
        db.upsert(content_hash="h1", documents=[doc])
        mock_embedder.get_embedding_and_usage.assert_called_once_with("hello")

    def test_document_with_none_embedding_triggers_embed(self, db, mock_embedder):
        doc = Document(content="hello", embedding=None)
        db.upsert(content_hash="h1", documents=[doc])
        mock_embedder.get_embedding_and_usage.assert_called_once_with("hello")

    def test_document_with_valid_embedding_skips_embed(self, db, mock_embedder):
        doc = Document(content="hello", embedding=[0.5, 0.6, 0.7])
        db.upsert(content_hash="h1", documents=[doc])
        mock_embedder.get_embedding_and_usage.assert_not_called()


# ===========================================================================
# 3. Upsert with empty documents list
# ===========================================================================


class TestUpsertEmptyDocumentsList:
    def test_upsert_empty_list_is_noop(self, db):
        db.upsert(content_hash="h1", documents=[])
        db.index.upsert.assert_not_called()
        db.index.scan.assert_not_called()

    def test_upsert_none_documents_raises_or_noop(self, db):
        """Passing None where List[Document] is expected."""
        # The implementation checks `if not documents:` -- None is falsy so this should be a no-op
        db.upsert(content_hash="h1", documents=None)  # type: ignore[arg-type]
        db.index.upsert.assert_not_called()


# ===========================================================================
# 4. Search with empty query string
# ===========================================================================


class TestSearchEmptyQuery:
    def test_search_empty_string_calls_embedder(self, db, mock_embedder):
        db.search("", limit=5)
        mock_embedder.get_embedding.assert_called_once_with("")

    def test_search_empty_string_returns_empty_when_embedder_returns_empty(self, db, mock_embedder):
        mock_embedder.get_embedding.return_value = []
        result = db.search("", limit=5)
        assert result == []


# ===========================================================================
# 5. Search with limit=0 or limit=-1
# ===========================================================================


class TestSearchLimitEdgeCases:
    def test_search_limit_zero(self, db, mock_embedder):
        """limit=0 is passed straight to the SDK -- it may return nothing or raise."""
        db.search("query", limit=0)
        call_kwargs = db.index.similarity_search.call_args.kwargs
        assert call_kwargs["num_results"] == 0

    def test_search_limit_negative(self, db, mock_embedder):
        db.search("query", limit=-1)
        call_kwargs = db.index.similarity_search.call_args.kwargs
        assert call_kwargs["num_results"] == -1


# ===========================================================================
# 6. Filters edge cases
# ===========================================================================


class TestFilterEdgeCases:
    def test_deeply_nested_and_or_not(self, db, mock_embedder):
        """Deep nesting should not crash the implementation."""
        deep = EQ("a", 1)
        for _ in range(20):
            deep = AND(NOT(OR(deep, EQ("b", 2))))
        db.search("query", limit=5, filters=[deep])
        db.index.similarity_search.assert_called_once()

    def test_filter_with_nonexistent_key(self, db, mock_embedder):
        """Filter referencing a key that doesn't exist in any row should return empty."""
        db.index.similarity_search.return_value = {
            "manifest": {"columns": [{"name": "id"}, {"name": "content"}]},
            "result": {
                "data_array": [["doc1", "hello"]],
            },
        }
        results = db.search("query", limit=5, filters=[EQ("nonexistent_key", "val")])
        assert results == []

    def test_dict_filter_with_metadata_column_name_excluded(self, db, mock_embedder):
        """meta_data column itself should NOT be forwarded as a provider filter."""
        pf = db._build_provider_filters({"meta_data": '{"key": "val"}'})
        assert pf is None  # meta_data is excluded

    def test_dict_filter_with_embedding_column_excluded(self, db, mock_embedder):
        pf = db._build_provider_filters({"embedding": [0.1, 0.2]})
        assert pf is None

    def test_dict_filter_with_usage_column_excluded(self, db, mock_embedder):
        pf = db._build_provider_filters({"usage": "some"})
        assert pf is None

    def test_empty_filter_list(self, db, mock_embedder):
        """An empty filter list [] should not crash."""
        db.index.similarity_search.return_value = {
            "manifest": {"columns": [{"name": "id"}, {"name": "content"}]},
            "result": {"data_array": [["doc1", "hello"]]},
        }
        results = db.search("query", limit=5, filters=[])
        # Empty list means all() on empty => True, so all rows should pass
        assert len(results) == 1

    def test_wrong_filter_type_string(self, db, mock_embedder):
        """Passing a string instead of dict or list should not crash."""
        # _build_provider_filters returns None for non-dict, non-list
        pf = db._build_provider_filters("bad_filter")  # type: ignore[arg-type]
        assert pf is None

    def test_build_provider_filters_none(self, db):
        assert db._build_provider_filters(None) is None


# ===========================================================================
# 7. Schema auto-discovery edge cases
# ===========================================================================


class TestSchemaAutoDiscovery:
    def _make_auto_db(self, mock_embedder, mock_vector_client, mock_vector_index):
        with patch("agno.vectordb.databricks.databricks._get_vector_search_client_cls", return_value=MagicMock()):
            db_obj = DatabricksVectorDb(
                endpoint_name="vs-endpoint",
                index_name="catalog.schema.index",
                host="https://example.cloud.databricks.com",
                token="dapi-test",
                embedder=mock_embedder,
            )
            db_obj._client = mock_vector_client
            db_obj._index = mock_vector_index
        return db_obj

    def test_describe_returns_none(self, mock_embedder, mock_vector_client, mock_vector_index):
        mock_vector_index.describe.return_value = None
        mock_vector_index.scan.return_value = {"data": [], "last_primary_key": None}
        db_obj = self._make_auto_db(mock_embedder, mock_vector_client, mock_vector_index)
        # Should not crash
        db_obj._ensure_index_defaults_loaded()
        assert db_obj._index_defaults_loaded is True

    def test_describe_returns_empty_dict(self, mock_embedder, mock_vector_client, mock_vector_index):
        mock_vector_index.describe.return_value = {}
        mock_vector_index.scan.return_value = {"data": [], "last_primary_key": None}
        db_obj = self._make_auto_db(mock_embedder, mock_vector_client, mock_vector_index)
        db_obj._ensure_index_defaults_loaded()
        assert db_obj._index_defaults_loaded is True

    def test_describe_raises_exception(self, mock_embedder, mock_vector_client, mock_vector_index):
        mock_vector_index.describe.side_effect = Exception("Network error")
        db_obj = self._make_auto_db(mock_embedder, mock_vector_client, mock_vector_index)
        db_obj._ensure_index_defaults_loaded()
        assert db_obj._index_defaults_loaded is True

    def test_scan_returns_empty_rows(self, mock_embedder, mock_vector_client, mock_vector_index):
        mock_vector_index.describe.return_value = {}
        mock_vector_index.scan.return_value = {"data": [], "last_primary_key": None}
        db_obj = self._make_auto_db(mock_embedder, mock_vector_client, mock_vector_index)
        db_obj._ensure_index_defaults_loaded()
        # Schema should remain as default
        assert "id" in db_obj.schema

    def test_scan_returns_struct_fields_format(self, mock_embedder, mock_vector_client, mock_vector_index):
        """Rows with 'fields' key (struct format from Databricks)."""
        mock_vector_index.describe.return_value = {}
        mock_vector_index.scan.return_value = {
            "data": [
                {
                    "fields": [
                        {"key": "pk", "value": {"string_value": "row1"}},
                        {"key": "vec", "value": {"list_value": {"values": [{"number_value": 0.1}]}}},
                        {"key": "text", "value": {"string_value": "content here"}},
                    ]
                }
            ],
            "last_primary_key": "row1",
        }
        db_obj = self._make_auto_db(mock_embedder, mock_vector_client, mock_vector_index)
        db_obj._ensure_index_defaults_loaded()
        assert db_obj._index_defaults_loaded is True
        assert "pk" in db_obj.schema

    def test_data_array_with_mismatched_column_count(self, db):
        """data_array row has fewer columns than the manifest declares."""
        response = {
            "manifest": {
                "columns": [{"name": "id"}, {"name": "content"}, {"name": "extra"}],
            },
            "result": {
                "data_array": [
                    ["doc1", "hello"],  # missing 'extra'
                ],
            },
        }
        rows, cursor = db._extract_rows_and_cursor(response)
        assert len(rows) == 1
        assert rows[0].get("id") == "doc1"
        assert rows[0].get("content") == "hello"
        assert "extra" not in rows[0]  # zip truncates

    def test_data_array_with_extra_columns(self, db):
        """data_array row has more columns than manifest declares."""
        response = {
            "manifest": {
                "columns": [{"name": "id"}],
            },
            "result": {
                "data_array": [
                    ["doc1", "extra_value", "another"],
                ],
            },
        }
        rows, _ = db._extract_rows_and_cursor(response)
        assert len(rows) == 1
        assert rows[0] == {"id": "doc1"}  # extras silently dropped


# ===========================================================================
# 8. Delete edge cases
# ===========================================================================


class TestDeleteEdgeCases:
    def test_delete_by_id_nonexistent(self, db):
        """Deleting a non-existent ID should return False."""
        result = db.delete_by_id("nonexistent-id")
        assert result is False
        db.index.delete.assert_not_called()

    def test_delete_by_name_none(self, db):
        """Passing None as name should return False (no match)."""
        result = db.delete_by_name(None)  # type: ignore[arg-type]
        assert result is False

    def test_delete_by_metadata_empty_dict(self, db):
        """Empty metadata dict should match everything (every key matches vacuously)."""
        db.index.scan.side_effect = [
            {
                "data": [{"id": "doc1", "content": "a", "meta_data": "{}"}],
                "last_primary_key": "doc1",
            },
            {"data": [], "last_primary_key": None},
        ]
        result = db.delete_by_metadata({})
        # Empty filter matches all -- should delete
        assert result is True
        db.index.delete.assert_called_once_with(primary_keys=["doc1"])

    def test_delete_on_empty_index(self, db):
        result = db.delete()
        assert result is False
        db.index.delete.assert_not_called()


# ===========================================================================
# 9. Pagination / _scan_all_rows edge cases
# ===========================================================================


class TestScanAllRowsEdgeCases:
    def test_scan_next_primary_key_equals_last_prevents_infinite_loop(self, db):
        """If next_primary_key never advances, _scan_all_rows must stop."""
        db.index.scan.side_effect = [
            {
                "data": [{"id": "stuck", "content": "data"}],
                "last_primary_key": "stuck",
            },
            {
                "data": [{"id": "stuck2", "content": "data2"}],
                "last_primary_key": "stuck",  # same key as we sent -- stuck!
            },
        ]
        rows = db._scan_all_rows()
        # Should stop after second batch since next_primary_key == last_primary_key
        assert len(rows) == 2
        assert db.index.scan.call_count == 2

    def test_scan_returns_none_cursor_stops(self, db):
        db.index.scan.side_effect = [
            {
                "data": [{"id": "doc1"}],
                "last_primary_key": None,
            },
        ]
        rows = db._scan_all_rows()
        assert len(rows) == 1

    def test_scan_empty_first_batch(self, db):
        db.index.scan.return_value = {"data": [], "last_primary_key": None}
        rows = db._scan_all_rows()
        assert rows == []


# ===========================================================================
# 10. Content hash collision
# ===========================================================================


class TestContentHashCollision:
    def test_two_docs_same_content_hash_different_content_get_separate_ids(self, db, mock_embedder):
        doc1 = Document(content="content A")
        doc2 = Document(content="content B")
        with patch.object(db, "_scan_all_rows", return_value=[]):
            db.upsert(content_hash="same-hash", documents=[doc1, doc2])
        rows = db.index.upsert.call_args.args[0]
        ids = [r["id"] for r in rows]
        assert ids[0] != ids[1], "Two different docs with same content_hash should get different IDs"

    def test_same_content_same_hash_produces_same_id(self, db, mock_embedder):
        doc1 = Document(content="identical")
        doc2 = Document(content="identical")
        with patch.object(db, "_scan_all_rows", return_value=[]):
            db.upsert(content_hash="h1", documents=[doc1, doc2])
        rows = db.index.upsert.call_args.args[0]
        ids = [r["id"] for r in rows]
        # Same content + same content_hash => same md5 => same id (potential collision!)
        assert ids[0] == ids[1]


# ===========================================================================
# 11. Special characters in document IDs, names, content
# ===========================================================================


class TestSpecialCharacters:
    def test_unicode_content(self, db, mock_embedder):
        doc = Document(content="Hello \u4e16\u754c \U0001f30d \u00e9\u00e8\u00ea \u00fc\u00f6\u00e4")
        db.upsert(content_hash="h1", documents=[doc])
        row = db.index.upsert.call_args.args[0][0]
        assert row["content"] == "Hello \u4e16\u754c \U0001f30d \u00e9\u00e8\u00ea \u00fc\u00f6\u00e4"

    def test_null_bytes_in_content(self, db, mock_embedder):
        doc = Document(content="hello\x00world")
        db.upsert(content_hash="h1", documents=[doc])
        row = db.index.upsert.call_args.args[0][0]
        assert "\x00" in row["content"]

    def test_very_long_string_content(self, db, mock_embedder):
        long_content = "x" * 10_000_000  # 10 MB
        doc = Document(content=long_content)
        db.upsert(content_hash="h1", documents=[doc])
        row = db.index.upsert.call_args.args[0][0]
        assert len(row["content"]) == 10_000_000

    def test_special_chars_in_document_id(self, db, mock_embedder):
        doc = Document(content="test", id="id/with:special chars&symbols=true")
        db.upsert(content_hash="h1", documents=[doc])
        row = db.index.upsert.call_args.args[0][0]
        assert row["id"] == "id/with:special chars&symbols=true"

    def test_empty_name(self, db, mock_embedder):
        doc = Document(content="test", name="")
        db.upsert(content_hash="h1", documents=[doc])
        row = db.index.upsert.call_args.args[0][0]
        assert row["name"] == ""

    def test_name_with_json_injection(self, db, mock_embedder):
        doc = Document(content="test", name='"}; DROP TABLE --')
        db.upsert(content_hash="h1", documents=[doc])
        row = db.index.upsert.call_args.args[0][0]
        assert row["name"] == '"}; DROP TABLE --'


# ===========================================================================
# 12. _extract_rows_and_cursor edge cases
# ===========================================================================


class TestExtractRowsAndCursor:
    def test_response_is_none(self, db):
        rows, cursor = db._extract_rows_and_cursor(None)
        assert rows == []
        assert cursor is None

    def test_response_is_string(self, db):
        rows, cursor = db._extract_rows_and_cursor("unexpected")
        assert rows == []
        assert cursor is None

    def test_response_is_integer(self, db):
        rows, cursor = db._extract_rows_and_cursor(42)
        assert rows == []
        assert cursor is None

    def test_response_is_empty_dict(self, db):
        rows, cursor = db._extract_rows_and_cursor({})
        assert rows == []
        assert cursor is None

    def test_response_is_list_of_dicts(self, db):
        rows, cursor = db._extract_rows_and_cursor([{"id": "a"}, {"id": "b"}])
        assert len(rows) == 2
        assert cursor is None

    def test_response_is_empty_list(self, db):
        rows, cursor = db._extract_rows_and_cursor([])
        assert rows == []
        assert cursor is None

    def test_response_result_is_none(self, db):
        rows, cursor = db._extract_rows_and_cursor({"result": None})
        assert rows == []

    def test_response_with_result_and_no_data(self, db):
        rows, cursor = db._extract_rows_and_cursor({"result": {}})
        assert rows == []

    def test_response_with_records_key(self, db):
        rows, cursor = db._extract_rows_and_cursor({"records": [{"id": "rec1"}]})
        assert len(rows) == 1
        assert rows[0]["id"] == "rec1"

    def test_response_with_results_key(self, db):
        rows, cursor = db._extract_rows_and_cursor({"results": [{"id": "res1"}]})
        assert len(rows) == 1

    def test_response_with_next_primary_key(self, db):
        rows, cursor = db._extract_rows_and_cursor({
            "data": [{"id": "d1"}],
            "next_primary_key": "npk",
        })
        assert cursor == "npk"

    def test_nested_result_with_records(self, db):
        rows, cursor = db._extract_rows_and_cursor({
            "result": {
                "records": [{"id": "r1"}],
                "last_primary_key": "lpk",
            }
        })
        assert len(rows) == 1
        assert cursor == "lpk"

    def test_data_array_non_list_items_skipped(self, db):
        """Non-list items in data_array should be skipped."""
        response = {
            "manifest": {"columns": [{"name": "id"}]},
            "result": {
                "data_array": [
                    ["good"],
                    "bad_string",
                    {"bad": "dict"},
                    None,
                    ["also_good"],
                ],
            },
        }
        rows, _ = db._extract_rows_and_cursor(response)
        assert len(rows) == 2
        assert rows[0]["id"] == "good"
        assert rows[1]["id"] == "also_good"

    def test_manifest_columns_as_strings(self, db):
        """Manifest columns can be plain strings instead of dicts."""
        response = {
            "manifest": {"columns": ["id", "content"]},
            "result": {
                "data_array": [["doc1", "hello"]],
            },
        }
        rows, _ = db._extract_rows_and_cursor(response)
        assert rows[0]["id"] == "doc1"
        assert rows[0]["content"] == "hello"

    def test_manifest_columns_mixed_format(self, db):
        response = {
            "manifest": {"columns": [{"name": "id"}, "content", 42]},  # 42 is neither dict nor str
            "result": {
                "data_array": [["doc1", "hello", "extra"]],
            },
        }
        rows, _ = db._extract_rows_and_cursor(response)
        # Only 2 column names extracted: "id" and "content"; 42 is dropped
        assert rows[0].get("id") == "doc1"
        assert rows[0].get("content") == "hello"


# ===========================================================================
# 13. update_metadata on non-existent content_id
# ===========================================================================


class TestUpdateMetadataEdgeCases:
    def test_update_metadata_nonexistent_content_id(self, db):
        db.update_metadata("nonexistent-cid", {"key": "value"})
        db.index.upsert.assert_not_called()

    def test_update_metadata_empty_metadata(self, db):
        db.index.scan.side_effect = [
            {
                "data": [{"id": "doc1", "content_id": "cid1", "meta_data": '{"existing": "val"}'}],
                "last_primary_key": "doc1",
            },
            {"data": [], "last_primary_key": None},
        ]
        db.update_metadata("cid1", {})
        db.index.upsert.assert_called_once()
        row = db.index.upsert.call_args.args[0][0]
        # Should preserve existing metadata
        assert '"existing"' in row["meta_data"]

    def test_update_metadata_with_corrupt_existing_metadata(self, db):
        """Existing meta_data is not valid JSON."""
        db.index.scan.side_effect = [
            {
                "data": [{"id": "doc1", "content_id": "cid1", "meta_data": "NOT_JSON{{{"}],
                "last_primary_key": "doc1",
            },
            {"data": [], "last_primary_key": None},
        ]
        db.update_metadata("cid1", {"new_key": "new_val"})
        db.index.upsert.assert_called_once()
        row = db.index.upsert.call_args.args[0][0]
        import json
        merged = json.loads(row["meta_data"])
        assert merged["new_key"] == "new_val"


# ===========================================================================
# Additional edge cases
# ===========================================================================


class TestNormalizeRowsEdgeCases:
    def test_normalize_rows_none(self, db):
        assert db._normalize_rows(None, None) == []

    def test_normalize_rows_non_list(self, db):
        assert db._normalize_rows("string", None) == []

    def test_normalize_rows_list_of_mixed_types(self, db):
        """A list that is neither all dicts nor all lists."""
        result = db._normalize_rows([{"a": 1}, [1, 2]], None)
        # Not all dicts, not all lists -- should return []
        assert result == []

    def test_normalize_rows_list_of_lists_without_manifest(self, db):
        """List of lists with no manifest columns."""
        result = db._normalize_rows([["val1", "val2"]], None)
        # No manifest columns => zip with [] => empty dicts
        assert result == [{}]


class TestDecodeStructFields:
    def test_decode_struct_fields_empty(self, db):
        assert db._decode_struct_fields([]) == {}

    def test_decode_struct_fields_missing_key(self, db):
        result = db._decode_struct_fields([{"value": {"string_value": "v"}}])
        assert result == {}

    def test_decode_struct_fields_non_string_key(self, db):
        result = db._decode_struct_fields([{"key": 123, "value": {"string_value": "v"}}])
        assert result == {}  # key must be str

    def test_decode_null_value(self, db):
        result = db._decode_databricks_value({"null_value": 0})
        assert result is None

    def test_decode_bool_value(self, db):
        result = db._decode_databricks_value({"bool_value": False})
        assert result is False

    def test_decode_nested_struct_value(self, db):
        result = db._decode_databricks_value({
            "struct_value": {
                "fields": [
                    {"key": "inner", "value": {"string_value": "nested"}}
                ]
            }
        })
        assert result == {"inner": "nested"}

    def test_decode_unknown_value_type(self, db):
        """Value dict with unknown keys is returned as-is."""
        val = {"custom_type": "something"}
        result = db._decode_databricks_value(val)
        assert result == val

    def test_decode_number_value_integer(self, db):
        result = db._decode_databricks_value({"number_value": 5.0})
        assert result == 5
        assert isinstance(result, int)

    def test_decode_number_value_float(self, db):
        result = db._decode_databricks_value({"number_value": 3.14})
        assert result == 3.14
        assert isinstance(result, float)


class TestInferSchemaType:
    def test_infer_bool(self, db):
        assert db._infer_schema_type(True) == "boolean"

    def test_infer_int(self, db):
        assert db._infer_schema_type(42) == "long"

    def test_infer_float(self, db):
        assert db._infer_schema_type(3.14) == "double"

    def test_infer_dict(self, db):
        assert db._infer_schema_type({"k": "v"}) == "map<string,string>"

    def test_infer_empty_list(self, db):
        assert db._infer_schema_type([]) == "array<string>"

    def test_infer_list_of_strings(self, db):
        assert db._infer_schema_type(["a", "b"]) == "array<string>"

    def test_infer_none(self, db):
        assert db._infer_schema_type(None) == "string"


class TestRowMetadataEdgeCases:
    def test_metadata_is_empty_string(self, db):
        result = db._row_metadata({"meta_data": ""})
        assert result == {}

    def test_metadata_is_non_dict_json(self, db):
        """meta_data that is valid JSON but not a dict (e.g., a list)."""
        result = db._row_metadata({"meta_data": "[1, 2, 3]"})
        # parsed is a list, not dict, so falls through to field-based extraction
        assert result == {}

    def test_metadata_is_dict_object(self, db):
        result = db._row_metadata({"meta_data": {"already": "parsed"}})
        assert result == {"already": "parsed"}


class TestRowFromDocumentEdgeCases:
    def test_none_values_stripped(self, db, mock_embedder):
        """Rows should not contain None values (Databricks SDK rejects them)."""
        doc = Document(content="hello", name=None, content_id=None)
        row = db._row_from_document(doc, "hash1")
        for key, value in row.items():
            assert value is not None, f"Key '{key}' has None value"

    def test_filters_added_to_metadata_and_row(self, db, mock_embedder):
        db.schema["tenant"] = "string"
        doc = Document(content="test", meta_data={"existing": "val"})
        row = db._row_from_document(doc, "hash1", filters={"tenant": "acme"})
        import json
        meta = json.loads(row["meta_data"])
        assert meta["tenant"] == "acme"
        assert meta["existing"] == "val"
        assert row["tenant"] == "acme"

    def test_document_with_explicit_id_uses_it(self, db, mock_embedder):
        doc = Document(content="test", id="my-explicit-id")
        row = db._row_from_document(doc, "hash1")
        assert row["id"] == "my-explicit-id"

    def test_document_without_id_generates_deterministic_hash(self, db, mock_embedder):
        doc1 = Document(content="same content")
        doc2 = Document(content="same content")
        row1 = db._row_from_document(doc1, "hash1")
        row2 = db._row_from_document(doc2, "hash1")
        assert row1["id"] == row2["id"]


class TestApplyClientSideFilters:
    def test_none_filters_returns_all(self, db):
        rows = [{"id": "1"}, {"id": "2"}]
        assert db._apply_client_side_filters(rows, None) == rows

    def test_empty_dict_filters_returns_all(self, db):
        rows = [{"id": "1", "meta_data": "{}"}]
        result = db._apply_client_side_filters(rows, {})
        assert len(result) == 1

    def test_filter_expr_list_on_empty_rows(self, db):
        result = db._apply_client_side_filters([], [EQ("key", "val")])
        assert result == []


class TestIdExists:
    def test_id_exists_with_int_id_in_row(self, db):
        """id_exists casts to str for comparison."""
        db.index.scan.side_effect = [
            {"data": [{"id": 123}], "last_primary_key": 123},
            {"data": [], "last_primary_key": None},
        ]
        assert db.id_exists("123") is True

    def test_id_exists_with_no_match(self, db):
        assert db.id_exists("does-not-exist") is False


class TestDeleteByContentId:
    def test_delete_by_content_id_existing(self, db):
        db.index.scan.side_effect = [
            {
                "data": [{"id": "doc1", "content_id": "cid1"}],
                "last_primary_key": "doc1",
            },
            {"data": [], "last_primary_key": None},
        ]
        assert db.delete_by_content_id("cid1") is True
        db.index.delete.assert_called_once_with(primary_keys=["doc1"])

    def test_delete_by_content_id_nonexistent(self, db):
        assert db.delete_by_content_id("nope") is False


class TestSearchWithSimilarityThreshold:
    def test_similarity_threshold_passed_to_sdk(self, mock_embedder, mock_vector_client, mock_vector_index):
        db_obj = _make_db(mock_embedder, mock_vector_client, mock_vector_index, similarity_threshold=0.8)
        db_obj.search("query", limit=5)
        call_kwargs = mock_vector_index.similarity_search.call_args.kwargs
        assert call_kwargs["score_threshold"] == 0.8


class TestBuildFilterableRow:
    def test_filterable_row_merges_metadata(self, db):
        row = {"id": "1", "meta_data": '{"topic": "ai", "author": "alice"}', "content": "hi"}
        filterable = db._build_filterable_row(row)
        assert filterable["topic"] == "ai"
        assert filterable["author"] == "alice"
        assert isinstance(filterable["meta_data"], dict)
