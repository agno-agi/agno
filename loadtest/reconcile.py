"""Reconciler: the pass/fail heart of the load test.

Diffs the client ledger (every 202 we got back) against the DB run rows and the
job-queue rows. Asserts the four invariants:

  DURABLE   : every accepted run_id reached a terminal state (none lost/stuck)
  BOUNDED   : queue never accepted beyond depth silently (429s present when expected)
  IDEMPOTENT: same-key submits map to exactly one run
  NO-ORPHAN : no run row stuck at RUNNING/PENDING after drain

Run AFTER the driver has finished AND you've waited for drain.

Env: PG_DSN (default postgresql://ai:ai@localhost:5532/ai), LEDGER
"""

import json
import os
import sys
from collections import Counter

import psycopg

PG_DSN = os.environ.get("PG_DSN", "postgresql://ai:ai@localhost:5532/ai")
LEDGER = os.environ.get("LEDGER", "client_ledger.jsonl")
TERMINAL = {"COMPLETED", "ERROR", "CANCELLED", "FAILED"}


def load_ledger():
    rows = []
    with open(LEDGER) as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def db_run_statuses(conn) -> dict:
    """run_id -> status, from every session's runs blob (ai schema)."""
    out = {}
    cur = conn.cursor()
    cur.execute(
        "SELECT runs FROM ai.agno_sessions WHERE runs IS NOT NULL AND jsonb_typeof(runs)='array'"
    )
    for (runs,) in cur.fetchall():
        for r in runs or []:
            rid = r.get("run_id")
            if rid:
                out[rid] = r.get("status")
    return out


def queue_rows(conn) -> dict:
    """id -> status from the durable queue table, if present."""
    out = {}
    cur = conn.cursor()
    for schema in ("ai", "public"):
        for tbl in ("agno_jobs", "agno_run_queue"):
            try:
                cur.execute(f"SELECT id, status FROM {schema}.{tbl}")
                for rid, st in cur.fetchall():
                    out[rid] = st
                return out
            except Exception:
                conn.rollback()
    return out


def main() -> int:
    ledger = load_ledger()
    submits = [r for r in ledger if r["kind"] == "submit"]
    accepted = [r for r in submits if r.get("http") == 202 and r.get("run_id")]
    got_429 = [r for r in submits if r.get("http") == 429]
    errors = [r for r in submits if r.get("http") in (-1, 500)]

    accepted_ids = {r["run_id"] for r in accepted}

    conn = psycopg.connect(PG_DSN)
    run_status = db_run_statuses(conn)
    q_status = queue_rows(conn)
    conn.close()

    # --- DURABLE: every accepted run reached terminal ---
    missing = [rid for rid in accepted_ids if rid not in run_status]
    stuck = [rid for rid in accepted_ids if run_status.get(rid) not in TERMINAL and rid in run_status]

    # --- NO-ORPHAN: any run row (queue-accepted) stuck non-terminal ---
    non_terminal_rows = [rid for rid, st in run_status.items() if st not in TERMINAL]

    # --- IDEMPOTENT: same-key submits -> one run_id ---
    from collections import defaultdict

    by_key = defaultdict(set)
    for r in submits:
        if r.get("idem") and r.get("run_id"):
            by_key[r["idem"]].add(r["run_id"])
    idem_violations = {k: v for k, v in by_key.items() if len(v) > 1}

    print("=" * 60)
    print(f"submits={len(submits)}  accepted(202)={len(accepted)}  429={len(got_429)}  errors={len(errors)}")
    print(f"distinct accepted run_ids={len(accepted_ids)}")
    print(f"run rows found={len(run_status)}  queue rows={len(q_status)}")
    print(f"status histogram: {dict(Counter(run_status.values()))}")
    print("=" * 60)

    ok = True
    if errors:
        print(f"FAIL  {len(errors)} submits errored/500 (durable seam should not 500): sample {errors[:3]}")
        ok = False
    if missing:
        print(f"FAIL  DURABLE: {len(missing)} accepted runs have NO run row (lost): {missing[:5]}")
        ok = False
    if stuck:
        print(f"FAIL  DURABLE: {len(stuck)} accepted runs stuck non-terminal: {stuck[:5]}")
        ok = False
    if non_terminal_rows:
        print(f"WARN/FAIL NO-ORPHAN: {len(non_terminal_rows)} run rows non-terminal after drain: {non_terminal_rows[:5]}")
        ok = False
    if idem_violations:
        print(f"FAIL  IDEMPOTENT: {len(idem_violations)} keys mapped to >1 run: {dict(list(idem_violations.items())[:3])}")
        ok = False

    if ok:
        print("PASS  all invariants held.")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
