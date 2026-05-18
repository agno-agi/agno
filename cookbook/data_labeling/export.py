"""
Export labeled sessions from SQLite to flat JSONL for downstream warehouse load.

The cookbook stores one workflow session per invoice; the runs column inside
each session is JSONB with the full history (both labelers, reviewer report,
optional adjudication). For a warehouse-shaped export, we flatten:

    one row per invoice = (
        session_id,
        source_path,
        source_hash,
        labeler_a_model, labeler_b_model,
        schema_version, pipeline_version,
        final_invoice (the adjudicated FinalLabel.invoice if present,
                       otherwise Labeler A's result),
        labeler_a_invoice,
        labeler_b_invoice,
        disagreement_count,
        adjudicated,
        created_at,
    )

This is intentionally a "good enough for a demo" exporter. For production
you would replace the SqliteDb with PostgresDb and use a CDC tool
(Fivetran, Airbyte, Debezium) to stream into Snowflake / BigQuery / etc.

Usage:
    python cookbook/data_labeling/export.py [--db tmp/labeling.db] [--out tmp/labels.jsonl]
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# Make sibling modules importable when this file is run as a script.
sys.path.insert(0, str(Path(__file__).parent))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _content_of(run: Dict[str, Any]) -> Any:
    """Pull the content payload off a run dict; tolerate string or dict shape."""
    content = run.get("content")
    if isinstance(content, str):
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return content
    return content


def _find_step_output(run: Dict[str, Any], step_name: str) -> Optional[Any]:
    """
    Walk the workflow run record to find a step's content by name.

    Workflow runs store step outputs under `step_responses` (list) or similar;
    the exact key has moved across Agno versions, so we probe a few options.
    """
    for key in ("step_responses", "steps", "step_outputs"):
        steps = run.get(key)
        if not isinstance(steps, list):
            continue
        for s in steps:
            if isinstance(s, dict) and s.get("step_name") == step_name:
                return _content_of(s)
    return None


def _flatten_session(row: sqlite3.Row) -> Dict[str, Any]:
    session_id = row["session_id"]
    metadata = json.loads(row["metadata"]) if row["metadata"] else {}
    runs = json.loads(row["runs"]) if row["runs"] else []

    # Use the most recent run for this session.
    run = runs[-1] if runs else {}
    created_at = run.get("created_at")

    labeler_a = _find_step_output(run, "Labeler A") or {}
    labeler_b = _find_step_output(run, "Labeler B") or {}
    reviewer = _find_step_output(run, "Reviewer") or {}
    adjudicator = _find_step_output(run, "Adjudicator")

    a_invoice = (labeler_a or {}).get("invoice")
    b_invoice = (labeler_b or {}).get("invoice")
    disagreements: List[Any] = (reviewer or {}).get("disagreements") or []

    if adjudicator:
        final_invoice = adjudicator.get("invoice")
        adjudicated = True
    else:
        final_invoice = a_invoice
        adjudicated = False

    return {
        "session_id": session_id,
        "source_path": metadata.get("source_path"),
        "source_hash": metadata.get("source_hash"),
        "labeler_a_model": metadata.get("labeler_a_model"),
        "labeler_b_model": metadata.get("labeler_b_model"),
        "schema_version": metadata.get("schema_version"),
        "pipeline_version": metadata.get("pipeline_version"),
        "final_invoice": final_invoice,
        "labeler_a_invoice": a_invoice,
        "labeler_b_invoice": b_invoice,
        "disagreement_count": len(disagreements),
        "adjudicated": adjudicated,
        "created_at": created_at,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def export(db_path: Path, out_path: Path) -> None:
    if not db_path.exists():
        raise SystemExit(f"DB not found: {db_path}. Run run_batch.py first.")

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    rows = conn.execute(
        "SELECT session_id, metadata, runs FROM labeling_sessions ORDER BY session_id"
    ).fetchall()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with out_path.open("w") as fh:
        for row in rows:
            record = _flatten_session(row)
            fh.write(json.dumps(record, default=str) + "\n")
            written += 1

    print(f"Wrote {written} rows to {out_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Flatten labeling sessions to JSONL.")
    parser.add_argument(
        "--db",
        default="cookbook/data_labeling/tmp/labeling.db",
        help="Path to the SQLite database (default: cookbook/data_labeling/tmp/labeling.db)",
    )
    parser.add_argument(
        "--out",
        default="cookbook/data_labeling/tmp/labels.jsonl",
        help="Output JSONL path (default: cookbook/data_labeling/tmp/labels.jsonl)",
    )
    args = parser.parse_args()

    export(Path(args.db), Path(args.out))
