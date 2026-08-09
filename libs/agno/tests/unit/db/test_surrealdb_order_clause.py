"""An omitted sort_order must mean descending, as it does in every other backend.

`order_limit_start` builds the ORDER BY / LIMIT / START tail of every SurrealDB
listing query. When sort_order was omitted it emitted a bare `ORDER BY {field}`,
and SurrealDB parses a direction-less ORDER BY as ascending, so listings that
every other backend returns newest first came back oldest first here.

These are pure string assertions: `order_limit_start` builds SurrealQL and never
touches a connection, matching how test_surrealdb_models.py covers this backend.
"""

from agno.db.surrealdb.queries import order_limit_start


def test_omitted_sort_order_is_descending():
    """The case that was wrong: no direction at all, which SurrealDB read as ascending."""
    assert order_limit_start(sort_by="created_at") == "ORDER BY created_at DESC"


def test_explicit_sort_order_is_unchanged():
    """The explicit directions keep working; only the omitted case moves."""
    assert order_limit_start(sort_by="created_at", sort_order="desc") == "ORDER BY created_at DESC"
    assert order_limit_start(sort_by="created_at", sort_order="asc") == "ORDER BY created_at ASC"


def test_sort_order_matching_is_case_insensitive():
    """Callers pass both cases; three call sites in surrealdb.py pass "DESC"."""
    assert order_limit_start(sort_by="created_at", sort_order="DESC") == "ORDER BY created_at DESC"
    assert order_limit_start(sort_by="created_at", sort_order="ASC") == "ORDER BY created_at ASC"


def test_unrecognized_sort_order_is_still_ascending():
    """Anything that is not "desc" stayed ascending before and stays ascending now."""
    assert order_limit_start(sort_by="created_at", sort_order="") == "ORDER BY created_at ASC"
    assert order_limit_start(sort_by="created_at", sort_order="oldest") == "ORDER BY created_at ASC"


def test_no_sort_by_emits_no_order_clause():
    """Without a field to sort on there is no ORDER BY to give a direction to."""
    assert order_limit_start() == ""
    assert order_limit_start(sort_order="desc") == ""
    assert order_limit_start(sort_order=None, limit=10) == "LIMIT 10"


def test_limit_and_start_clauses_are_unchanged():
    """The rest of the clause builder is untouched by this change."""
    assert order_limit_start(sort_by="created_at", limit=10) == "ORDER BY created_at DESC LIMIT 10"
    assert order_limit_start(sort_by="created_at", sort_order="asc", limit=10, page=3) == (
        "ORDER BY created_at ASC LIMIT 10 START 20"
    )
    assert order_limit_start(limit=10, page=1) == "LIMIT 10 START 0"
