"""
Custom AuditSink - ship the audit trail wherever you keep your security events

(New to this? Read 05_managed_roles_audit.py first: it shows the two trails and the
`audit=True` switch that writes both to your database.)

`audit=True` stores the change trail and the decision trail in two tables in the object's
database. If your security events belong somewhere else (a SIEM, an append-only log, a
message queue, a file you rotate), hand `Authorization(audit=...)` your own AuditSink instead.
One class, one method:

    class MySink(AuditSink):
        def record(self, event: AuditEvent) -> None: ...

Every event on BOTH trails comes through it:

  - changes    role.set_scopes / role.removed / user.assigned / user.unassigned, with the
               acting admin (`actor`), the `target`, and a before/after diff;
  - decisions  access.allowed / access.denied for every protected request, with the caller
               as `actor`, "METHOD /path" as `target`, and metadata holding the scopes the
               route required and a NON-secret reference to the token (its jti or a short
               hash, never the token itself).

`record` must never raise into the request path; agno catches and logs a failing sink, but
a sink that swallows its own errors keeps the log clean. The async request path calls
`arecord`, whose default runs `record` in a worker thread, so a sync sink is enough.

Reading back: `authz.audit_log()` and `authz.decisions()` read from the database sink. A custom
sink owns its own storage, so it owns its own reads too (this one tails its file).

This file writes both trails as JSON lines to tmp/authz_audit.jsonl, makes a few changes and
requests, then prints the file. No server and no model key needed.

Run it:
    pip install "agno[os]"
    python 10_custom_audit_sink.py
"""

import json
import os
from datetime import UTC, datetime, timedelta

import jwt
from agno.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.os import AgentOS
from agno.os.authz import AuditEvent, AuditSink, Authorization

SECRET = "custom-audit-sink-demo-secret-at-least-256-bits-long-x"
OS_ID = "custom-audit-sink-os"
AUDIT_FILE = "tmp/authz_audit.jsonl"


# ---------------------------------------------------------------------------
# The whole integration: implement AuditSink.record.
# ---------------------------------------------------------------------------


class JsonLinesAuditSink(AuditSink):
    """Append every event as one JSON line. Swap the body for your SIEM client, a queue
    producer, or an HTTP call; the shape of `event.to_dict()` is what you ship."""

    def __init__(self, path: str) -> None:
        self._path = path

    def record(self, event: AuditEvent) -> None:
        try:
            with open(self._path, "a", encoding="utf-8") as f:
                f.write(json.dumps(event.to_dict()) + "\n")
        except OSError as exc:  # never let audit failures reach the caller's request
            print(f"audit sink failed: {exc}")

    # arecord() is inherited: it runs record() in a worker thread on the async path.

    def tail(self):
        with open(self._path, encoding="utf-8") as f:
            return [json.loads(line) for line in f]


def token(sub: str) -> dict:
    t = jwt.encode(
        {
            "sub": sub,
            "aud": OS_ID,
            "scopes": [],
            "exp": datetime.now(UTC) + timedelta(hours=1),
        },
        SECRET,
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {t}"}


def main() -> None:
    sink = JsonLinesAuditSink(AUDIT_FILE)

    # audit=<your sink> is the same single switch as audit=True: both trails, one sink.
    authz = Authorization(
        db_url="sqlite:///tmp/custom_audit_sink.db",
        verification_keys=[SECRET],
        algorithm="HS256",
        verify_audience=True,
        audience=OS_ID,
        audit=sink,
    )

    # --- changes (each lands in the file with the actor) ---
    authz.define_role("viewer", ["agents:*:read"])
    authz.set_role_scopes(
        "viewer", ["agents:*:read", "agents:research-agent:run"], actor="alice"
    )
    authz.set_role("bob", "viewer", actor="alice")

    # --- decisions (each protected request lands in the file, allow or deny) ---
    from fastapi.testclient import TestClient

    agent = Agent(id="research-agent", name="Research Agent", db=InMemoryDb())
    agent_os = AgentOS(id=OS_ID, agents=[agent], authorization=authz)
    client = TestClient(agent_os.get_app())
    client.get(
        "/agents/research-agent", headers=token("bob")
    )  # allowed (viewer can read)
    client.post(
        "/agents/research-agent/runs", headers=token("nobody"), data={"message": "hi"}
    )  # denied

    print(f"\n=== {AUDIT_FILE}: both trails, one line per event ===")
    for e in sink.tail():
        kind = "DECISION" if e["action"].startswith("access.") else "CHANGE  "
        extra = (
            e.get("metadata", {}).get("required")
            if kind == "DECISION"
            else f"{e.get('before')} -> {e.get('after')}"
        )
        print(
            f"  {kind}  {str(e['actor'] or 'system'):>6}  {e['action']:<16} {e['target']:<28} {extra}"
        )

    print(
        "\nA custom sink owns its storage, so authz.audit_log() / authz.decisions() are for the db sink:"
    )
    print(f"  authz.decisions() -> {authz.decisions()}")


if __name__ == "__main__":
    os.makedirs("tmp", exist_ok=True)
    for path in (AUDIT_FILE, "tmp/custom_audit_sink.db"):
        if os.path.exists(path):
            os.remove(path)
    main()
