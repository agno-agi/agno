"""Inspect a team run's checkpoint timeline via the new HTTP endpoints.

Two GET endpoints, mirroring the agent variants:

- ``GET /teams/{team_id}/runs/{run_id}/checkpoints?session_id=...``
  Returns the list of message boundaries derived from the persisted team run.

- ``GET /teams/{team_id}/runs/{run_id}/checkpoints/{message_index}?session_id=...``
  Returns a truncated snapshot at the chosen boundary. Use the
  ``message_index`` from the timeline as ``continue_from=K`` when resuming.

This cookbook runs an AgentOS in-process via ``fastapi.testclient.TestClient``
so it's self-contained — no separate server, no port binding.
"""

import json
import time

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.team import Team
from fastapi.testclient import TestClient

DB_FILE = f"tmp/team_checkpoint_endpoints_{int(time.time())}.db"


def get_population(city: str) -> str:
    """Mock population lookup."""
    data = {"Paris": "2.1M", "Tokyo": "13.9M", "Lagos": "15.3M"}
    return data.get(city, "unknown")


def main() -> None:
    pop_agent = Agent(
        name="pop-agent",
        role="Answers population questions.",
        model=OpenAIResponses(id="gpt-5.4"),
        tools=[get_population],
        db=SqliteDb(session_table="team_endpoints", db_file=DB_FILE),
    )
    team = Team(
        id="pop-team",
        name="pop-team",
        model=OpenAIResponses(id="gpt-5.4"),
        members=[pop_agent],
        db=SqliteDb(session_table="team_endpoints", db_file=DB_FILE),
        instructions="Delegate population questions and summarize.",
        checkpoint="steps",
    )

    agent_os = AgentOS(description="team-checkpoint-endpoints demo", teams=[team])
    app = agent_os.get_app()
    client = TestClient(app)

    # 1. Drive a team run that delegates to a member and produces a couple
    #    of tool batches.
    run = team.run(
        input="Compare the populations of Paris, Tokyo, and Lagos in one sentence.",
        session_id="team-sess-endpoints",
    )
    print("Created team run")
    print("  run_id:    ", run.run_id)
    print("  session_id:", run.session_id)
    print("  messages:  ", len(run.messages or []))
    print()

    # 2. GET /checkpoints — the FE-friendly timeline.
    timeline = client.get(
        f"/teams/{team.id}/runs/{run.run_id}/checkpoints",
        params={"session_id": run.session_id},
    )
    print(f"GET /teams/{team.id}/runs/{run.run_id}/checkpoints")
    print(f"  status: {timeline.status_code}")
    print("  body:")
    print(json.dumps(timeline.json(), indent=2, default=str))
    print()

    # 3. Pick the first non-terminal boundary and fetch the derived snapshot.
    checkpoints = timeline.json()["checkpoints"]
    interior = [c for c in checkpoints if not c.get("is_latest")]
    if interior:
        target = interior[0]
        snapshot_idx = target["message_index"]
        snap = client.get(
            f"/teams/{team.id}/runs/{run.run_id}/checkpoints/{snapshot_idx}",
            params={"session_id": run.session_id},
        )
        print(f"GET /teams/{team.id}/runs/{run.run_id}/checkpoints/{snapshot_idx}")
        print(f"  status: {snap.status_code}")
        payload = snap.json()
        print("  checkpoint metadata:")
        print(json.dumps(payload["checkpoint"], indent=2, default=str))
        print(
            f"  snapshot.messages: {len(payload['snapshot'].get('messages') or [])} (truncated)"
        )
        print(
            f"  snapshot.tools:    {len(payload['snapshot'].get('tools') or [])} (only those referenced)"
        )
        print()

        # 4. Plug the same message_index back into /continue.
        cont = client.post(
            f"/teams/{team.id}/runs/{run.run_id}/continue",
            data={
                "session_id": run.session_id,
                "continue_from": str(snapshot_idx),
                "input": "Actually, just Paris.",
                "stream": "false",
            },
        )
        print(
            f"POST /teams/{team.id}/runs/{run.run_id}/continue (continue_from={snapshot_idx})"
        )
        print(f"  status: {cont.status_code}")
        if cont.status_code == 200:
            body = cont.json()
            print(f"  new run_id:               {body.get('run_id')}")
            print(f"  forked_from_run_id:       {body.get('forked_from_run_id')}")
            print(
                f"  forked_from_message_index:{body.get('forked_from_message_index')}"
            )
    else:
        print("(No interior checkpoints found — the team run had a single turn.)")


if __name__ == "__main__":
    main()
