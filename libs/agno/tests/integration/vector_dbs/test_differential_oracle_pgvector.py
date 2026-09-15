"""Differential ranking harness: OracleVector vs PgVector.

Ticket 17's own acceptance criterion: the same corpus and query, embedded
with the same deterministic offline embedder (no API key needed), must
produce the same top-k ordering on both backends. PgVector is the reference
implementation for OracleVector (see OracleVector's own module docstring);
this is the vector-similarity-only differential, matching this ticket's own
scope (keyword/hybrid search is ticket 18's).

Both fixtures skip cleanly (not error) when their server is unreachable,
matching the sync storage-adapter harness's own convention (ADR 0009: no
Oracle container in public CI).
"""

import uuid
from hashlib import md5
from typing import Any, Dict, List

import pytest
from sqlalchemy import create_engine, text

from agno.knowledge.document import Document
from agno.vectordb.distance import Distance
from agno.vectordb.oracle import OracleVector
from agno.vectordb.pgvector import PgVector

PG_URL = "postgresql+psycopg://ai:ai@localhost:5532/ai"
ORACLE_URL = "oracle+oracledb://ai:ai@localhost:1523/?service_name=FREEPDB1"


class _CorpusEmbedder:
    """Deterministic, offline, bag-of-hashed-words embedder with genuine
    geometric structure (unlike a pure one-hot embedder, two texts sharing
    words end up closer together), so a differential ranking comparison is
    meaningful rather than trivially degenerate.
    """

    enable_batch = False
    dimensions = 16

    def _vec(self, text: str) -> List[float]:
        words = text.lower().split()
        vec = [0.0] * self.dimensions
        for w in words:
            vec[int(md5(w.encode()).hexdigest(), 16) % self.dimensions] += 1.0
        norm = sum(v * v for v in vec) ** 0.5
        return [v / norm for v in vec] if norm else vec

    def get_embedding(self, text: str) -> List[float]:
        return self._vec(text)

    def get_embedding_and_usage(self, text: str):
        return self._vec(text), {"total_tokens": 1}

    def embed(self, document, *args, **kwargs):
        document.embedding = self._vec(document.content)
        document.usage = {"total_tokens": 1}
        return document


def _reachable(url: str) -> bool:
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            conn.execute(text("select 1 from dual") if "oracle" in url else text("select 1"))
        return True
    except Exception:
        return False
    finally:
        engine.dispose()


@pytest.fixture(scope="module")
def _servers_up():
    if not _reachable(PG_URL):
        pytest.skip(f"Postgres server not reachable at {PG_URL}")
    if not _reachable(ORACLE_URL):
        pytest.skip(f"Oracle server not reachable at {ORACLE_URL}")


@pytest.fixture
def pg_db(_servers_up):
    table_name = f"diff_vec_{uuid.uuid4().hex[:8]}"
    database = PgVector(table_name=table_name, db_url=PG_URL, embedder=_CorpusEmbedder(), distance=Distance.cosine)
    database.create()
    yield database
    database.drop()


@pytest.fixture
def oracle_db(_servers_up):
    table_name = f"diff_vec_{uuid.uuid4().hex[:8]}"
    database = OracleVector(
        table_name=table_name, db_url=ORACLE_URL, embedder=_CorpusEmbedder(), distance=Distance.cosine
    )
    database.create()
    yield database
    database.drop()


CORPUS = [
    Document(name="cats", content="Cats are small furry mammals that purr and sleep most of the day."),
    Document(name="dogs", content="Dogs are loyal furry mammals that bark and love to play fetch."),
    Document(name="rockets", content="Rockets use combustion to reach orbit and travel through space."),
    Document(name="planets", content="Planets orbit stars and some have rings made of ice and rock."),
    Document(name="bread", content="Bread is made from flour, water, yeast, and baked in an oven."),
]

QUERIES = [
    "furry pet mammal",
    "space travel orbit",
    "baking food oven",
]


def _run_ranking_scenario(db) -> Dict[str, Any]:
    db.insert(content_hash="corpus-1", documents=[Document(name=d.name, content=d.content) for d in CORPUS])

    results: Dict[str, Any] = {}
    for query in QUERIES:
        matches = db.search(query, limit=5)
        results[query] = {
            "order": [m.name for m in matches],
            "count": len(matches),
        }
    return results


def test_vector_search_ranking_matches_postgres(pg_db, oracle_db):
    """Same corpus, same queries, same embedder: the top-k ordering must match."""
    pg_result = _run_ranking_scenario(pg_db)
    oracle_result = _run_ranking_scenario(oracle_db)

    assert oracle_result == pg_result, (
        f"OracleVector diverged from PgVector.\nPostgres: {pg_result}\nOracle:   {oracle_result}"
    )


def test_similarity_scores_are_close_across_backends(pg_db, oracle_db):
    """The similarity scores themselves (not just the ordering) should agree
    within floating-point tolerance -- both compute cosine distance from the
    same vectors, just through different SQL functions.
    """
    for db in (pg_db, oracle_db):
        db.insert(content_hash="corpus-1", documents=[Document(name=d.name, content=d.content) for d in CORPUS])

    pg_top = pg_db.search("furry pet mammal", limit=1)[0]
    oracle_top = oracle_db.search("furry pet mammal", limit=1)[0]

    assert pg_top.name == oracle_top.name
    pg_score = pg_top.meta_data["similarity_score"]
    oracle_score = oracle_top.meta_data["similarity_score"]
    assert abs(pg_score - oracle_score) < 1e-6, f"similarity scores diverged: pg={pg_score} oracle={oracle_score}"
