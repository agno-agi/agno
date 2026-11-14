from datetime import datetime, timezone

from agno.db.json import JsonDb
from agno.tracing.schemas import Trace


def test_json_db_round_trips_non_ascii_content(tmp_path):
    db = JsonDb(db_path=str(tmp_path))
    rows = [{"id": "unicode", "content": "Olá, 世界", "emoji": "✅"}]

    db._write_json_file("unicode_rows", rows)

    assert db._read_json_file("unicode_rows") == rows


def test_json_db_trace_reads_apply_limit_without_page(tmp_path):
    db = JsonDb(db_path=str(tmp_path))
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for i in range(3):
        db.upsert_trace(
            Trace(
                trace_id=str(i),
                name="Agent.run",
                status="OK",
                start_time=now,
                end_time=now,
                duration_ms=0,
                total_spans=0,
                error_count=0,
                run_id=str(i),
                session_id=str(i),
                user_id="user",
                agent_id="agent",
                team_id=None,
                workflow_id=None,
                created_at=now,
            )
        )

    traces, total = db.get_traces(limit=1, page=None)
    assert (len(traces), total) == (1, 3)

    stats, total = db.get_trace_stats(limit=1, page=None)
    assert (len(stats), total) == (1, 3)
