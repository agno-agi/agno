"""Two turns of one session on Vercel Sandbox microVMs. This creates billable compute.

Install the extra, sign in to Vercel, and build an Agno wheel from this checkout (the computer
installs Agno from it and refuses to run unless its source matches yours):

    uv pip install "agno[vercel-sandbox]"
    (cd libs/agno && uv build --wheel)
    .venv/bin/python cookbook/frameworks/sandbox/vercel/vercel_session.py --wheel libs/agno/dist/agno-*.whl

Credentials come from the Vercel SDK: OIDC (for example after `vercel env pull`), or VERCEL_TOKEN with
VERCEL_TEAM_ID and VERCEL_PROJECT_ID. They stay on this machine and never enter the computer. The default
fixture harness makes no model calls. --harness claude forwards ANTHROPIC_API_KEY or
CLAUDE_CODE_OAUTH_TOKEN and --harness codex forwards OPENAI_API_KEY into the computer; both check that
turn 2 recalls a codeword only the conversation from turn 1 holds.

--mode public (the default) is a sandboxed agent with a database, as in production. The first turn
creates a computer; the coordinator then keeps it running for 300 seconds, so the second turn reuses it
(metadata.sandbox.resumed is True) with nothing restored. A computer kept like this keeps running, and is
billed, until the next turn claims it, a sweep retires it, or its lifetime ends; this example retires it
when it finishes. Public mode needs Postgres: ./cookbook/scripts/run_pgvector.sh.

--mode direct drives the runtime client by hand. Turn 2 finds the same computer with create. With
--replace, turn 1 is checkpointed, the computer destroyed, and turn 2 runs on generation 2 restored from
the checkpoint, the path a session takes once its computer is gone.
"""

import argparse
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from agno.sandbox.checkpoint import FileCheckpointStore
from agno.sandbox.client import SandboxRuntimeClient
from agno.sandbox.vercel import VercelCheckpointTransfer, VercelSandbox

CODEWORD_TURNS = [
    "Remember the codeword BLUE-HERON, but do not write it to any file. "
    "Create primes.py that prints the first 10 primes, run it, and report the output.",
    "What codeword did I ask you to remember? Then add test_primes.py for primes.py, "
    "run it with python, and report the result.",
]


def run_turn(client, computer, number, harness, prompt, config):
    execution = client.start(
        computer,
        execution_id=f"turn-{number}",
        run_id=f"turn-{number}",
        sdk=harness,
        input=prompt,
        config=config,
        execution_timeout=600,
    )
    result = None
    for page in client.pages(execution, timeout=900):
        result = page.result
    assert result is not None and result["type"] == "execution_finished", result
    content = str(result["run"].get("content"))
    print(f"Turn {number}: {result['run']['status']}")
    print(content[:800])
    return content


def model_env(harness):
    """The variables a harness needs inside the computer: its model key, or the fixture switch."""
    if harness == "claude":
        keys = ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN")
        return {key: os.environ[key] for key in keys if key in os.environ}
    if harness == "codex":
        return {"OPENAI_API_KEY": os.environ["OPENAI_API_KEY"]}
    return {"AGNO_SANDBOX_TEST_RUNTIME": "1"}


def harness_settings(harness, model):
    """The environment and runtime configuration for a real harness, and its two turns."""
    env = model_env(harness)
    if harness == "claude":
        config = {
            "model": model or "claude-sonnet-4-6",
            "permission_mode": "acceptEdits",
            "allowed_tools": ["Read", "Write", "Edit", "Bash"],
        }
    else:
        # The computer is the isolation boundary, so Codex runs without its own nested sandbox.
        config = {"sandbox_mode": "full-access", "model": model or "gpt-5.5"}
    return env, config, CODEWORD_TURNS


def run_direct(args, wheel):
    if args.harness == "fixture":
        env, config = {"AGNO_SANDBOX_TEST_RUNTIME": "1"}, {}
        turns = ["Create a file", "Continue in the same session"]
    else:
        env, config, turns = harness_settings(args.harness, args.model)
    sandbox = VercelSandbox(
        namespace="vercel-example-" + uuid4().hex[:12], lifetime=1800, wheel=wheel
    )
    client = SandboxRuntimeClient(sandbox)
    identity = {"session_id": "example", "agent_id": "coder", "env": env}
    print("Creating the computer: it installs Agno and the harness SDKs first.")
    handles = [sandbox.create(**identity)]
    try:
        with TemporaryDirectory() as directory:
            transfer = VercelCheckpointTransfer(
                sandbox, FileCheckpointStore(Path(directory) / "objects")
            )
            run_turn(client, handles[0], 1, args.harness, turns[0], config)
            if args.replace:
                reference = transfer.capture(handles[0], state={"turn": 1})
                print(f"Checkpoint {reference.sha256[:12]}, {reference.size} bytes")
                sandbox.destroy(handles[0])
                handles.append(sandbox.create(**identity, generation=2))
                assert handles[1].provider_ref != handles[0].provider_ref
                assert transfer.restore(handles[1], reference) == {"turn": 1}
                print("Restored generation 2 on", handles[1].provider_ref)
            else:
                # A later request finds the same computer by its session and generation.
                assert (
                    sandbox.create(**identity).provider_ref == handles[0].provider_ref
                )
            content = run_turn(client, handles[-1], 2, args.harness, turns[1], config)
        listing = sandbox.exec(handles[-1], ["ls", "-1"]).stdout.split()
        print("Workspace after both turns:", listing)
        if args.harness != "fixture":
            assert "BLUE-HERON" in content, "Turn 2 lost the conversation"
            place = "a restored computer" if args.replace else "the same computer"
            print(f"Turn 2 recalled the codeword on {place}.")
    finally:
        # Try every cleanup and preserve the original work failure.
        failed = []
        for handle in handles:
            try:
                sandbox.destroy(handle)
            except Exception as error:
                failed.append(handle.provider_ref)
                print(
                    f"Could not destroy {handle.provider_ref}: {type(error).__name__}: {error}",
                    file=sys.stderr,
                )
            else:
                print("Destroyed", handle.provider_ref)
        if failed and sys.exc_info()[0] is None:
            raise RuntimeError("Could not destroy: " + ", ".join(failed))


def run_public(args, wheel):
    from agno.db.postgres import PostgresDb
    from agno.media import File, Image
    from agno.sandbox.coordinator import SandboxCoordinator
    from agno.sandbox.fixture import FixtureAgent

    db = PostgresDb(
        db_url=os.getenv(
            "AGNO_SANDBOX_DB_URL", "postgresql+psycopg://ai:ai@localhost:5532/ai"
        )
    )
    with TemporaryDirectory() as directory:
        checkpoints = FileCheckpointStore(Path(directory) / "objects")
        sandbox = VercelSandbox(
            namespace="vercel-example-" + uuid4().hex[:12],
            lifetime=1800,
            wheel=wheel,
            checkpoints=checkpoints,
            env=model_env(args.harness),
        )
        if args.harness == "fixture":
            agent = FixtureAgent(id="coder", db=db, sandbox=sandbox)
            turns = ["Create a file", "Continue in the same session"]
        elif args.harness == "claude":
            from agno.agents.claude import ClaudeAgent

            agent = ClaudeAgent(
                id="coder",
                model=args.model or "claude-sonnet-4-6",
                permission_mode="acceptEdits",
                allowed_tools=["Read", "Write", "Edit", "Bash"],
                db=db,
                sandbox=sandbox,
            )
            turns = CODEWORD_TURNS
        else:
            from agno.agents.codex import CodexAgent

            agent = CodexAgent(
                id="coder",
                model=args.model or "gpt-5.5",
                sandbox_mode="full-access",
                db=db,
                sandbox=sandbox,
            )
            turns = CODEWORD_TURNS
        session_id = "vercel-example-" + uuid4().hex[:8]
        media = {}
        if args.harness == "fixture":
            # Only bytes cross into the computer: an image and a file travel with the first turn.
            media = dict(
                images=[Image(content=b"\x89PNG-example", format="png")],
                files=[File(content=b"notes", filename="notes.txt")],
            )
        try:
            first = agent.run(turns[0], session_id=session_id, **media)
            print(
                "Turn 1:",
                first.status.value,
                "- resumed:",
                first.metadata["sandbox"]["resumed"],
            )
            print(str(first.content)[:800])
            second = agent.run(turns[1], session_id=session_id)
            print(
                "Turn 2:",
                second.status.value,
                "- resumed:",
                second.metadata["sandbox"]["resumed"],
            )
            print(str(second.content)[:800])
            if args.harness != "fixture":
                assert "BLUE-HERON" in str(second.content), (
                    "Turn 2 lost the conversation"
                )
        finally:
            # The computer turn 2 left warm keeps running, and billing, until something retires it.
            coordinator = SandboxCoordinator(
                db, sandbox, sandbox.checkpoint_transfer(checkpoints)
            )
            removed = coordinator.retire_computer(session_id, agent_id="coder")
            print(
                "Retired the warm computer."
                if removed
                else "No warm computer was left."
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--harness", choices=("fixture", "claude", "codex"), default="fixture"
    )
    parser.add_argument("--mode", choices=("public", "direct"), default="public")
    parser.add_argument("--model", help="Claude or OpenAI model for a real harness")
    parser.add_argument("--wheel", help="Agno wheel built from this checkout")
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Direct mode: run turn 2 on a new computer restored from a checkpoint",
    )
    args = parser.parse_args()
    if args.replace and args.mode != "direct":
        parser.error("--replace belongs to --mode direct")
    wheel = Path(args.wheel) if args.wheel else None
    (run_public if args.mode == "public" else run_direct)(args, wheel)


if __name__ == "__main__":
    main()
