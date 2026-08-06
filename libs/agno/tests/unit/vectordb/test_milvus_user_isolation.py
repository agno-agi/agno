"""Milvus per-user RAG isolation contract.

Milvus keeps the owner in a declared top-level ``user_id`` scalar field and
pushes the scope into the filter expression: ``user_id == <caller> or user_id
is null``. A scoped caller sees their own chunks plus the shared (NULL-owned)
bucket and never another owner's; an unscoped (``user_id=None``) read applies
no scope and sees everything.

The field has to be DECLARED. Milvus keeps unset dynamic keys out of ``$meta``
entirely and ``is null`` cannot match a key that is not there, so an undeclared
owner field costs every scoped caller the shared bucket and every chunk written
before isolation existed - silently, with no error anywhere.

``FakeMilvusClient`` stands in for the engine: it really evaluates the filter
expression the backend built against stored rows. Its null handling follows a
real Milvus server rather than Milvus Lite - only a declared field reads as
NULL. Lite answers ``is null`` for an absent dynamic key too, which is why an
embedded run scores the pre-fix schema exactly like the fixed one and cannot see
this bug at all.
"""

import json
import re
from typing import Any, Dict, List, Optional
from unittest.mock import Mock

import pytest

from agno.knowledge.document import Document
from agno.knowledge.embedder.base import Embedder

try:
    import pymilvus  # noqa: F401

    MILVUS_AVAILABLE = True
except ImportError:
    MILVUS_AVAILABLE = False

pytestmark = pytest.mark.skipif(not MILVUS_AVAILABLE, reason="pymilvus is required for the Milvus isolation tests")

if MILVUS_AVAILABLE:
    from pymilvus import DataType, MilvusClient

    from agno.vectordb.milvus import Milvus
    from agno.vectordb.milvus.milvus import USER_ID_FIELD
    from agno.vectordb.search import SearchType

TEST_COLLECTION = "isolation_test"
TEST_DIMENSION = 8

# A field that resolved to nothing at all. Distinct from None, which is a stored NULL.
_MISSING = object()

_EQUALS = re.compile(r'^(\w+)(?:\["(\w+)"\])?\s*==\s*"(.*)"$', re.DOTALL)
_IS_NULL = re.compile(r'^(\w+)(?:\["(\w+)"\])?\s+is\s+null$')


def _split(clause: str, operator: str) -> List[str]:
    """Split on a top-level ``and`` / ``or``, skipping one nested in parentheses or
    inside a quoted literal. An escaped owner id can contain either."""
    parts, depth, quote, start, index = [], 0, "", 0, 0
    while index < len(clause):
        char = clause[index]
        if quote:
            if char == "\\":
                index += 2
                continue
            if char == quote:
                quote = ""
        elif char in "\"'":
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif depth == 0 and clause.startswith(operator, index):
            parts.append(clause[start:index])
            start = index + len(operator)
            index = start
            continue
        index += 1
    parts.append(clause[start:])
    return parts


class FakeCollection:
    """One Milvus collection: its declared fields plus an id-keyed row store.

    Rows are stored flat, with the server's null rules already applied - a
    declared field that was never written reads as NULL, and a dynamic key
    written with no value is simply absent, because ``$meta`` does not store
    nulls. That is the whole difference between the two engines: on a real
    server ``is null`` matches the first and not the second, on Milvus Lite it
    matches both.
    """

    def __init__(self, name: str, schema: Any = None, dimension: Optional[int] = None):
        self.name = name
        self.schema = schema
        if schema is not None:
            self.fields = [
                {
                    "name": field.name,
                    "is_primary": field.is_primary,
                    "nullable": field.nullable,
                    "type": field.dtype,
                    "params": dict(field.params or {}),
                }
                for field in schema.fields
            ]
            self.enable_dynamic_field = bool(schema.enable_dynamic_field)
        else:
            # The quick-setup path: an id and a vector, nothing else declared.
            self.fields = [
                {"name": "id", "is_primary": True, "nullable": False, "params": {"max_length": 65_535}},
                {"name": "vector", "is_primary": False, "nullable": False, "params": {"dim": dimension}},
            ]
            self.enable_dynamic_field = True
        self.declared = [field["name"] for field in self.fields]
        self.rows: Dict[str, Dict[str, Any]] = {}

    def store(self, data: Dict[str, Any]) -> None:
        row: Dict[str, Any] = {name: None for name in self.declared}
        for key, value in data.items():
            if key in self.declared:
                row[key] = value
            elif not self.enable_dynamic_field:
                raise AssertionError(f"FakeCollection {self.name!r} has no field {key!r} and no dynamic field")
            elif value is not None:
                row[key] = value
        self.rows[row["id"]] = row

    def value(self, row: Dict[str, Any], field: str, key: Optional[str] = None) -> Any:
        """Resolve ``field`` or ``field["key"]``, keeping a stored NULL distinct
        from a key that is not there at all."""
        found = row.get(field, _MISSING)
        if key is None:
            return found
        if isinstance(found, str):
            found = json.loads(found)
        return found.get(key, _MISSING) if isinstance(found, dict) else _MISSING

    def evaluate(self, row: Dict[str, Any], clause: str) -> bool:
        """Evaluate the expression grammar this backend emits - ``field == "value"``
        and ``field is null``, optionally subscripted as ``meta_data["key"]``, joined
        by ``or`` / ``and`` and parenthesised. Anything else raises, so an expression
        that changes shape fails loudly instead of quietly matching every row."""
        clause = clause.strip()
        parts = _split(clause, " or ")
        if len(parts) > 1:
            return any(self.evaluate(row, part) for part in parts)
        parts = _split(clause, " and ")
        if len(parts) > 1:
            return all(self.evaluate(row, part) for part in parts)
        if clause.startswith("(") and clause.endswith(")"):
            return self.evaluate(row, clause[1:-1])

        is_null = _IS_NULL.match(clause)
        if is_null:
            return self.value(row, *is_null.groups()) is None
        equals = _EQUALS.match(clause)
        if equals:
            field, key, literal = equals.groups()
            # Undo the escape so ``zzz\" or ...`` compares as the one literal it is.
            return self.value(row, field, key) == literal.replace('\\"', '"').replace("\\\\", "\\")
        raise AssertionError(f"FakeCollection cannot evaluate predicate {clause!r}")


class FakeMilvusClient:
    """A Milvus stand-in that runs the filter expression the backend built against
    its own rows, so a wrong expression returns the wrong rows rather than a
    passing assertion about a call. It also keeps every expression it was sent.
    """

    def __init__(self):
        self.collections: Dict[str, FakeCollection] = {}
        # The filter expressions the backend handed to the server, in call order.
        self.search_filters: List[Optional[str]] = []
        self.delete_filters: List[Optional[str]] = []
        # The AnnSearchRequests of every hybrid read, in call order.
        self.hybrid_requests: List[List[Any]] = []

    def _collection(self, collection_name: str) -> FakeCollection:
        if collection_name not in self.collections:
            raise AssertionError(f"Collection {collection_name!r} does not exist")
        return self.collections[collection_name]

    def _select(self, collection_name: str, expression: Optional[str]) -> List[Dict[str, Any]]:
        collection = self._collection(collection_name)
        rows = list(collection.rows.values())
        if not expression:
            return rows
        return [row for row in rows if collection.evaluate(row, expression)]

    @staticmethod
    def _hits(rows: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
        return [[{"id": row["id"], "entity": dict(row)} for row in rows]]

    def rows(self, collection_name: str) -> List[Dict[str, Any]]:
        return list(self._collection(collection_name).rows.values())

    def prepare_index_params(self) -> Any:
        return MilvusClient.prepare_index_params()

    def has_collection(self, collection_name: str) -> bool:
        return collection_name in self.collections

    def create_collection(self, collection_name, schema=None, index_params=None, dimension=None, **kwargs) -> None:
        self.collections[collection_name] = FakeCollection(collection_name, schema=schema, dimension=dimension)

    def describe_collection(self, collection_name: str) -> Dict[str, Any]:
        collection = self._collection(collection_name)
        return {"fields": collection.fields, "enable_dynamic_field": collection.enable_dynamic_field}

    def drop_collection(self, collection_name: str) -> None:
        self.collections.pop(collection_name, None)

    def insert(self, collection_name: str, data) -> None:
        for row in data if isinstance(data, list) else [data]:
            self._collection(collection_name).store(row)

    def upsert(self, collection_name: str, data) -> None:
        self.insert(collection_name, data)

    def query(self, collection_name, filter=None, output_fields=None, limit=None, **kwargs) -> List[Dict[str, Any]]:
        rows = self._select(collection_name, filter)
        if limit is not None:
            rows = rows[:limit]
        if output_fields and "*" not in output_fields:
            return [{field: row.get(field) for field in output_fields} for row in rows]
        return [dict(row) for row in rows]

    def search(self, collection_name, data, filter=None, output_fields=None, limit=10, search_params=None):
        self.search_filters.append(filter)
        return self._hits(self._select(collection_name, filter)[:limit])

    def hybrid_search(self, collection_name, reqs, ranker=None, limit=10, output_fields=None):
        self.hybrid_requests.append(list(reqs))
        merged: Dict[str, Dict[str, Any]] = {}
        for request in reqs:
            for row in self._select(collection_name, getattr(request, "expr", None)):
                merged[row["id"]] = row
        return self._hits(list(merged.values())[:limit])

    def delete(self, collection_name, filter=None, ids=None) -> None:
        collection = self._collection(collection_name)
        if ids is not None:
            for row_id in ids:
                collection.rows.pop(row_id, None)
            return
        self.delete_filters.append(filter)
        for row in self._select(collection_name, filter):
            del collection.rows[row["id"]]


class AsyncFakeMilvusClient:
    """Async facade over the same FakeMilvusClient, so the async half hits the same rows."""

    def __init__(self, client: FakeMilvusClient):
        self._client = client

    async def create_collection(self, collection_name, schema=None, index_params=None) -> None:
        self._client.create_collection(collection_name, schema=schema, index_params=index_params)

    async def insert(self, collection_name, data) -> None:
        self._client.insert(collection_name, data)

    async def search(self, collection_name, data, filter=None, output_fields=None, limit=10, search_params=None):
        return self._client.search(collection_name, data, filter, output_fields, limit, search_params)

    async def hybrid_search(self, collection_name, reqs, ranker=None, limit=10, output_fields=None):
        return self._client.hybrid_search(collection_name, reqs, ranker, limit, output_fields)


@pytest.fixture
def mock_embedder():
    embedder = Mock(spec=Embedder)
    embedder.dimensions = TEST_DIMENSION
    embedder.enable_batch = False
    embedder.get_embedding.return_value = [0.1] * TEST_DIMENSION
    embedder.get_embedding_and_usage.return_value = ([0.1] * TEST_DIMENSION, {"tokens": 10})
    embedder.async_get_embedding_and_usage.return_value = ([0.1] * TEST_DIMENSION, {"tokens": 10})
    return embedder


@pytest.fixture
def milvus_db(mock_embedder):
    """A vector-mode Milvus wired to FakeMilvusClient - no engine, no ``.db`` file."""
    db = Milvus(collection=TEST_COLLECTION, embedder=mock_embedder)
    db._client = FakeMilvusClient()
    db._async_client = AsyncFakeMilvusClient(db._client)
    db.create()
    return db


@pytest.fixture
def hybrid_db(mock_embedder):
    """A hybrid-mode Milvus on the same fake, so the dense/sparse read paths are
    exercised rather than assumed."""
    db = Milvus(collection=TEST_COLLECTION, embedder=mock_embedder, search_type=SearchType.hybrid)
    db._client = FakeMilvusClient()
    db._async_client = AsyncFakeMilvusClient(db._client)
    db.create()
    return db


def _declared_fields(db) -> List[str]:
    """The collection's declared (non-dynamic) field names."""
    return [field["name"] for field in db.client.describe_collection(TEST_COLLECTION)["fields"]]


def _owner_field(db) -> Any:
    """The owner field as the backend declared it to the server."""
    schema = db.client.collections[TEST_COLLECTION].schema
    return next(field for field in schema.fields if field.name == USER_ID_FIELD)


def _doc(name: str, content: str, content_id: Optional[str] = None) -> Document:
    doc = Document(name=name, content=content)
    if content_id is not None:
        doc.content_id = content_id
    return doc


def _alice_docs() -> List[Document]:
    return [_doc("alice-salary", "Alice's salary is $180k.")]


def _bob_docs() -> List[Document]:
    return [_doc("bob-salary", "Bob's salary is $215k.")]


def _shared_docs() -> List[Document]:
    return [_doc("company-holidays", "The office is closed Jan 1.")]


def _rows(db) -> List[Dict[str, Any]]:
    return db.client.rows(TEST_COLLECTION)


def _owners(db) -> List[str]:
    return sorted(str(row.get(USER_ID_FIELD)) for row in _rows(db))


def _count(db) -> int:
    return len(_rows(db))


def _names(documents: List[Document]) -> set:
    return {document.name for document in documents}


# The scope predicate every scoped read has to carry.
SCOPE = '(user_id == "alice" or user_id is null)'


class TestCollectionSchemaDeclaresOwner:
    """``user_id`` has to be a *declared* field in every creation path. Milvus
    keeps unset dynamic keys out of ``$meta``, so on a real server ``user_id is
    null`` matches no row at all and the shared bucket - plus every chunk written
    before isolation existed - vanishes from every scoped search."""

    def test_default_collection_declares_user_id(self, milvus_db):
        assert USER_ID_FIELD in _declared_fields(milvus_db)

    def test_hybrid_collection_declares_user_id(self, hybrid_db):
        assert USER_ID_FIELD in _declared_fields(hybrid_db)

    def test_owner_field_is_a_nullable_varchar(self, milvus_db):
        """The shared bucket is stored as NULL, so the field has to accept it,
        and it has to be a scalar the filter expression can compare."""
        owner = _owner_field(milvus_db)
        assert owner.nullable is True
        assert owner.dtype == DataType.VARCHAR
        assert owner.params["max_length"] == 256

    def test_hybrid_owner_field_is_a_nullable_varchar(self, hybrid_db):
        owner = _owner_field(hybrid_db)
        assert owner.nullable is True
        assert owner.dtype == DataType.VARCHAR

    def test_default_collection_keeps_its_shape(self, milvus_db):
        """Declaring the owner must not disturb anything else: same primary key,
        same vector field, and dynamic fields still on so meta_data keeps landing
        in $meta."""
        fields = {field["name"]: field for field in milvus_db.client.describe_collection(TEST_COLLECTION)["fields"]}
        assert fields["id"]["is_primary"] is True
        assert fields["id"]["params"]["max_length"] == 65_535
        assert fields["vector"]["params"]["dim"] == TEST_DIMENSION
        assert milvus_db.client.describe_collection(TEST_COLLECTION)["enable_dynamic_field"] is True

    async def test_async_create_declares_user_id(self, mock_embedder):
        """The async client creates the collection through its own call, so the
        schema it is handed has to declare the owner too."""
        db = Milvus(collection=TEST_COLLECTION, embedder=mock_embedder)
        db._client = FakeMilvusClient()
        db._async_client = AsyncFakeMilvusClient(db._client)

        await db.async_create()

        assert USER_ID_FIELD in _declared_fields(db)


class TestLegacyCollectionWithoutOwnerField:
    """A collection created before the owner field existed keeps its old schema.
    Milvus cannot add a field in place, so ``create()`` leaves it alone - repairing
    it is an explicit migration, never a silent side effect of connecting.

    ``create()`` says nothing about it either, so the only signal a deployment gets
    is the missing rows in ``test_undeclared_owner_hides_the_shared_bucket``."""

    @pytest.fixture
    def legacy_db(self, mock_embedder):
        db = Milvus(collection=TEST_COLLECTION, embedder=mock_embedder)
        db._client = FakeMilvusClient()
        db._async_client = AsyncFakeMilvusClient(db._client)
        # The pre-fix quick-setup call, verbatim: no owner field is declared.
        db.client.create_collection(
            collection_name=TEST_COLLECTION,
            dimension=TEST_DIMENSION,
            metric_type="COSINE",
            id_type="string",
            max_length=65_535,
        )
        return db

    def test_create_does_not_touch_the_schema(self, legacy_db):
        assert USER_ID_FIELD not in _declared_fields(legacy_db)
        legacy_db.create()
        assert USER_ID_FIELD not in _declared_fields(legacy_db)

    def test_undeclared_owner_hides_the_shared_bucket(self, legacy_db):
        """The cost of the missing field. With the owner undeclared the value lands
        in the dynamic field, ``$meta`` drops it because it is null, and the
        ``or user_id is null`` arm matches nothing - so alice keeps her own chunks
        and loses every shared one, with nothing logged anywhere."""
        legacy_db.insert(content_hash="ha", documents=_alice_docs(), user_id="alice")
        legacy_db.insert(content_hash="hs", documents=_shared_docs(), user_id=None)

        assert _names(legacy_db.search("salary", limit=20, user_id="alice")) == {"alice-salary"}


class TestUserIdFieldStorage:
    """Pin the contract: ``user_id`` is a top-level field, not nested in
    meta_data. The owner-scope filter relies on this."""

    def test_user_id_key_constant_is_user_id(self):
        assert USER_ID_FIELD == "user_id"

    def test_explicit_user_id_persisted_top_level(self, milvus_db):
        milvus_db.insert(content_hash="h1", documents=_alice_docs(), user_id="alice")

        (row,) = _rows(milvus_db)
        assert row[USER_ID_FIELD] == "alice"
        # And NOT smuggled into the caller-controlled meta_data blob.
        assert "user_id" not in milvus_db._decode_json_field(row.get("meta_data"), default={})

    def test_none_user_id_persisted_as_null(self, milvus_db):
        milvus_db.insert(content_hash="h1", documents=_shared_docs(), user_id=None)

        (row,) = _rows(milvus_db)
        assert row[USER_ID_FIELD] is None

    def test_user_id_omitted_defaults_to_null(self, milvus_db):
        """Backwards-compatible: callers that never pass ``user_id`` get NULL
        (shared) - they're effectively opting out of isolation."""
        milvus_db.insert(content_hash="h1", documents=_shared_docs())

        (row,) = _rows(milvus_db)
        assert row[USER_ID_FIELD] is None


class TestScopeExpressionBuilder:
    """The scope-expression builder is small enough to unit-test directly."""

    def test_none_user_id_applies_no_scope(self, milvus_db):
        # user_id=None is the admin view: the metadata filter passes through unchanged.
        assert milvus_db._scoped_expr(None, None) is None
        assert milvus_db._scoped_expr({"tag": "x"}, None) == 'meta_data["tag"] == "x"'

    def test_alice_scope_is_own_or_null(self, milvus_db):
        assert milvus_db._scoped_expr(None, "alice") == SCOPE

    def test_scoped_expr_ands_metadata_and_scope(self, milvus_db):
        expr = milvus_db._scoped_expr({"tag": "x"}, "alice")
        assert expr == f'(meta_data["tag"] == "x") and {SCOPE}'

    def test_empty_string_is_a_scoped_tenant_not_unscoped(self, milvus_db):
        # "" is a real owner, not an admin bypass - it scopes to its own bucket plus shared.
        assert milvus_db._scoped_expr(None, "") == '(user_id == "" or user_id is null)'

    def test_scope_expr_escapes_quotes_to_block_injection(self, milvus_db):
        # A quote in user_id cannot break out of the literal and widen the scope.
        expr = milvus_db._scoped_expr(None, 'zzz" or user_id == "bob')
        assert expr == '(user_id == "zzz\\" or user_id == \\"bob" or user_id is null)'

    def test_a_quoted_owner_still_matches_only_its_own_rows(self, milvus_db):
        """The escaped expression has to survive evaluation, not just look right.
        Unescaped it would parse as a third predicate and hand over bob's chunk."""
        attacker = 'zzz" or user_id == "bob'
        milvus_db.insert(content_hash="ha", documents=[_doc("attacker-doc", "salary note")], user_id=attacker)
        milvus_db.insert(content_hash="hb", documents=_bob_docs(), user_id="bob")
        milvus_db.insert(content_hash="hs", documents=_shared_docs(), user_id=None)

        found = _names(milvus_db.search("salary", limit=20, user_id=attacker))

        assert found == {"attacker-doc", "company-holidays"}


class TestFilterExpressionSentToMilvus:
    """The expression the backend actually handed to the server, on every read
    path. A scope that never leaves the builder protects nobody."""

    @pytest.fixture
    def populated_db(self, milvus_db):
        milvus_db.insert(content_hash="ha", documents=_alice_docs(), user_id="alice")
        return milvus_db

    def test_scoped_search_sends_the_scope_expression(self, populated_db):
        populated_db.search("salary", limit=10, user_id="alice")

        assert populated_db.client.search_filters[-1] == SCOPE

    def test_unscoped_search_sends_no_expression(self, populated_db):
        """Callers who never pass ``user_id`` must get the query they always got."""
        populated_db.search("salary", limit=10, user_id=None)

        assert populated_db.client.search_filters[-1] is None

    def test_scope_composes_with_metadata_filters(self, populated_db):
        """The metadata filter and the scope are ANDed; the scope's ``or`` stays
        parenthesised so it cannot widen the metadata predicate."""
        populated_db.search("salary", limit=10, filters={"team": "eng"}, user_id="alice")

        assert populated_db.client.search_filters[-1] == f'(meta_data["team"] == "eng") and {SCOPE}'

    async def test_async_scoped_search_sends_the_scope_expression(self, populated_db):
        await populated_db.async_search("salary", limit=10, user_id="alice")

        assert populated_db.client.search_filters[-1] == SCOPE

    def test_hybrid_search_scopes_both_halves(self, hybrid_db):
        """Two AnnSearchRequests go out. An unscoped sparse half would pull another
        owner's chunks into the reranked result even with the dense half scoped."""
        hybrid_db.insert(content_hash="ha", documents=_alice_docs(), user_id="alice")

        hybrid_db.search("salary", limit=10, user_id="alice")

        dense, sparse = hybrid_db.client.hybrid_requests[-1]
        assert dense.anns_field == "dense_vector"
        assert sparse.anns_field == "sparse_vector"
        assert dense.expr == SCOPE
        assert sparse.expr == SCOPE

    def test_unscoped_hybrid_search_sends_no_expression(self, hybrid_db):
        hybrid_db.insert(content_hash="ha", documents=_alice_docs(), user_id="alice")

        hybrid_db.search("salary", limit=10, user_id=None)

        assert [request.expr for request in hybrid_db.client.hybrid_requests[-1]] == [None, None]

    async def test_async_hybrid_search_scopes_both_halves(self, hybrid_db):
        await hybrid_db.async_insert(content_hash="ha", documents=_alice_docs(), user_id="alice")

        await hybrid_db.async_search("salary", limit=10, user_id="alice")

        assert [request.expr for request in hybrid_db.client.hybrid_requests[-1]] == [SCOPE, SCOPE]


class TestVectorSearchIsolation:
    """The load-bearing test: alice's search returns her chunks plus shared
    chunks, never bob's."""

    @pytest.fixture
    def populated_db(self, milvus_db):
        milvus_db.insert(content_hash="ha", documents=_alice_docs(), user_id="alice")
        milvus_db.insert(content_hash="hb", documents=_bob_docs(), user_id="bob")
        milvus_db.insert(content_hash="hs", documents=_shared_docs(), user_id=None)
        return milvus_db

    def test_alice_sees_her_own_and_shared(self, populated_db):
        names = _names(populated_db.search("salary", limit=20, user_id="alice"))
        assert "alice-salary" in names
        assert "company-holidays" in names

    def test_scope_predicate_matches_the_shared_bucket(self, populated_db):
        """The ``or user_id is null`` arm, evaluated on its own. It only matches
        while ``user_id`` is a declared field - a dynamic one is simply absent from
        ``$meta`` when unset, and then this arm matches nothing."""
        rows = populated_db.client.query(
            collection_name=TEST_COLLECTION,
            filter=populated_db._scoped_expr(None, "alice"),
            output_fields=["name", "user_id"],
        )

        names = {row.get("name") for row in rows}
        assert "company-holidays" in names
        assert "alice-salary" in names
        assert "bob-salary" not in names

    def test_scoped_caller_sees_a_pre_isolation_chunk(self, populated_db):
        """A chunk written before isolation shipped carries no ``user_id`` key at
        all. It belongs to the shared bucket and must stay reachable to a scoped
        caller."""
        populated_db.client.insert(
            collection_name=TEST_COLLECTION,
            data={
                "id": "legacy-row",
                "vector": [0.1] * TEST_DIMENSION,
                "name": "legacy-handbook",
                "content_id": "c-legacy",
                "meta_data": "{}",
                "content": "legacy handbook salary policy",
                "usage": "{}",
                "content_hash": "hL",
            },
        )

        assert "legacy-handbook" in _names(populated_db.search("salary", limit=20, user_id="alice"))

    def test_alice_never_sees_bob(self, populated_db):
        """The isolation contract. If this fails the feature is broken - alice
        would be retrieving bob's confidential chunks."""
        assert "bob-salary" not in _names(populated_db.search("salary", limit=20, user_id="alice"))

    def test_bob_never_sees_alice(self, populated_db):
        names = _names(populated_db.search("salary", limit=20, user_id="bob"))
        assert "alice-salary" not in names
        assert "bob-salary" in names

    def test_unknown_owner_sees_only_the_shared_bucket(self, populated_db):
        """Carol owns nothing, so the null arm is all that matches."""
        assert _names(populated_db.search("salary", limit=20, user_id="carol")) == {"company-holidays"}

    def test_admin_sees_everything(self, populated_db):
        names = _names(populated_db.search("salary", limit=20, user_id=None))
        assert {"alice-salary", "bob-salary", "company-holidays"} <= names

    async def test_async_alice_never_sees_bob(self, milvus_db):
        await milvus_db.async_insert(content_hash="ha", documents=_alice_docs(), user_id="alice")
        await milvus_db.async_insert(content_hash="hb", documents=_bob_docs(), user_id="bob")
        await milvus_db.async_insert(content_hash="hs", documents=_shared_docs(), user_id=None)

        names = _names(await milvus_db.async_search("salary", limit=20, user_id="alice"))

        assert "alice-salary" in names
        assert "company-holidays" in names
        assert "bob-salary" not in names


class TestHybridSearchIsolation:
    """Hybrid reads merge a dense and a sparse candidate list, so they are a
    second, independent way for another owner's chunk to reach the caller.
    ``hybrid_search`` swallows its own exceptions and returns ``[]``, so every
    test here asserts on something the caller SHOULD see as well."""

    @pytest.fixture
    def populated_db(self, hybrid_db):
        hybrid_db.insert(content_hash="ha", documents=_alice_docs(), user_id="alice")
        hybrid_db.insert(content_hash="hb", documents=_bob_docs(), user_id="bob")
        hybrid_db.insert(content_hash="hs", documents=_shared_docs(), user_id=None)
        return hybrid_db

    def test_alice_sees_her_own_and_shared_never_bob(self, populated_db):
        names = _names(populated_db.search("salary", limit=20, user_id="alice"))

        assert names == {"alice-salary", "company-holidays"}

    def test_admin_sees_everything(self, populated_db):
        names = _names(populated_db.search("salary", limit=20, user_id=None))

        assert {"alice-salary", "bob-salary", "company-holidays"} <= names

    def test_unknown_owner_sees_only_the_shared_bucket(self, populated_db):
        assert _names(populated_db.search("salary", limit=20, user_id="carol")) == {"company-holidays"}

    async def test_async_alice_never_sees_bob(self, populated_db):
        names = _names(await populated_db.async_search("salary", limit=20, user_id="alice"))

        assert names == {"alice-salary", "company-holidays"}


class TestSameContentDistinctOwners:
    """Steal-prevention: the owner is folded into the deterministic doc id, so two
    users uploading byte-identical content (same content_hash) land on distinct
    primary keys. Neither insert overwrites the other and the shared bucket stays
    independent - Milvus has no content-hash dedup delete, upsert is by primary key."""

    def test_two_owners_identical_content_both_survive(self, milvus_db):
        milvus_db.insert(content_hash="h", documents=[_doc("a", "same secret", "c1")], user_id="alice")
        milvus_db.insert(content_hash="h", documents=[_doc("b", "same secret", "c1")], user_id="bob")

        rows = _rows(milvus_db)
        assert len(rows) == 2
        assert len({row["id"] for row in rows}) == 2  # distinct primary keys
        assert _owners(milvus_db) == ["alice", "bob"]

    def test_underscored_base_id_cannot_collide_with_a_different_split(self, milvus_db):
        """The base id is collapsed to a fixed-length digest before the owner is
        folded in. Without that collapse the '_' boundary moves and
        ('doc', '1', 'a_lice') and ('doc', '1_a', 'lice') join to one primary key,
        letting one owner overwrite the other's row."""
        assert milvus_db._scoped_doc_id("doc", "1", "a_lice") != milvus_db._scoped_doc_id("doc", "1_a", "lice")
        # whatever the caller passes, the owner is always folded into a fixed-length digest
        assert len(milvus_db._scoped_doc_id("doc_1_2_3", "h", None)) == 32

    def test_shared_reingest_does_not_wipe_owned(self, milvus_db):
        """A shared (NULL-owned) re-ingest of content a user already owns must not
        clobber the owned row - the two rows are keyed independently."""
        milvus_db.insert(content_hash="h", documents=[_doc("a", "same secret", "c1")], user_id="alice")
        milvus_db.insert(content_hash="h", documents=[_doc("s", "same secret", "c1")], user_id=None)

        assert _owners(milvus_db) == ["None", "alice"]

    async def test_async_two_owners_identical_content_both_survive(self, milvus_db):
        await milvus_db.async_insert(content_hash="h", documents=[_doc("a", "same secret", "c1")], user_id="alice")
        await milvus_db.async_insert(content_hash="h", documents=[_doc("b", "same secret", "c1")], user_id="bob")

        assert _owners(milvus_db) == ["alice", "bob"]


class TestUpdateMetadataOwnership:
    """``update_metadata`` writes into the caller-controlled meta_data blob; it must
    never reassign the top-level owner, even if a ``user_id`` key is smuggled in."""

    def test_update_metadata_cannot_reassign_owner(self, milvus_db):
        milvus_db.insert(content_hash="h", documents=[_doc("a", "Alice secret", "c1")], user_id="alice")

        milvus_db.update_metadata("c1", {"user_id": "bob", "tag": "x"})

        (row,) = _rows(milvus_db)
        assert row[USER_ID_FIELD] == "alice"  # owner untouched
        meta = milvus_db._decode_json_field(row.get("meta_data"), default={})
        assert "user_id" not in meta  # stripped from the metadata blob too
        assert meta.get("tag") == "x"  # legitimate keys still applied


class TestDeleteByContentIdIsolation:
    """``delete_by_content_id(content_id, user_id=...)`` must scope the delete to
    the caller's chunks - otherwise Bob could guess Alice's content_id and wipe
    her chunks, or a scoped caller could wipe the org's shared chunks."""

    @pytest.fixture
    def populated_db(self, milvus_db):
        milvus_db.insert(content_hash="ha", documents=[_doc("alice-doc", "Alice secret", "doc-1")], user_id="alice")
        milvus_db.insert(content_hash="hb", documents=[_doc("bob-doc", "Bob secret", "doc-1")], user_id="bob")
        milvus_db.insert(content_hash="hs", documents=[_doc("shared-doc", "Shared", "doc-1")], user_id=None)
        return milvus_db

    def test_scoped_delete_only_removes_callers_chunks(self, populated_db):
        """Bob deletes 'doc-1' under his own scope - alice's AND the shared chunk
        must remain."""
        assert populated_db.delete_by_content_id("doc-1", user_id="bob") is True

        assert _owners(populated_db) == ["None", "alice"]

    def test_scoped_delete_ands_the_owner_into_the_expression(self, populated_db):
        """Both predicates go out together: content_id AND owner. Losing the owner
        arm turns a scoped delete into a cross-tenant wipe."""
        populated_db.delete_by_content_id("doc-1", user_id="bob")

        assert populated_db.client.delete_filters[-1] == 'content_id == "doc-1" and user_id == "bob"'

    def test_scoped_delete_does_not_touch_shared(self, populated_db):
        """A scoped caller must never delete the shared (NULL-owned) bucket."""
        populated_db.delete_by_content_id("doc-1", user_id="alice")

        owners = _owners(populated_db)
        assert "None" in owners  # shared survived
        assert "alice" not in owners

    def test_unscoped_delete_wipes_everyone(self, populated_db):
        """Legacy behaviour: ``user_id=None`` deletes across all owners."""
        assert populated_db.delete_by_content_id("doc-1", user_id=None) is True

        assert _count(populated_db) == 0

    def test_scoped_delete_is_no_op_when_nothing_owned(self, populated_db):
        """Carol owns nothing; her scoped delete of doc-1 removes no rows."""
        populated_db.delete_by_content_id("doc-1", user_id="carol")

        assert _count(populated_db) == 3


class TestContentHashExistsIsScoped:
    """``content_hash_exists`` is the guard half of the upsert dedup pair, so it
    means what a scoped delete means: a set owner checks that owner's chunks and
    ``None`` checks the shared (NULL-owned) bucket alone, never every owner."""

    def test_scoped_check_sees_only_the_owner(self, milvus_db):
        milvus_db.insert(content_hash="h1", documents=_alice_docs(), user_id="alice")

        assert milvus_db.content_hash_exists("h1", user_id="alice") is True
        assert milvus_db.content_hash_exists("h1", user_id="bob") is False

    def test_none_check_sees_the_shared_row(self, milvus_db):
        """The owner field is DECLARED nullable, so a shared write stores a real
        NULL and ``is null`` resolves it. On a dynamic field the key would simply
        be absent and the predicate would match nothing."""
        milvus_db.insert(content_hash="h1", documents=_shared_docs(), user_id=None)

        assert milvus_db.content_hash_exists("h1", user_id=None) is True

    def test_none_check_does_not_see_a_privately_owned_row(self, milvus_db):
        """Alice privately holds this content. If ``None`` matched her row, a shared
        publish of the same bytes would be judged a duplicate and silently skipped,
        and the shared bucket would never receive it."""
        milvus_db.insert(content_hash="h1", documents=_alice_docs(), user_id="alice")

        assert milvus_db.content_hash_exists("h1", user_id=None) is False
        assert milvus_db.content_hash_exists("h1", user_id="alice") is True
