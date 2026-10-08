"""
Compact a Session over REST
===========================

Drive compaction from the AgentOS API rather than from Python: hold a conversation
over /runs, fold it with /compact, and confirm the stored transcript is untouched.

    POST /agents/{agent_id}/sessions/{session_id}/compact

For a session that exists, the route answers 200 with a status, because declining to
compact is a normal outcome rather than a failure (a session that does not exist is a
404, as on the other session routes). A summary costs a few hundred tokens whatever it
replaces, so folding a span smaller than that would leave the context BIGGER - which
is why the server declines instead of obeying:

    compacted         the fold happened; "record" carries the token counts
    not_worth_it      with enforce_min_fold_ratio=True: the span is too small to pay for its summary
    nothing_to_fold   the kept tail covers the whole conversation
    already_compacted a previous fold already covers everything foldable
    no_history        the session exists but has no stored history yet
    not_enabled       compaction is not configured on this agent
    summary_failed    the summarizer returned nothing

A UI branches on "compacted" and shows "message" verbatim.

Prerequisites: compaction_os.py running on http://localhost:7777
Run: .venvs/demo/bin/python cookbook/05_agent_os/28_compaction/rest_api_compaction.py
The script compacts twice at the end: the second call reports already_compacted.
"""

import os
from typing import Any
from uuid import uuid4

import httpx

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
BASE_URL = os.getenv("AGENT_OS_BASE_URL", "http://localhost:7777")
# The agent with no automatic trigger, so every fold here is one this script asked
# for. Point this at "compaction-agent" instead to watch the two paths interleave.
AGENT_ID = "manual-compaction-agent"

# Enough long answers that there is a real span to fold in front of the kept tail.
# Asking for detail is what makes them long.
QUESTIONS = [
    "Explain database indexing in detail, with worked examples.",
    "Explain B-tree indexes in depth and when they are the right choice.",
    "Explain hash indexes and how they differ, in detail.",
    "Explain covering indexes and index-only scans, in detail.",
    "Explain partial and filtered indexes in detail, with examples.",
    "Explain when an index hurts more than it helps, in detail.",
]


# ---------------------------------------------------------------------------
# API Helpers
# ---------------------------------------------------------------------------
def ask(client: httpx.Client, session_id: str, message: str) -> None:
    """One non-streaming turn."""
    response = client.post(
        f"/agents/{AGENT_ID}/runs",
        data={"message": message, "session_id": session_id, "stream": "false"},
    )
    response.raise_for_status()


def compact(client: httpx.Client, session_id: str) -> dict[str, Any]:
    """Fold this session's history now, and report what the server decided."""
    response = client.post(f"/agents/{AGENT_ID}/sessions/{session_id}/compact")
    if response.status_code == 404:
        # Not a decline: there is no such session to fold.
        return {"status": "404", "message": response.json().get("detail", "Not found")}
    response.raise_for_status()
    return response.json()


def show(result: dict[str, Any]) -> None:
    print(f"  status : {result['status']}")
    print(f"  message: {result['message']}")
    record = result.get("record")
    if record:
        print(
            f"  tokens : {record['tokens_before']} -> {record['tokens_after']} "
            f"({record['messages_compacted']} messages folded)"
        )


def stored_turn_count(client: httpx.Client, session_id: str) -> int:
    """User and assistant messages the session still holds, whatever compaction did.

    chat_history skips system and tool roles, so this is a count of conversation turns
    rather than of every stored message - enough to show the transcript is intact.
    """
    response = client.get(f"/sessions/{session_id}", params={"type": "agent"})
    if response.status_code == 404:
        # The session is only created by the first run, so before that there is
        # nothing to count rather than an error.
        return 0
    response.raise_for_status()
    return len(response.json().get("chat_history") or [])


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
def main() -> None:
    session_id = f"compaction-rest-{uuid4().hex[:8]}"

    with httpx.Client(base_url=BASE_URL, timeout=300.0) as client:
        print(f"Session: {session_id}\n")

        # 1. The session is only created by the first run, so compacting it now is a 404 -
        #    an error, unlike the declines below, which are normal outcomes.
        print("Compacting a session that does not exist yet:")
        show(compact(client, session_id))

        # 2. Build up a conversation worth folding. The questions all run first, so
        #    there is one sizeable span to fold rather than a small fold per turn.
        print("\nAsking questions...")
        for question in QUESTIONS:
            print(f"  - {question}")
            ask(client, session_id, question)

        before = stored_turn_count(client, session_id)

        # 3. Fold it. This agent has compact_at_tokens=None, so nothing folds unless
        #    asked - which makes the result below entirely this call's doing.
        print("\nCompacting:")
        result = compact(client, session_id)
        show(result)

        # 4. Compaction shortens the request, never the record - but that is only
        #    worth asserting when a fold actually happened.
        after = stored_turn_count(client, session_id)
        print(f"\nStored turns: {before} before, {after} after")
        if not result["compacted"]:
            if result["status"] == "already_compacted":
                print("  The server had already folded this session on its own.")
            else:
                print("  Nothing was folded, so there is nothing to compare.")
                print("  Ask more questions, or lower uncompacted_runs on the server.")
            return
        if before == after:
            print(
                "  The transcript is unchanged - only what is sent to the model got shorter."
            )

        # 5. Immediately again: the previous fold already covers everything
        #    foldable, and nothing new has been said since.
        print("\nCompacting again straight away:")
        show(compact(client, session_id))


if __name__ == "__main__":
    main()
