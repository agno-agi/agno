"""Inspect a run's checkpoint timeline via the new HTTP endpoints.

Two GET endpoints expose checkpoint boundaries derived from the persisted run
(no separate checkpoint table — entries are inferred from message-level
markers + the terminal end of the transcript):

- ``GET /agents/{agent_id}/runs/{run_id}/checkpoints?session_id=...``
  Returns the list of message boundaries a UI can show as resume points.

- ``GET /agents/{agent_id}/runs/{run_id}/checkpoints/{message_index}?session_id=...``
  Returns a derived run snapshot truncated at that boundary. Use the
  ``message_index`` from the timeline as ``continue_from=K`` when resuming.

This cookbook runs an AgentOS in-process via ``fastapi.testclient.TestClient``
so the example is self-contained — no separate server, no port binding.
"""

import json

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from fastapi.testclient import TestClient


def get_population(city: str) -> str:
    """Mock population lookup."""
    data = {"Paris": "2.1M", "Tokyo": "13.9M", "Lagos": "15.3M"}
    return data.get(city, "unknown")


def main() -> None:
    agent = Agent(
        id="travel-agent",
        name="travel-agent",
        model=OpenAIResponses(id="gpt-5.4"),
        db=SqliteDb(
            session_table="checkpoint_endpoints_demo",
            db_file="tmp/checkpoint_endpoints.db",
        ),
        checkpoint="tool-batch",
        tools=[get_population],
    )

    agent_os = AgentOS(description="checkpoint-endpoints demo", agents=[agent])
    app = agent_os.get_app()
    client = TestClient(app)

    # 1. Drive a run that produces a few tool batches so the timeline has
    #    real checkpoints to show. Each tool batch writes a checkpoint
    #    marker on the boundary message.
    run = agent.run(
        input="Compare the populations of Paris, Tokyo, and Lagos in one sentence.",
    )
    print("Created run")
    print("  run_id:    ", run.run_id)
    print("  session_id:", run.session_id)
    print("  messages:  ", len(run.messages or []))
    print()

    # 2. GET /checkpoints — the FE-friendly timeline.
    timeline = client.get(
        f"/agents/{agent.id}/runs/{run.run_id}/checkpoints",
        params={"session_id": run.session_id},
    )
    print(f"GET /agents/{agent.id}/runs/{run.run_id}/checkpoints")
    print(f"  status: {timeline.status_code}")
    print("  body:")
    print(json.dumps(timeline.json(), indent=2, default=str))
    print()

    # 3. Pick a non-terminal boundary from the timeline and fetch the
    #    derived snapshot at that index. A snapshot is a truncated copy of
    #    the persisted run — the stored row is NOT mutated.
    checkpoints = timeline.json()["checkpoints"]
    interior = [c for c in checkpoints if not c.get("is_latest")]
    if interior:
        target = interior[0]
        snapshot_idx = target["message_index"]
        snap = client.get(
            f"/agents/{agent.id}/runs/{run.run_id}/checkpoints/{snapshot_idx}",
            params={"session_id": run.session_id},
        )
        print(f"GET /agents/{agent.id}/runs/{run.run_id}/checkpoints/{snapshot_idx}")
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

        # 4. The returned message_index plugs directly into /continue.
        #    Show how a UI would use it: list checkpoints, let the user pick
        #    one, resume from there.
        cont = client.post(
            f"/agents/{agent.id}/runs/{run.run_id}/continue",
            data={
                "session_id": run.session_id,
                "continue_from": str(snapshot_idx),
                "input": "Actually, just tell me about Paris.",
                "stream": "false",
            },
        )
        print(
            f"POST /agents/{agent.id}/runs/{run.run_id}/continue (continue_from={snapshot_idx})"
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
        print("(No interior checkpoints found — the run had a single turn.)")
        print("Try a multi-tool prompt to populate the timeline with more boundaries.")


if __name__ == "__main__":
    main()
