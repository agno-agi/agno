import pytest

from agno.db.gcs_json import GcsJsonDb
from agno.db.json import JsonDb
from agno.tracing.schemas import Span, Trace


def test_json_db_round_trips_non_ascii_content(tmp_path):
    db = JsonDb(db_path=str(tmp_path))
    rows = [{"id": "unicode", "content": "Olá, 世界", "emoji": "✅"}]

    db._write_json_file("unicode_rows", rows)

    assert db._read_json_file("unicode_rows") == rows


@pytest.mark.parametrize("db_class", [JsonDb, GcsJsonDb])
def test_trace_reads_respect_zero_limits_and_default_page(db_class, monkeypatch):
    db = object.__new__(db_class)
    db.trace_table_name = "traces"
    db.span_table_name = "spans"
    timestamp = "2026-01-01"
    traces = [
        {"trace_id": str(i), "session_id": str(i), "start_time": timestamp, "created_at": timestamp} for i in range(3)
    ]
    spans = [{"span_id": "span", "trace_id": "0"}]
    db._read_json_file = lambda table, **_: traces if table == "traces" else spans
    monkeypatch.setattr(Trace, "from_dict", staticmethod(lambda row: row))
    monkeypatch.setattr(Span, "from_dict", staticmethod(lambda row: row))

    for query in (db.get_traces, db.get_trace_stats):
        rows, total = query(limit=1, page=None)
        assert (len(rows), total) == (1, 3)
        rows, total = query(limit=1, page=0)
        assert (len(rows), total) == (1, 3)
        rows, total = query(limit=0)
        assert (rows, total) == ([], 3)
    assert db.get_spans(limit=0) == []
