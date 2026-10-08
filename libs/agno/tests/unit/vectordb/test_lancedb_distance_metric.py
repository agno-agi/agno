"""
Regression test for agno issue #10883:
LanceDB searches must forward the configured distance metric to the query.

Before the fix, self.distance was stored in __init__ but never passed to
self.table.search(...), so every query used LanceDB's default L2 metric
regardless of the configured Distance enum value.
"""
import inspect
import pytest


def test_lancedb_metric_helper_maps_cosine():
    from agno.vectordb.distance import Distance
    from agno.vectordb.lancedb.lance_db import LanceDb

    src = inspect.getsource(LanceDb._lancedb_metric)
    assert "cosine" in src or "distance.value" in src


def test_lancedb_metric_helper_maps_max_inner_product_to_dot():
    """max_inner_product must map to "dot" because LanceDB uses that string."""
    from agno.vectordb.distance import Distance
    from agno.vectordb.lancedb.lance_db import LanceDb

    src = inspect.getsource(LanceDb._lancedb_metric)
    assert "dot" in src
    assert "max_inner_product" in src


def test_vector_search_calls_metric():
    """vector_search must call .metric() on the LanceDB query builder."""
    from agno.vectordb.lancedb.lance_db import LanceDb

    src = inspect.getsource(LanceDb.vector_search)
    assert ".metric(" in src, (
        "vector_search must call .metric() on the LanceDB query builder; "
        "without it the configured distance is silently ignored"
    )


def test_hybrid_search_calls_metric():
    """hybrid_search must call .metric() on the LanceDB query builder."""
    from agno.vectordb.lancedb.lance_db import LanceDb

    src = inspect.getsource(LanceDb.hybrid_search)
    assert ".metric(" in src, (
        "hybrid_search must call .metric() on the LanceDB query builder; "
        "without it the configured distance is silently ignored"
    )


def test_lancedb_metric_returns_correct_values():
    """_lancedb_metric() must return the right string for each Distance value."""
    from unittest.mock import MagicMock, patch
    from agno.vectordb.distance import Distance
    from agno.vectordb.lancedb.lance_db import LanceDb

    # Build a minimal LanceDb instance without connecting to anything
    with patch.object(LanceDb, "__init__", lambda self, *a, **kw: None):
        db = LanceDb.__new__(LanceDb)

    db.distance = Distance.cosine
    assert db._lancedb_metric() == "cosine"

    db.distance = Distance.l2
    assert db._lancedb_metric() == "l2"

    db.distance = Distance.max_inner_product
    assert db._lancedb_metric() == "dot"
