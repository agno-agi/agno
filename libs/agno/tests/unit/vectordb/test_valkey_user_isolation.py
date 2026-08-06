"""Valkey per-user RAG isolation contract.

The ValkeyDB adapter stores a chunk's owner in a top-level ``user_id`` TAG
field. valkey-search has no ``ismissing()``, so shared chunks store the
``__shared__`` sentinel and a scoped read matches ``{owner|__shared__}``;
unscoped (admin) reads apply no scope at all. The deterministic id folds the
owner in so two users uploading identical content never collide.

No server is contacted: ``glide_ft`` is replaced with an in-memory fake that
holds the hashes written by ``client.hset`` and evaluates the FT.SEARCH query
the adapter actually builds (TAG clauses with valkey escaping, ``@content``
text terms, and the ``=>[KNN n @embedding $query_vector]`` suffix). So every
test here asserts twice over: on the query string the adapter emits, and on
which owners' chunks that query actually returns.

The fake models tag alternation, escaping and the KNN pre-filter faithfully.
It deliberately does NOT model server-side tag normalisation (whitespace
trimming, case folding on non-``case_sensitive`` fields) — those are
unverified without a live valkey-search, and a fake asserting them would
manufacture a result rather than test one.
"""

import re
import struct
from typing import Any, Dict, List, Optional

import pytest

from agno.knowledge.document import Document
from agno.utils.string import hash_string_sha256
from agno.vectordb.search import SearchType
from agno.vectordb.valkey.valkeydb import RESERVED_HASH_FIELDS, ValkeyDB, _escape_tag_value

USER_ID_FIELD = ValkeyDB.USER_ID_FIELD
SHARED = ValkeyDB.SHARED_OWNER_TAG
MATCH_ALL = ValkeyDB.MATCH_ALL_TAG

_TAG_CLAUSE = re.compile(r"^(-?)@([A-Za-z_][A-Za-z0-9_]*):\{(.*)\}$", re.DOTALL)
_TEXT_CLAUSE = re.compile(r"^@content:(.+)$", re.DOTALL)
_KNN_SUFFIX = re.compile(r"=>\s*\[KNN\s+(\d+)\s+@embedding\s+\$query_vector\]\s*$")
_TOKEN = re.compile(r"[A-Za-z0-9_]+")


class _DeterministicEmbedder:
    """A tiny embedder that needs no network or API key."""

    dimensions = 8
    enable_batch = False

    def get_embedding(self, text):
        vector = [0.0] * self.dimensions
        vector[abs(hash(text)) % self.dimensions] = 1.0
        return vector

    def get_embedding_and_usage(self, text):
        return self.get_embedding(text), {"total_tokens": 1}

    async def async_get_embedding(self, text):
        return self.get_embedding(text)

    async def async_get_embedding_and_usage(self, text):
        return self.get_embedding(text), {"total_tokens": 1}

    def embed(self, *args, **kwargs):
        pass

    async def async_embed(self, *args, **kwargs):
        pass


def _embedded(name: str, content: str, content_id: str = None, doc_id: str = None) -> Document:
    """A Document carrying a precomputed embedding."""
    doc = Document(name=name, content=content)
    if doc_id is not None:
        doc.id = doc_id
    doc.embedding = _DeterministicEmbedder().get_embedding(content)
    if content_id is not None:
        doc.content_id = content_id
    return doc


# -- The fake valkey-search server --


def _tag_alternatives(tag_body: str) -> List[str]:
    """Split a ``{a|b}`` TAG body on its UNESCAPED ``|`` and unescape each
    alternative, exactly as valkey-search reads a TAG query."""
    alternatives: List[str] = []
    current: List[str] = []
    i = 0
    while i < len(tag_body):
        char = tag_body[i]
        if char == "\\" and i + 1 < len(tag_body):
            current.append(tag_body[i + 1])
            i += 2
            continue
        if char == "|":
            alternatives.append("".join(current))
            current = []
            i += 1
            continue
        current.append(char)
        i += 1
    alternatives.append("".join(current))
    return alternatives


def _split_clauses(expression: str) -> List[str]:
    """Split an FT.SEARCH expression into whitespace-separated clauses,
    keeping parenthesised groups and braced TAG bodies intact."""
    clauses: List[str] = []
    i = 0
    while i < len(expression):
        if expression[i].isspace():
            i += 1
            continue
        if expression[i] == "(":
            depth, j = 0, i
            while j < len(expression):
                if expression[j] == "(":
                    depth += 1
                elif expression[j] == ")":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            clauses.append(expression[i + 1 : j])
            i = j + 1
            continue
        depth, j = 0, i
        while j < len(expression):
            char = expression[j]
            if char == "\\":
                j += 2
                continue
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
            elif char.isspace() and depth == 0:
                break
            j += 1
        clauses.append(expression[i:j])
        i = j
    return clauses


class _FakeValkey:
    """An in-memory Valkey holding HASH keys, plus the FT.SEARCH evaluator.

    Only the surface ValkeyDB uses is implemented: ``hset``, ``delete``,
    ``scan`` and the ``glide_ft`` module functions.
    """

    def __init__(self, separator: str = "\x1f"):
        self.hashes: Dict[str, Dict[str, Any]] = {}
        self.queries: List[str] = []
        self.separator = separator

    # -- client surface --

    def hset(self, key, field_value_map):
        self.hashes.setdefault(key, {}).update(dict(field_value_map))
        return len(field_value_map)

    def delete(self, keys):
        removed = 0
        for key in keys:
            if self.hashes.pop(key, None) is not None:
                removed += 1
        return removed

    def scan(self, cursor=b"0", match="*", count=100):
        prefix = match[:-1] if match.endswith("*") else match
        prefix = prefix.replace("\\", "")
        return ("0", [k for k in self.hashes if k.startswith(prefix)])

    # -- query evaluation --

    def _field_tags(self, fields: Dict[str, Any], name: str) -> List[str]:
        value = fields.get(name)
        if value is None:
            return []
        return str(value).split(self.separator)

    def _matches_clause(self, fields: Dict[str, Any], clause: str) -> bool:
        if clause == "*":
            return True
        tag = _TAG_CLAUSE.match(clause)
        if tag:
            negated, field_name, body = tag.group(1), tag.group(2), tag.group(3)
            wanted = set(_tag_alternatives(body))
            hit = any(stored in wanted for stored in self._field_tags(fields, field_name))
            return not hit if negated else hit
        text = _TEXT_CLAUSE.match(clause)
        terms = text.group(1) if text else clause
        # A bare term matches the only TEXT field in the schema, "content".
        content_tokens = set(_TOKEN.findall(str(fields.get("content", "")).lower()))
        return all(term.lower() in content_tokens for term in _TOKEN.findall(terms))

    def _matches(self, fields: Dict[str, Any], expression: str) -> bool:
        clauses = _split_clauses(expression)
        if len(clauses) == 1 and clauses[0] == expression.strip():
            return self._matches_clause(fields, clauses[0])
        return all(self._matches(fields, clause) for clause in clauses)

    def search(self, query: str, options) -> list:
        self.queries.append(query)
        knn = _KNN_SUFFIX.search(query)
        expression = query[: knn.start()] if knn else query
        expression = expression.strip()
        if expression.startswith("(") and expression.endswith(")"):
            expression = expression[1:-1]

        matched = [(key, fields) for key, fields in self.hashes.items() if self._matches(fields, expression)]

        if knn:
            query_vector = options.params["query_vector"]
            matched.sort(key=lambda item: _cosine_distance(query_vector, item[1].get("embedding", b"")))
            matched = matched[: int(knn.group(1))]

        offset = options.limit.offset if options.limit else 0
        count = options.limit.count if options.limit else len(matched)
        page = matched[offset : offset + count]

        wanted_fields = [rf.field_identifier for rf in options.return_fields] if options.return_fields else None
        result_map = {}
        for key, fields in page:
            if wanted_fields is None:
                result_map[key] = dict(fields)
            else:
                result_map[key] = {name: fields[name] for name in wanted_fields if name in fields}
        return [len(matched), result_map]


def _cosine_distance(left: bytes, right: bytes) -> float:
    """Cosine distance between two little-endian float32 buffers."""
    if not right:
        return 2.0
    a = struct.unpack(f"<{len(left) // 4}f", left)
    b = struct.unpack(f"<{len(right) // 4}f", right)
    dot = sum(x * y for x, y in zip(a, b))
    norm = (sum(x * x for x in a) ** 0.5) * (sum(y * y for y in b) ** 0.5)
    return 1.0 - (dot / norm if norm else 0.0)


class _FakeFt:
    """Stand-in for the ``glide_sync.ft`` module. Like the real one it is
    stateless about data and dispatches to the client it is handed."""

    def __init__(self):
        self.created_schema: Optional[list] = None
        self.indexes: List[str] = []

    def search(self, client, index_name, query, options=None):
        return client.search(query, options)

    def create(self, client, index_name, schema, options=None):
        self.created_schema = schema
        self.indexes.append(index_name)

    def list(self, client):
        return list(self.indexes)

    def dropindex(self, client, index_name):
        self.indexes = [name for name in self.indexes if name != index_name]

    def info(self, client, index_name):
        attributes = [[b"identifier", field.name.encode(), b"type", b"TAG"] for field in (self.created_schema or [])]
        return {b"attributes": attributes}


@pytest.fixture
def valkey_db(monkeypatch):
    """A ValkeyDB whose glide client and ``glide_ft`` module are in-memory fakes."""
    from agno.vectordb.valkey import valkeydb as valkeydb_mod

    store = _FakeValkey()
    monkeypatch.setattr(valkeydb_mod, "glide_ft", _FakeFt())

    db = valkeydb_mod.ValkeyDB(
        index_name="iso_test",
        glide_client=store,
        embedder=_DeterministicEmbedder(),
        search_type=SearchType.vector,
    )
    db._fake = store
    return db


def _stored(db) -> Dict[str, Dict[str, Any]]:
    """Every hash currently held by the fake, keyed by valkey key."""
    return db._fake.hashes


def _owners(db) -> List[str]:
    """The owner tag on every stored hash."""
    return [fields[USER_ID_FIELD] for fields in _stored(db).values()]


def _last_query(db) -> str:
    """The most recent FT.SEARCH query string the adapter emitted."""
    assert db._fake.queries, "no FT.SEARCH query was issued"
    return db._fake.queries[-1]


def _seed_three_owners(db) -> None:
    """One chunk for alice, one for bob, one shared — the isolation corpus."""
    db.insert(content_hash="ha", documents=[_embedded("alice-doc", "quarterly secret alpha", "cid-a")], user_id="alice")
    db.insert(content_hash="hb", documents=[_embedded("bob-doc", "quarterly secret bravo", "cid-b")], user_id="bob")
    db.insert(content_hash="hs", documents=[_embedded("shared-doc", "quarterly secret shared", "cid-s")])


class TestSchemaDeclaresOwner:
    """Isolation is enforced server-side, so the owner field (and the
    ``linked_to`` filter Knowledge injects) must be in the index schema —
    an unindexed TAG silently matches nothing and every scoped read empties."""

    def test_owner_is_an_atomic_case_sensitive_tag(self, valkey_db):
        owner_field = next(f for f in valkey_db._build_schema() if f.name == USER_ID_FIELD)
        # 0x1f never appears in a real owner id, so the value stays ONE tag.
        assert owner_field.separator == ValkeyDB.USER_ID_SEPARATOR
        assert owner_field.case_sensitive is True

    def test_linked_to_is_indexed(self, valkey_db):
        # isolate_vector_search injects a linked_to filter; unindexed it is dropped.
        assert "linked_to" in {f.name for f in valkey_db._build_schema()}


class TestWriteStampsOwner:
    """``user_id`` is a top-level TAG on every hash. Shared chunks store the
    ``__shared__`` sentinel so the owner-OR-shared scope can match them."""

    def test_isolation_constants(self):
        # Storage-compatibility markers: changing any orphans the scope on
        # every previously persisted row.
        assert ValkeyDB.USER_ID_FIELD == "user_id"
        assert ValkeyDB.SHARED_OWNER_TAG == "__shared__"
        assert ValkeyDB.MATCH_ALL_TAG == "__match_all__"

    def test_explicit_user_id_persisted(self, valkey_db):
        valkey_db.insert(
            content_hash="h1", documents=[_embedded("alice-salary", "Alice secret 180k.")], user_id="alice"
        )
        assert _owners(valkey_db) == ["alice"]

    def test_none_user_id_stamps_shared_sentinel(self, valkey_db):
        valkey_db.insert(content_hash="h1", documents=[_embedded("holidays", "Office closed Jan 1.")], user_id=None)
        assert _owners(valkey_db) == [SHARED]

    def test_user_id_omitted_defaults_to_shared(self, valkey_db):
        valkey_db.insert(content_hash="h1", documents=[_embedded("holidays", "Office closed Jan 1.")])
        assert _owners(valkey_db) == [SHARED]

    def test_upsert_stamps_owner(self, valkey_db):
        valkey_db.upsert(content_hash="h1", documents=[_embedded("a", "x")], user_id="alice")
        assert _owners(valkey_db) == ["alice"]

    def test_caller_meta_data_cannot_spoof_owner(self, valkey_db):
        """``user_id`` / ``id`` in caller meta_data must not override the
        adapter-stamped owner or the owner-folded key."""
        doc = Document(name="d", content="c", meta_data={"user_id": "attacker", "id": "evil"})
        doc.embedding = _DeterministicEmbedder().get_embedding("c")
        valkey_db.insert(content_hash="h1", documents=[doc], user_id="alice")
        stored = list(_stored(valkey_db).values())[0]
        assert stored[USER_ID_FIELD] == "alice"
        assert stored["id"] != "evil"

    async def test_async_insert_stamps_owner(self, valkey_db):
        await valkey_db.async_insert(content_hash="h1", documents=[_embedded("a", "x")], user_id="alice")
        assert _owners(valkey_db) == ["alice"]

    async def test_async_insert_none_is_shared(self, valkey_db):
        await valkey_db.async_insert(content_hash="h1", documents=[_embedded("a", "x")], user_id=None)
        assert _owners(valkey_db) == [SHARED]

    async def test_async_upsert_stamps_owner(self, valkey_db):
        await valkey_db.async_upsert(content_hash="h1", documents=[_embedded("a", "x")], user_id="alice")
        assert _owners(valkey_db) == ["alice"]


class TestIdFolding:
    """The deterministic key folds the owner in, so two users uploading
    byte-identical content get DISTINCT keys and cannot clobber each other.
    The shared bucket keeps the legacy (unfolded) id."""

    _SAME = "The quarterly figure is identical for both owners."

    def test_scoped_key_is_owner_folded_hash(self, valkey_db):
        valkey_db.insert(content_hash="h", documents=[_embedded("a", "x", doc_id="doc-1")], user_id="alice")
        expected = hash_string_sha256(f"{hash_string_sha256('doc-1')}_alice")
        assert list(_stored(valkey_db).values())[0]["id"] == expected

    def test_shared_keeps_legacy_id(self, valkey_db):
        valkey_db.insert(content_hash="h", documents=[_embedded("a", "x", doc_id="doc-1")], user_id=None)
        assert list(_stored(valkey_db).values())[0]["id"] == "doc-1"

    def test_two_owners_same_content_get_distinct_keys(self, valkey_db):
        assert valkey_db._scoped_doc_id("doc-1", "alice") != valkey_db._scoped_doc_id("doc-1", "bob")

    def test_owner_boundary_cannot_be_shifted(self, valkey_db):
        """The base id is caller-controlled, so it is collapsed to a fixed-length
        digest before the owner is folded in. Without that, ("doc_1", "alice") and
        ("doc", "1_alice") both join to "doc_1_alice" and land on ONE key — and
        every agno chunk id ends in "_<n>", so a caller passing user_id="1_alice"
        overwrites alice's chunk 1."""
        assert valkey_db._scoped_doc_id("doc_1", "alice") != valkey_db._scoped_doc_id("doc", "1_alice")

    def test_shifted_boundary_write_does_not_overwrite_the_owner(self, valkey_db):
        """The consequence on the write path: both chunks survive under their own
        keys instead of the crafted owner's write landing on alice's key."""
        valkey_db.insert(content_hash="h", documents=[_embedded("alice-doc", "x", doc_id="doc_1")], user_id="alice")
        valkey_db.insert(content_hash="h", documents=[_embedded("crafted", "x", doc_id="doc")], user_id="1_alice")
        assert len(_stored(valkey_db)) == 2
        assert sorted(_owners(valkey_db)) == ["1_alice", "alice"]

    def test_identical_content_does_not_overwrite_the_other_owner(self, valkey_db):
        """The load-bearing consequence: bob writing byte-identical content
        must leave alice's row alive, not overwrite it at the same key."""
        valkey_db.insert(content_hash="h", documents=[_embedded("a", self._SAME)], user_id="alice")
        valkey_db.insert(content_hash="h", documents=[_embedded("a", self._SAME)], user_id="bob")
        assert len(_stored(valkey_db)) == 2
        assert sorted(_owners(valkey_db)) == ["alice", "bob"]


class TestReadScope:
    """A scoped search filters to the caller's own chunks OR the shared bucket
    and never another user's; admin (``None``) applies no scope. Both the query
    string and the rows it actually returns are asserted."""

    def test_user_scope_expression_builder(self, valkey_db):
        assert valkey_db._user_scope_expression("alice") == "@user_id:{alice|__shared__}"
        assert valkey_db._user_scope_expression(None) == ""

    def test_scoped_vector_search_builds_own_or_shared(self, valkey_db):
        valkey_db.search(query="secret salary", limit=10, user_id="alice")
        assert _last_query(valkey_db) == "(@user_id:{alice|__shared__})=>[KNN 10 @embedding $query_vector]"

    def test_admin_vector_search_has_no_scope(self, valkey_db):
        valkey_db.search(query="secret salary", limit=10, user_id=None)
        # "*" pre-filter == no owner scope; admin sees everything.
        assert _last_query(valkey_db) == "*=>[KNN 10 @embedding $query_vector]"

    def test_scoped_keyword_search_builds_own_or_shared(self, valkey_db):
        valkey_db.search_type = SearchType.keyword
        valkey_db.search(query="secret", limit=10, user_id="alice")
        assert _last_query(valkey_db) == "(@content:secret) @user_id:{alice|__shared__}"

    def test_admin_keyword_search_has_no_scope(self, valkey_db):
        valkey_db.search_type = SearchType.keyword
        valkey_db.search(query="secret", limit=10, user_id=None)
        assert _last_query(valkey_db) == "(@content:secret)"

    def test_empty_keyword_query_still_carries_the_scope(self, valkey_db):
        """A query with no alphanumeric terms must fall back to the scope
        clause, never to the unscoped match-all."""
        valkey_db.search_type = SearchType.keyword
        valkey_db.search(query="!!! ???", limit=10, user_id="alice")
        assert _last_query(valkey_db) == "@user_id:{alice|__shared__}"

    def test_admin_empty_keyword_query_matches_all(self, valkey_db):
        valkey_db.search_type = SearchType.keyword
        valkey_db.search(query="!!! ???", limit=10, user_id=None)
        assert _last_query(valkey_db) == f"-@user_id:{{{MATCH_ALL}}}"

    def test_metadata_filter_never_displaces_the_scope(self, valkey_db):
        valkey_db.search(query="secret", limit=5, filters={"category": "hr"}, user_id="alice")
        assert _last_query(valkey_db) == (
            "(@category:{hr} @user_id:{alice|__shared__})=>[KNN 5 @embedding $query_vector]"
        )

    def test_scoped_vector_search_returns_own_and_shared_only(self, valkey_db):
        _seed_three_owners(valkey_db)
        names = {doc.name for doc in valkey_db.vector_search("quarterly secret", limit=10, user_id="alice")}
        assert names == {"alice-doc", "shared-doc"}
        assert "bob-doc" not in names

    def test_scoped_keyword_search_returns_own_and_shared_only(self, valkey_db):
        _seed_three_owners(valkey_db)
        names = {doc.name for doc in valkey_db.keyword_search("quarterly", limit=10, user_id="alice")}
        assert names == {"alice-doc", "shared-doc"}

    def test_admin_search_sees_every_owner(self, valkey_db):
        _seed_three_owners(valkey_db)
        names = {doc.name for doc in valkey_db.vector_search("quarterly secret", limit=10, user_id=None)}
        assert names == {"alice-doc", "bob-doc", "shared-doc"}

    def test_owner_with_no_chunks_sees_only_shared(self, valkey_db):
        _seed_three_owners(valkey_db)
        names = {doc.name for doc in valkey_db.vector_search("quarterly secret", limit=10, user_id="carol")}
        assert names == {"shared-doc"}

    async def test_async_search_scopes_identically(self, valkey_db):
        _seed_three_owners(valkey_db)
        names = {doc.name for doc in await valkey_db.async_search("quarterly secret", limit=10, user_id="alice")}
        assert _last_query(valkey_db) == "(@user_id:{alice|__shared__})=>[KNN 10 @embedding $query_vector]"
        assert names == {"alice-doc", "shared-doc"}


class TestContentHashExists:
    """``content_hash_exists`` is STRICT for a real owner: another owner's (or
    the shared bucket's) identical upload is not the caller's duplicate, so it
    must not suppress the caller's own ingest. It is the guard half of the upsert
    dedupe pair, so ``None`` means the shared bucket alone — the same bucket the
    dedupe delete clears — and never every owner."""

    def test_scoped_check_ands_the_owner(self, valkey_db):
        valkey_db.content_hash_exists("h1", user_id="alice")
        assert _last_query(valkey_db) == "@content_hash:{h1} @user_id:{alice}"

    def test_none_check_scopes_to_the_shared_bucket(self, valkey_db):
        valkey_db.content_hash_exists("h1", user_id=None)
        assert _last_query(valkey_db) == f"@content_hash:{{h1}} @user_id:{{{SHARED}}}"

    def test_check_matches_the_dedupe_delete_bucket(self, valkey_db):
        """The two halves are one guard: the check reuses ``_dedupe_query``, so
        they can never drift onto different buckets."""
        for owner in ("alice", None):
            valkey_db.content_hash_exists("h1", user_id=owner)
            assert _last_query(valkey_db) == valkey_db._dedupe_query("h1", owner)

    def test_owner_sees_own_hash(self, valkey_db):
        valkey_db.insert(content_hash="h1", documents=[_embedded("a", "x")], user_id="alice")
        assert valkey_db.content_hash_exists("h1", user_id="alice") is True

    def test_owner_does_not_see_another_owners_hash(self, valkey_db):
        valkey_db.insert(content_hash="h1", documents=[_embedded("a", "x")], user_id="bob")
        # Bob's identical upload must NOT be judged alice's duplicate.
        assert valkey_db.content_hash_exists("h1", user_id="alice") is False

    def test_owner_does_not_see_the_shared_hash(self, valkey_db):
        valkey_db.insert(content_hash="h1", documents=[_embedded("a", "x")], user_id=None)
        # Strict, unlike a read scope: the shared bucket is not alice's duplicate.
        assert valkey_db.content_hash_exists("h1", user_id="alice") is False

    def test_none_check_does_not_see_a_privately_owned_hash(self, valkey_db):
        """Alice privately holds this content. If ``None`` matched her chunk, a
        shared publish of the same bytes would be judged a duplicate and silently
        skipped, and the shared bucket would never receive it."""
        valkey_db.insert(content_hash="h1", documents=[_embedded("a", "x")], user_id="alice")
        assert valkey_db.content_hash_exists("h1", user_id=None) is False

    def test_none_check_sees_the_shared_hash(self, valkey_db):
        valkey_db.insert(content_hash="h1", documents=[_embedded("a", "x")], user_id=None)
        assert valkey_db.content_hash_exists("h1", user_id=None) is True


class TestScopedDedupe:
    """The upsert dedupe-delete is scoped to the writing owner's bucket: a
    scoped upsert dedupes only that owner's chunks, a shared upsert dedupes
    only the shared bucket — one can never evict the other's identical content.
    """

    def test_dedupe_query_scoped_to_owner(self, valkey_db):
        assert valkey_db._dedupe_query("hc", "alice") == "@content_hash:{hc} @user_id:{alice}"

    def test_dedupe_query_none_scopes_to_shared(self, valkey_db):
        assert valkey_db._dedupe_query("hc", None) == f"@content_hash:{{hc}} @user_id:{{{SHARED}}}"

    def test_scoped_upsert_does_not_evict_other_owners(self, valkey_db):
        valkey_db.insert(content_hash="hc", documents=[_embedded("bob-doc", "same")], user_id="bob")
        valkey_db.insert(content_hash="hc", documents=[_embedded("shared-doc", "same")], user_id=None)
        valkey_db.upsert(content_hash="hc", documents=[_embedded("alice-doc", "same")], user_id="alice")
        assert sorted(_owners(valkey_db)) == ["__shared__", "alice", "bob"]

    def test_shared_upsert_does_not_evict_owned_chunks(self, valkey_db):
        valkey_db.insert(content_hash="hc", documents=[_embedded("alice-doc", "same")], user_id="alice")
        valkey_db.upsert(content_hash="hc", documents=[_embedded("shared-doc", "same")], user_id=None)
        assert sorted(_owners(valkey_db)) == ["__shared__", "alice"]

    def test_scoped_upsert_replaces_only_the_callers_prior_chunks(self, valkey_db):
        valkey_db.insert(content_hash="hc", documents=[_embedded("old", "same", doc_id="d1")], user_id="alice")
        valkey_db.insert(content_hash="hc", documents=[_embedded("old", "same", doc_id="d2")], user_id="alice")
        valkey_db.upsert(content_hash="hc", documents=[_embedded("new", "same", doc_id="d3")], user_id="alice")
        assert [fields["name"] for fields in _stored(valkey_db).values()] == ["new"]


class TestScopedDelete:
    """``delete_by_content_id(content_id, user_id=...)`` scopes the delete to
    the caller's chunks. A scoped delete matches the owner EXACTLY (it must
    NOT reach the shared bucket); ``None`` deletes across all owners."""

    def test_scoped_delete_restricts_to_owner(self, valkey_db):
        valkey_db.delete_by_content_id("cid1", user_id="alice")
        # Owner-only: no "|__shared__" alternation here, unlike a read scope.
        assert _last_query(valkey_db) == "@content_id:{cid1} @user_id:{alice}"

    def test_unscoped_delete_spans_all_owners(self, valkey_db):
        valkey_db.delete_by_content_id("cid1", user_id=None)
        assert _last_query(valkey_db) == "@content_id:{cid1}"

    def test_scoped_delete_leaves_other_owners_alive(self, valkey_db):
        for owner in ("alice", "bob", None):
            valkey_db.insert(
                content_hash=f"h-{owner}",
                documents=[_embedded(str(owner), f"body {owner}", content_id="cid1")],
                user_id=owner,
            )
        assert valkey_db.delete_by_content_id("cid1", user_id="alice") is True
        assert sorted(_owners(valkey_db)) == ["__shared__", "bob"]

    def test_scoped_delete_does_not_reach_the_shared_bucket(self, valkey_db):
        valkey_db.insert(content_hash="hs", documents=[_embedded("s", "body", content_id="cid1")], user_id=None)
        # Nothing of alice's matches, so the shared chunk must survive untouched.
        assert valkey_db.delete_by_content_id("cid1", user_id="alice") is False
        assert _owners(valkey_db) == [SHARED]

    def test_unscoped_delete_removes_every_owner(self, valkey_db):
        for owner in ("alice", "bob", None):
            valkey_db.insert(
                content_hash=f"h-{owner}",
                documents=[_embedded(str(owner), f"body {owner}", content_id="cid1")],
                user_id=owner,
            )
        assert valkey_db.delete_by_content_id("cid1", user_id=None) is True
        assert _stored(valkey_db) == {}

    def test_unscoped_delete_pages_past_the_first_page(self, valkey_db):
        """FT.SEARCH returns one 1000-match page. An unscoped delete that read a
        single page left every chunk past it behind AND still returned True, so an
        admin was told the delete succeeded while the survivors kept their owner
        tag and stayed visible to every scoped reader."""
        docs = [_embedded(f"a{i}", f"body {i}", content_id="cid1", doc_id=f"a{i}") for i in range(1500)]
        valkey_db.insert(content_hash="ha", documents=docs, user_id="alice")

        assert valkey_db.delete_by_content_id("cid1", user_id=None) is True
        assert _stored(valkey_db) == {}
        # And nothing survives for a scoped reader either.
        assert valkey_db.vector_search("body", limit=10, user_id="alice") == []

    def test_unscoped_delete_by_id_and_name_page_too(self, valkey_db):
        """``delete_by_id`` / ``delete_by_name`` share the same tag-filter path,
        so they page to exhaustion as well."""
        docs = [_embedded("same-name", f"body {i}", content_id="cid1", doc_id="same-id") for i in range(1500)]
        # One key per doc: the fake keys on the hash "id" field, so vary it here.
        for i, doc in enumerate(docs):
            doc.id = f"same-id-{i}"
        valkey_db.insert(content_hash="ha", documents=docs, user_id=None)
        assert valkey_db.delete_by_name("same-name") is True
        assert _stored(valkey_db) == {}

        valkey_db.insert(content_hash="ha", documents=docs, user_id=None)
        assert len(_stored(valkey_db)) == 1500
        # Every chunk carries the same "id" tag value here, one page cannot clear it.
        for key in list(_stored(valkey_db)):
            _stored(valkey_db)[key]["id"] = "shared-id"
        assert valkey_db.delete_by_id("shared-id") is True
        assert _stored(valkey_db) == {}

    def test_paged_scoped_delete_keeps_the_owner_clause_on_every_page(self, valkey_db):
        """``_delete_by_query`` pages at 1000 matches. The owner clause must ride
        every page, or the second page widens the delete to all owners."""
        page_size = 1000
        alice_docs = [_embedded(f"a{i}", f"body {i}", content_id="cid1", doc_id=f"a{i}") for i in range(page_size + 1)]
        valkey_db.insert(content_hash="ha", documents=alice_docs, user_id="alice")
        valkey_db.insert(content_hash="hb", documents=[_embedded("bob", "body bob", content_id="cid1")], user_id="bob")

        assert valkey_db.delete_by_content_id("cid1", user_id="alice") is True
        # More than one page was fetched, and bob survived every one of them.
        assert len([q for q in valkey_db._fake.queries if "@content_id:{cid1}" in q]) > 1
        assert _owners(valkey_db) == ["bob"]


class TestUpdateMetadataReservedFields:
    """``update_metadata`` writes caller-supplied fields straight onto the
    hash, so it must strip the fields the adapter owns. An ``id`` would
    redirect the owner-folded key, an ``embedding`` would corrupt the vector,
    and a ``user_id`` would hand the chunk to another tenant outright."""

    def _seed_alice(self, db):
        db.insert(
            content_hash="h1", documents=[_embedded("alice-doc", "secret alpha", content_id="cid1")], user_id="alice"
        )

    def test_reserved_fields_are_stripped(self, valkey_db):
        self._seed_alice(valkey_db)
        original = dict(list(_stored(valkey_db).values())[0])
        valkey_db.update_metadata(
            "cid1",
            {"user_id": "bob", "id": "evil", "embedding": "junk", "content": "rewritten", "status": "ok"},
        )
        stored = list(_stored(valkey_db).values())[0]
        for field in RESERVED_HASH_FIELDS:
            assert stored.get(field) == original.get(field), f"reserved field '{field}' was overwritten"
        # Non-reserved metadata still lands.
        assert stored["status"] == "ok"

    def test_owner_cannot_be_reassigned(self, valkey_db):
        self._seed_alice(valkey_db)
        valkey_db.update_metadata("cid1", {"user_id": "bob"})
        assert _owners(valkey_db) == ["alice"]

    def test_chunk_stays_invisible_to_the_other_owner_after_update(self, valkey_db):
        """The consequence of the strip: a metadata update cannot move a chunk
        into another tenant's read scope."""
        self._seed_alice(valkey_db)
        valkey_db.update_metadata("cid1", {"user_id": "bob", "status": "ok"})
        assert valkey_db.vector_search("secret alpha", limit=10, user_id="bob") == []
        assert [d.name for d in valkey_db.vector_search("secret alpha", limit=10, user_id="alice")] == ["alice-doc"]

    def test_shared_sentinel_cannot_be_forged(self, valkey_db):
        """Stamping ``__shared__`` onto an owned chunk would publish it to
        every tenant at once — the worst case of an unstripped ``user_id``."""
        self._seed_alice(valkey_db)
        valkey_db.update_metadata("cid1", {"user_id": SHARED})
        assert valkey_db.vector_search("secret alpha", limit=10, user_id="carol") == []

    def test_key_is_not_redirected(self, valkey_db):
        self._seed_alice(valkey_db)
        keys_before = set(_stored(valkey_db))
        valkey_db.update_metadata("cid1", {"id": "evil"})
        assert set(_stored(valkey_db)) == keys_before


class TestUserIdValidation:
    """Reserved / structurally unsafe owner values are rejected up front so a
    caller can neither impersonate the shared bucket nor break the TAG scope."""

    @pytest.mark.parametrize(
        "bad",
        [
            "",  # an owner tag no scope clause can match
            ValkeyDB.SHARED_OWNER_TAG,  # shared-bucket impersonation
            ValkeyDB.MATCH_ALL_TAG,  # breaks the match-all query
            "alice*",  # wildcard matches other owners
            "alice?",  # wildcard matches other owners
            "alice{1}",  # brace can never be matched by a scope clause
            "a\x1fb",  # separator indexes one value as several tags
        ],
    )
    def test_rejects_unsafe_user_id(self, valkey_db, bad):
        with pytest.raises(ValueError):
            valkey_db._validate_user_id(bad)
        # And the rejection is enforced on the write path, not just the helper.
        with pytest.raises(ValueError):
            valkey_db.insert(content_hash="h", documents=[_embedded("a", "x")], user_id=bad)
        assert _stored(valkey_db) == {}

    def test_none_is_allowed(self, valkey_db):
        valkey_db._validate_user_id(None)

    def test_upsert_rejects_unsafe_user_id(self, valkey_db):
        with pytest.raises(ValueError):
            valkey_db.upsert(content_hash="h", documents=[_embedded("a", "x")], user_id=SHARED)
        assert _stored(valkey_db) == {}

    def test_scoped_delete_rejects_unsafe_user_id(self, valkey_db):
        with pytest.raises(ValueError):
            valkey_db.delete_by_content_id("cid1", user_id=SHARED)

    async def test_async_insert_rejects_unsafe_user_id(self, valkey_db):
        with pytest.raises(ValueError):
            await valkey_db.async_insert(content_hash="h", documents=[_embedded("a", "x")], user_id="")


class TestTagEscaping:
    """FT.SEARCH TAG syntax is punctuation-driven, so an owner id carrying a
    separator or an operator must be escaped into a single literal tag —
    otherwise ``alice|bob`` would union two owners' buckets into one scope."""

    @pytest.mark.parametrize(
        "raw, escaped",
        [
            ("alice", "alice"),
            ("alice_1", "alice_1"),
            ("alice-1", r"alice\-1"),
            ("alice bob", r"alice\ bob"),
            ("alice|bob", r"alice\|bob"),
            ("a.b@c.com", r"a\.b\@c\.com"),
            ("user:42", r"user\:42"),
        ],
    )
    def test_escape_tag_value(self, raw, escaped):
        assert _escape_tag_value(raw) == escaped

    def test_pipe_in_owner_id_does_not_union_two_buckets(self, valkey_db):
        # Only the trailing "|" is the alternation; the owner's own "|" is escaped.
        assert valkey_db._user_scope_expression("alice|bob") == r"@user_id:{alice\|bob|__shared__}"

    def test_pipe_owner_cannot_read_either_named_owner(self, valkey_db):
        valkey_db.insert(content_hash="h1", documents=[_embedded("alice-doc", "secret alpha")], user_id="alice")
        valkey_db.insert(content_hash="h2", documents=[_embedded("bob-doc", "secret bravo")], user_id="bob")
        assert valkey_db.vector_search("secret", limit=10, user_id="alice|bob") == []

    def test_separator_bearing_owner_ids_stay_distinct(self, valkey_db):
        valkey_db.insert(content_hash="h1", documents=[_embedded("hyphen-doc", "secret alpha")], user_id="alice-1")
        valkey_db.insert(content_hash="h2", documents=[_embedded("plain-doc", "secret bravo")], user_id="alice")
        assert [d.name for d in valkey_db.vector_search("secret", limit=10, user_id="alice-1")] == ["hyphen-doc"]
        assert [d.name for d in valkey_db.vector_search("secret", limit=10, user_id="alice")] == ["plain-doc"]

    def test_scoped_delete_escapes_the_owner(self, valkey_db):
        valkey_db.delete_by_content_id("cid1", user_id="alice bob")
        assert _last_query(valkey_db) == r"@content_id:{cid1} @user_id:{alice\ bob}"

    def test_keyword_query_punctuation_cannot_break_the_scope(self, valkey_db):
        """A crafted keyword query must not inject its own TAG clause; the
        query text is reduced to alphanumeric terms before it is embedded."""
        valkey_db.search_type = SearchType.keyword
        valkey_db.search(query="x} @user_id:{bob", limit=5, user_id="alice")
        # Every operator character is dropped, so the injected clause survives
        # only as an inert content term.
        assert _last_query(valkey_db) == "(@content:x user_idbob) @user_id:{alice|__shared__}"
