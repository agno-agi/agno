import inspect
from typing import List
from unittest.mock import Mock, patch

import pytest

# Skip the whole module cleanly if the optional dep is absent.
pytest.importorskip("upstash_vector")

from agno.knowledge.document import Document  # noqa: E402
from agno.vectordb.upstashdb import UpstashVectorDb  # noqa: E402
from agno.vectordb.upstashdb.upstashdb import (  # noqa: E402
    _build_filter_str,
    _combine_filter_strs,
    _quote_value,
    _user_scope_filter_str,
)


@pytest.fixture
def mock_upstash_index():
    """A mocked Upstash Index so no live REST endpoint is needed."""
    with patch("upstash_vector.Index") as mock_index_class:
        mock_index = Mock()
        mock_index_class.return_value = mock_index

        mock_info = Mock()
        mock_info.vector_count = 0
        mock_info.dimension = 384
        mock_index.info.return_value = mock_info

        mock_index.upsert.return_value = "Success"
        mock_index.query.return_value = []

        mock_delete_result = Mock()
        mock_delete_result.deleted = 0
        mock_index.delete.return_value = mock_delete_result

        mock_index.fetch.return_value = []
        mock_index.reset.return_value = "Success"

        yield mock_index


@pytest.fixture
def upstash_db(mock_upstash_index):
    """An UpstashVectorDb using Upstash hosted embeddings (no embedder)."""
    db = UpstashVectorDb(url="https://test-url.upstash.io", token="test-token", embedder=None)
    db._index = mock_upstash_index
    return db


def _docs() -> List[Document]:
    return [
        Document(content="alpha doc", meta_data={"topic": "a"}, name="alpha", id="doc_1", content_id="c1"),
        Document(content="beta doc", meta_data={"topic": "b"}, name="beta", id="doc_2", content_id="c2"),
    ]


# --------------------------------------------------------------------------- #
# Filter-string builder (the pre-existing ``str(dict)`` bug fix)
# --------------------------------------------------------------------------- #


def test_build_filter_str_string_value_is_quoted():
    assert _build_filter_str({"user_id": "alice"}) == 'user_id = "alice"'


def test_build_filter_str_number_and_bool_are_unquoted():
    assert _build_filter_str({"n": 3}) == "n = 3"
    assert _build_filter_str({"score": 1.5}) == "score = 1.5"
    # bool must render lowercase true/false, NOT as 1/0 (it's an int subclass).
    assert _build_filter_str({"flag": True}) == "flag = true"
    assert _build_filter_str({"flag": False}) == "flag = false"


def test_build_filter_str_none_is_has_not_field():
    assert _build_filter_str({"user_id": None}) == "HAS NOT FIELD user_id"


def test_build_filter_str_and_combines_multiple_keys():
    out = _build_filter_str({"content_hash": "h1", "n": 2})
    assert out == 'content_hash = "h1" AND n = 2'


def test_build_filter_str_empty_is_no_filter():
    assert _build_filter_str(None) == ""
    assert _build_filter_str({}) == ""


def test_build_filter_str_is_not_python_dict_repr():
    """Regression: the adapter used to do ``str(filters)`` which is invalid
    Upstash syntax (e.g. ``{'user_id': 'alice'}``)."""
    out = _build_filter_str({"user_id": "alice"})
    assert "{" not in out and "}" not in out and ":" not in out


def test_quote_value_chooses_quote_char_to_avoid_escaping():
    """Upstash does not process backslash escapes inside a literal, so the value
    must be wrapped in whichever quote char it does NOT contain — escaping a '"'
    would break the owner's own match (self-starve), single-quoting matches it."""
    # No double quote -> double-quote it raw (common case).
    assert _quote_value("alice") == '"alice"'
    # Backslash passes through verbatim (NOT doubled).
    assert _quote_value("a\\b") == '"a\\b"'
    # A double quote in the value -> single-quote it (no escaping).
    assert _quote_value('wei"rd') == "'wei\"rd'"
    # A single quote in the value -> double-quote it.
    assert _quote_value("o'brien") == '"o\'brien"'
    # BOTH quote chars are unrepresentable -> None (callers fail closed).
    assert _quote_value("a'b\"c") is None


def test_build_filter_str_injection_is_quoted_not_escaped():
    """A crafted value with a '"' cannot break out of the literal: it is
    single-quoted whole, so the OR/-- injection becomes part of the matched
    value, never new filter grammar."""
    out = _build_filter_str({"user_id": 'a" OR 1=1 --'})
    assert out == "user_id = 'a\" OR 1=1 --'"


def test_build_filter_str_unrepresentable_value_fails_closed():
    """A value containing both quote chars can't be a literal, so the equality
    becomes an always-false predicate (matches nothing) rather than leaking."""
    out = _build_filter_str({"user_id": "a'b\"c"})
    assert out == "(HAS FIELD user_id AND HAS NOT FIELD user_id)"


def test_combine_filter_strs_skips_empty_and_parenthesises():
    assert _combine_filter_strs("", 'user_id = "a"') == 'user_id = "a"'
    assert _combine_filter_strs("a = 1", "") == "a = 1"
    assert _combine_filter_strs("a = 1", "b = 2") == "(a = 1) AND (b = 2)"
    assert _combine_filter_strs("", "") == ""


# --------------------------------------------------------------------------- #
# Owner-scope predicate
# --------------------------------------------------------------------------- #


def test_user_scope_filter_none_is_empty():
    """user_id=None => no scope (admin sees everything)."""
    assert _user_scope_filter_str(None) == ""
    assert _user_scope_filter_str("") == ""


def test_user_scope_filter_is_own_or_shared():
    assert _user_scope_filter_str("alice") == '(user_id = "alice" OR HAS NOT FIELD user_id)'


def test_user_scope_filter_quotes_value_with_double_quote():
    """A double quote in the id forces single-quoting (no escaping) so the owner
    still matches their own rows (escaping would self-starve the match)."""
    assert _user_scope_filter_str('a"x') == "(user_id = 'a\"x' OR HAS NOT FIELD user_id)"


def test_user_scope_filter_unrepresentable_id_sees_only_shared():
    """An id with both quote chars can't be a literal: the own-branch becomes
    always-false, so the caller sees only the shared bucket (fail closed)."""
    scope = _user_scope_filter_str("a'b\"c")
    assert scope == "((HAS FIELD user_id AND HAS NOT FIELD user_id) OR HAS NOT FIELD user_id)"


def test_scope_filters_never_use_is_null_operator():
    """``IS NULL`` is INVALID Upstash filter grammar — a scoped search built
    with it raises. The absent-field branch must stay ``HAS NOT FIELD``; guard
    so the invalid operator can't slip back in."""
    assert "IS NULL" not in _user_scope_filter_str("alice")
    assert "IS NULL" not in _build_filter_str({"user_id": None})


# --------------------------------------------------------------------------- #
# Signatures accept user_id (sync + async)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "method_name",
    ["insert", "async_insert", "upsert", "async_upsert", "search", "async_search", "delete_by_content_id"],
)
def test_signature_accepts_user_id_last(method_name):
    sig = inspect.signature(getattr(UpstashVectorDb, method_name))
    params = list(sig.parameters)
    assert "user_id" in params, f"{method_name} must accept user_id"
    assert sig.parameters["user_id"].default is None
    # user_id must be the LAST parameter per the isolation contract.
    assert params[-1] == "user_id", f"{method_name}: user_id must be the last parameter, got {params}"


def test_content_hash_exists_accepts_user_id():
    sig = inspect.signature(UpstashVectorDb.content_hash_exists)
    assert "user_id" in sig.parameters
    assert sig.parameters["user_id"].default is None


# --------------------------------------------------------------------------- #
# Write: stamp owner in metadata + fold owner into the vector id
# --------------------------------------------------------------------------- #


def test_upsert_stamps_user_id_in_metadata(upstash_db):
    upstash_db.upsert(content_hash="h1", documents=_docs(), user_id="alice")
    vectors = upstash_db.index.upsert.call_args[0][0]
    for v in vectors:
        assert v.metadata["user_id"] == "alice"


def test_upsert_shared_omits_user_id(upstash_db):
    upstash_db.upsert(content_hash="h1", documents=_docs(), user_id=None)
    vectors = upstash_db.index.upsert.call_args[0][0]
    for v in vectors:
        assert "user_id" not in v.metadata


def test_upsert_empty_user_id_is_shared(upstash_db):
    """normalize_user_id collapses "" to None => shared bucket."""
    upstash_db.upsert(content_hash="h1", documents=_docs(), user_id="")
    vectors = upstash_db.index.upsert.call_args[0][0]
    for v in vectors:
        assert "user_id" not in v.metadata


def test_caller_filter_cannot_override_owner(upstash_db):
    """A caller passing their own user_id in filters must not reassign tenancy."""
    upstash_db.upsert(content_hash="h1", documents=_docs(), filters={"user_id": "bob"}, user_id="alice")
    vectors = upstash_db.index.upsert.call_args[0][0]
    for v in vectors:
        assert v.metadata["user_id"] == "alice"


def test_vector_id_folds_in_user_id(upstash_db):
    # Scoped id differs from the legacy (shared) id and per-user ids differ.
    shared = upstash_db._vector_id("doc_1", None)
    alice = upstash_db._vector_id("doc_1", "alice")
    bob = upstash_db._vector_id("doc_1", "bob")
    assert shared == "doc_1"  # legacy id preserved for the shared bucket
    assert alice != shared
    assert bob != shared
    assert alice != bob


def test_two_users_same_content_get_distinct_vector_ids(upstash_db):
    """Cross-user clobber guard: same content_hash + same doc ids, different
    users => different vector ids => both coexist instead of overwriting."""
    upstash_db.upsert(content_hash="h1", documents=_docs(), user_id="alice")
    alice_ids = [v.id for v in upstash_db.index.upsert.call_args[0][0]]

    upstash_db.index.upsert.reset_mock()
    upstash_db.upsert(content_hash="h1", documents=_docs(), user_id="bob")
    bob_ids = [v.id for v in upstash_db.index.upsert.call_args[0][0]]

    assert set(alice_ids).isdisjoint(bob_ids)


def test_same_user_reupsert_reuses_ids(upstash_db):
    """Same-user re-upsert keeps the SAME vector ids so the write replaces in
    place (no duplicate chunks)."""
    upstash_db.upsert(content_hash="h1", documents=_docs(), user_id="alice")
    first = [v.id for v in upstash_db.index.upsert.call_args[0][0]]

    upstash_db.index.upsert.reset_mock()
    upstash_db.upsert(content_hash="h1", documents=_docs(), user_id="alice")
    second = [v.id for v in upstash_db.index.upsert.call_args[0][0]]

    assert first == second


# --------------------------------------------------------------------------- #
# Read: own-OR-shared filter string passed to the client
# --------------------------------------------------------------------------- #


def test_search_passes_own_or_shared_filter(upstash_db):
    upstash_db.search("q", user_id="alice")
    filter_str = upstash_db.index.query.call_args.kwargs["filter"]
    assert filter_str == '(user_id = "alice" OR HAS NOT FIELD user_id)'


def test_search_admin_has_no_scope(upstash_db):
    upstash_db.search("q", user_id=None)
    assert upstash_db.index.query.call_args.kwargs["filter"] == ""


def test_search_combines_caller_filter_with_scope(upstash_db):
    upstash_db.search("q", filters={"topic": "a"}, user_id="alice")
    filter_str = upstash_db.index.query.call_args.kwargs["filter"]
    assert filter_str == '(topic = "a") AND ((user_id = "alice" OR HAS NOT FIELD user_id))'


def test_search_filter_is_not_python_dict_repr(upstash_db):
    """Regression for the ``str(filters)`` bug: caller filters must be rendered
    as Upstash syntax, never a stringified dict."""
    upstash_db.search("q", filters={"topic": "a"}, user_id=None)
    filter_str = upstash_db.index.query.call_args.kwargs["filter"]
    assert filter_str == 'topic = "a"'
    assert "{" not in filter_str and "'topic':" not in filter_str


# --------------------------------------------------------------------------- #
# Delete: own-only scoping
# --------------------------------------------------------------------------- #


def test_delete_by_content_id_scoped_to_owner(upstash_db):
    upstash_db.delete_by_content_id("c1", user_id="alice")
    filter_str = upstash_db.index.delete.call_args.kwargs["filter"]
    assert filter_str == '(content_id = "c1") AND (user_id = "alice")'


def test_delete_by_content_id_admin_is_unscoped(upstash_db):
    upstash_db.delete_by_content_id("c1", user_id=None)
    filter_str = upstash_db.index.delete.call_args.kwargs["filter"]
    assert filter_str == 'content_id = "c1"'


def test_delete_by_content_hash_scoped_to_owner(upstash_db):
    upstash_db._delete_by_content_hash("h1", user_id="alice")
    filter_str = upstash_db.index.delete.call_args.kwargs["filter"]
    assert filter_str == '(content_hash = "h1") AND (user_id = "alice")'


# --------------------------------------------------------------------------- #
# content_hash_exists scoping
# --------------------------------------------------------------------------- #


def test_content_hash_exists_scoped_to_owner(upstash_db):
    upstash_db.content_hash_exists("h1", user_id="alice")
    filter_str = upstash_db.index.query.call_args.kwargs["filter"]
    assert filter_str == '(content_hash = "h1") AND (user_id = "alice")'


def test_content_hash_exists_unscoped(upstash_db):
    upstash_db.content_hash_exists("h1", user_id=None)
    filter_str = upstash_db.index.query.call_args.kwargs["filter"]
    assert filter_str == 'content_hash = "h1"'


# --------------------------------------------------------------------------- #
# update_metadata must not let a caller overwrite the owner field
# --------------------------------------------------------------------------- #


def test_update_metadata_protects_owner(upstash_db):
    existing = Mock()
    existing.id = "vec_1"
    existing.metadata = {"user_id": "alice", "content_id": "c1"}
    upstash_db.index.query.return_value = [existing]

    upstash_db.update_metadata("c1", {"user_id": "bob", "topic": "x"})

    update_kwargs = upstash_db.index.update.call_args.kwargs
    # Owner stays alice; caller-supplied user_id=bob is ignored.
    assert update_kwargs["metadata"]["user_id"] == "alice"
    assert update_kwargs["metadata"]["topic"] == "x"
