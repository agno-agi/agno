"""RBAC + Per-User Knowledge Isolation + Admin Bypass.

Builds on ``user_isolation.py``. With ``AuthorizationConfig(user_isolation=True)``,
member callers are scoped to their own ``sub`` at the DB layer AND at the
vector-DB layer (per-user RAG isolation). This cookbook demonstrates the
admin-bypass that closes the Slack-thread gap:

    "Admin can see both member content in the Knowledge page, but on the
    Chat page can't access any member knowledge — is that intentional?"

It WAS, because the admin's run is correctly attributed to the admin
(sessions / traces / metrics keep admin ownership), and the same
``user_id`` flowed into vector-DB retrieval — so the admin only saw their
own uploads + the shared bucket. Now, when the JWT carries the configured
``admin_scope``, the agents/teams/workflows routers set an internal
RAG-scope override on ``RunContext.dependencies`` that promotes retrieval
to UNSCOPED (sees every user's chunks + shared) while session attribution
stays tied to the admin's own ``sub``.

How this cookbook runs:
  * Spins up the AgentOS in-process via ``fastapi.testclient.TestClient``
    — no real HTTP, no port races, no LLM cost beyond the one model call
    per scenario.
  * For each scenario (alice / bob / admin) it POSTs to /agents/.../runs
    and prints the ``references`` returned on the RunOutput. ``references``
    is the deterministic surface populated by ``search_knowledge_base``;
    the LLM's natural-language reply is shown separately for context but
    isn't asserted on.
  * Three contract checks run at the end so a regression shows up loudly.

Prerequisites:
  * Set JWT_VERIFICATION_KEY env var (or accept the default below for
    local testing only).
  * Postgres at ``postgresql+psycopg://ai:ai@localhost:5532/ai`` with
    pgvector. Run ``./cookbook/scripts/run_pgvector.sh`` from the repo
    root.
  * OPENAI_API_KEY in your environment.
"""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List

import jwt
from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.config import AuthorizationConfig
from agno.vectordb.pgvector import PgVector
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

JWT_SECRET = os.getenv("JWT_VERIFICATION_KEY", "your-secret-key-at-least-256-bits-long")
DB_URL = "postgresql+psycopg://ai:ai@localhost:5532/ai"
OS_ID = "my-agent-os"

db = PostgresDb(db_url=DB_URL)


# ---------------------------------------------------------------------------
# Seed the knowledge base with per-user + shared content.
#
# Idempotent on content_hash so re-running the cookbook is safe.
# ---------------------------------------------------------------------------


def _seed_knowledge(knowledge: Knowledge) -> None:
    alice_doc = Path("/tmp/alice_private.md")
    alice_doc.write_text(
        "# Alice's internal Q3 plan\n\n"
        "Alice is leading the migration of the billing service to "
        "event-sourced architecture. Target completion: 2026-09-15."
    )
    bob_doc = Path("/tmp/bob_private.md")
    bob_doc.write_text(
        "# Bob's onboarding runbook\n\n"
        "Bob owns the recruiter onboarding flow. New hires get a one-week "
        "shadow rotation with an existing recruiter."
    )
    shared_doc = Path("/tmp/company_handbook.md")
    shared_doc.write_text(
        "# Company handbook\n\n"
        "All employees observe a four-day workweek (Mon-Thu). Company "
        "all-hands runs every other Tuesday at 10:00 IST."
    )

    knowledge.insert(path=str(alice_doc), user_id="user-alice", skip_if_exists=True)
    knowledge.insert(path=str(bob_doc), user_id="user-bob", skip_if_exists=True)
    knowledge.insert(path=str(shared_doc), skip_if_exists=True)


vector_db = PgVector(table_name="rag_admin_bypass_demo", db_url=DB_URL)
knowledge = Knowledge(name="rag_admin_bypass_demo", vector_db=vector_db, contents_db=db)
_seed_knowledge(knowledge)

research_agent = Agent(
    id="research-agent",
    name="Research Agent",
    model=OpenAIResponses(id="gpt-5.4"),
    db=db,
    knowledge=knowledge,
    add_history_to_context=True,
    markdown=True,
)

# user_isolation=True turns on BOTH DB scoping (sessions/memory/traces)
# AND vector-DB scoping (RAG retrieval). The admin bypass added on top
# applies to the RAG path only — admins still keep their own session
# attribution.
agent_os = AgentOS(
    id=OS_ID,
    description="RBAC + Per-User RAG + Admin Bypass",
    agents=[research_agent],
    authorization=True,
    authorization_config=AuthorizationConfig(
        verification_keys=[JWT_SECRET],
        algorithm="HS256",
        user_isolation=True,
    ),
)

app = agent_os.get_app()


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------


def _mint(sub: str, scopes: List[str]) -> str:
    return jwt.encode(
        {
            "sub": sub,
            "aud": OS_ID,
            "scopes": scopes,
            "exp": datetime.now(UTC) + timedelta(hours=1),
            "iat": datetime.now(UTC),
        },
        JWT_SECRET,
        algorithm="HS256",
    )


_DOC_OWNER: Dict[str, str] = {
    "alice_private.md": "user-alice",
    "bob_private.md": "user-bob",
    "company_handbook.md": "shared",
}


def _retrieved_owners(payload: Dict[str, Any]) -> List[str]:
    """Map retrieved chunks back to the owner that uploaded them.

    The vector-DB layer stores ``user_id`` in a dedicated column for fast
    indexed filtering (see ``vectordb/pgvector/pgvector.py``) — it is NOT
    round-tripped into ``Document.meta_data`` when chunks come back out
    of search. The deterministic surface we have is the document
    ``name``, which is the filename we seeded with — and we know which
    file each owner uploaded, so a name → owner table is the cleanest
    way to assert visibility.

    Each ``references`` entry holds the RAG hits for a single
    ``search_knowledge_base`` call.
    """
    owners: List[str] = []
    for ref_group in payload.get("references") or []:
        for ref in ref_group.get("references") or []:
            name = ref.get("name") or ""
            base = name.rsplit("/", 1)[-1]
            owner = _DOC_OWNER.get(base)
            if owner is not None:
                owners.append(owner)
    return owners


def _run_scenario(
    client: TestClient,
    *,
    label: str,
    token: str,
    message: str,
) -> Dict[str, Any]:
    """POST a non-streaming run and print the model reply + retrieved owners.

    Returns the parsed RunOutput so the contract checks at the bottom can
    assert on it.
    """
    print(f"\n--- {label} ---")
    print(f"prompt: {message}")
    response = client.post(
        f"/agents/{research_agent.id}/runs",
        headers={"Authorization": f"Bearer {token}"},
        data={"message": message, "stream": "false"},
    )
    if response.status_code != 200:
        print(f"  HTTP {response.status_code}: {response.text[:300]}")
        return {}
    payload = response.json()
    print(f"  model reply: {(payload.get('content') or '')[:160].strip()}")
    owners = _retrieved_owners(payload)
    print(f"  RAG saw owners: {sorted(set(owners)) if owners else '(no chunks)'}")
    return payload


def main() -> int:
    if not os.getenv("OPENAI_API_KEY"):
        print("OPENAI_API_KEY not set — this cookbook runs against a real model.")
        return 1

    alice_token = _mint("user-alice", ["agents:read", "agents:run", "sessions:read"])
    bob_token = _mint("user-bob", ["agents:read", "agents:run", "sessions:read"])
    admin_token = _mint("admin-1", ["agent_os:admin"])

    print("=" * 60)
    print("RAG admin-bypass demo (in-process via TestClient)")
    print("=" * 60)

    client = TestClient(app)

    alice_self = _run_scenario(
        client,
        label="1. Alice asks about her own work",
        token=alice_token,
        message="What is the target completion date for the billing migration?",
    )
    alice_cross = _run_scenario(
        client,
        label="2. Alice asks about Bob's work (should find nothing of Bob's)",
        token=alice_token,
        message="Who owns the recruiter onboarding flow?",
    )
    _run_scenario(
        client,
        label="3. Bob asks about the shared handbook",
        token=bob_token,
        message="How many days is the company workweek?",
    )
    admin_alice = _run_scenario(
        client,
        label="4. ADMIN asks about Alice's work (bypass — should see it)",
        token=admin_token,
        message="What is the target completion date for the billing migration?",
    )
    admin_bob = _run_scenario(
        client,
        label="5. ADMIN asks about Bob's work (bypass — should see it)",
        token=admin_token,
        message="Who owns the recruiter onboarding flow?",
    )

    # ----------------------------------------------------------------------
    # Contract checks — the deterministic part of the demo.
    #
    # We assert on the *owners* of retrieved chunks, not on LLM phrasing.
    # This is the surface the bypass actually affects.
    # ----------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("Contract checks")
    print("=" * 60)

    failures: List[str] = []

    def check(name: str, condition: bool, detail: str = "") -> None:
        marker = "PASS" if condition else "FAIL"
        print(
            f"  [{marker}] {name}"
            + (f" — {detail}" if detail and not condition else "")
        )
        if not condition:
            failures.append(name)

    alice_self_owners = set(_retrieved_owners(alice_self))
    alice_cross_owners = set(_retrieved_owners(alice_cross))
    admin_alice_owners = set(_retrieved_owners(admin_alice))
    admin_bob_owners = set(_retrieved_owners(admin_bob))

    check(
        "Alice's own search retrieves only Alice + shared (no Bob)",
        "user-bob" not in alice_self_owners,
        detail=f"got owners={alice_self_owners}",
    )
    check(
        "Alice's cross-user search does NOT retrieve Bob's chunks",
        "user-bob" not in alice_cross_owners,
        detail=f"got owners={alice_cross_owners}",
    )
    check(
        "Admin asking about Alice's work DOES retrieve Alice's chunks (bypass works)",
        "user-alice" in admin_alice_owners,
        detail=f"got owners={admin_alice_owners}",
    )
    check(
        "Admin asking about Bob's work DOES retrieve Bob's chunks (bypass works)",
        "user-bob" in admin_bob_owners,
        detail=f"got owners={admin_bob_owners}",
    )

    # Session attribution: admin's runs must NOT show up under alice/bob's
    # sessions. This proves the bypass is scoped to RAG retrieval and not
    # leaking into the data-isolation layer.
    sessions_resp = client.get(
        "/sessions?type=agent",
        headers={"Authorization": f"Bearer {alice_token}"},
    )
    alice_visible_user_ids: set[str] = set()
    if sessions_resp.status_code == 200:
        for sess in sessions_resp.json().get("data") or []:
            uid = sess.get("user_id")
            if uid:
                alice_visible_user_ids.add(uid)
    check(
        "Admin's runs do NOT appear in Alice's /sessions list",
        "admin-1" not in alice_visible_user_ids,
        detail=f"got user_ids={alice_visible_user_ids}",
    )

    print("\n" + "=" * 60)
    if failures:
        print(f"FAILED: {len(failures)} contract check(s) — {failures}")
        return 1
    print("All contract checks passed.")
    print("=" * 60 + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())


# Local-dev convenience: if you'd rather poke at this via real HTTP / Studio,
# replace ``main()`` above with::
#
#     agent_os.serve(app="knowledge_admin_bypass:app", port=7777, reload=True)
#
# and curl the endpoints. Tokens to mint look like::
#
#     jwt.encode({"sub": "user-alice", "aud": "my-agent-os",
#                 "scopes": ["agents:read","agents:run"], ...}, JWT_SECRET)
