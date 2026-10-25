"""Warm and cold turns, on Docker or AgentCore: see which path each turn takes and what it costs.

Credential-free: the fixture runtime stands in for Claude or Codex. Run Postgres and build the
runtime image, then:

    .venv/bin/python cookbook/frameworks/sandbox/warm_turns.py                       # Docker
    .venv/bin/python cookbook/frameworks/sandbox/warm_turns.py --provider agentcore  # needs AGENTCORE_RUNTIME_ARN

Four turns of one session. Turn 1 is cold: a new computer. Turn 2 resumes the computer turn 1
left warm, with nothing restored. Before turn 3 the warm window is shortened to a few seconds,
so turn 3 is still warm but its computer is only kept that long; after waiting past the window,
turn 4 is cold again: a fresh generation restored from turn 3's checkpoint, which the files it
sees prove. Each turn prints the path it took, how long it ran, its generation and the run's
``metadata.sandbox.resumed`` flag, which is what you would read in production. Create and
restore are counted on the provider and the transfer, so the path is not inferred from timing.
"""

import argparse
import asyncio
import os
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from agno.db.postgres import PostgresDb
from agno.sandbox.checkpoint import CheckpointRef, FileCheckpointStore
from agno.sandbox.coordinator import SandboxCoordinator

parser = argparse.ArgumentParser()
parser.add_argument("--provider", choices=["docker", "agentcore"], default="docker")
args = parser.parse_args()

db = PostgresDb(
    db_url=os.getenv(
        "AGNO_SANDBOX_DB_URL", "postgresql+psycopg://ai:ai@localhost:5532/ai"
    )
)
if args.provider == "docker":
    from agno.sandbox.docker import DockerSandbox

    sandbox = DockerSandbox(
        os.getenv("AGNO_SANDBOX_IMAGE", "agno-sandbox:local"),
        namespace="warm-turns",
        memory_mb=512,
    )
else:
    from agno.sandbox.agentcore import AgentCoreSandbox

    # The turn budget below must fit inside this lifetime for a computer to be resumed.
    sandbox = AgentCoreSandbox(
        os.environ["AGENTCORE_RUNTIME_ARN"], namespace="warm-turns", lifetime=1800
    )

session_id = "warm-turns-" + uuid4().hex[:8]
turn = dict(
    agent_id="coder",
    sdk="fixture",
    env={"AGNO_SANDBOX_TEST_RUNTIME": "1"},
    execution_timeout=300,
)
counts = {"create": 0, "restore": 0}


def counted(method, key):
    async def wrapper(*arguments, **options):
        counts[key] += 1
        return await method(*arguments, **options)

    return wrapper


def workspace_turns(
    checkpoints: FileCheckpointStore, run_id: str, scratch: Path
) -> list:
    """The turns recorded in the checkpoint the run committed, as the fixture writes them."""
    reference = CheckpointRef(**db.get_run(run_id).metadata["sandbox"]["checkpoint"])
    opened = scratch / uuid4().hex
    checkpoints.restore(reference, opened)
    return (opened / "workspace" / "fixture-effects.txt").read_text().split()


async def main() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        checkpoints = FileCheckpointStore(root / "checkpoints")
        transfer = sandbox.checkpoint_transfer(checkpoints)
        coordinator = SandboxCoordinator(db, sandbox, transfer)
        sandbox.acreate = counted(sandbox.acreate, "create")  # type: ignore[method-assign]
        transfer.arestore = counted(transfer.arestore, "restore")  # type: ignore[method-assign]
        print(
            f"Provider: {args.provider}. Computers stay warm for {coordinator.warm_computer_seconds:.0f}s after a turn."
        )

        async def run(number: int) -> None:
            before = dict(counts)
            started = time.monotonic()
            result = await coordinator.arun(
                session_id,
                run_id=f"{session_id}-{number}",
                input=f"turn {number}",
                **turn,
            )
            elapsed = time.monotonic() - started
            created = counts["create"] - before["create"]
            restored = counts["restore"] - before["restore"]
            sandbox_metadata = result.metadata["sandbox"]
            if created and restored:
                path = "cold: a new computer, restored from the last checkpoint"
            elif created:
                path = "cold: a new computer, nothing to restore yet"
            else:
                path = "warm: the previous turn's computer, resumed, nothing restored"
            print(f"Turn {number}: {path}")
            print(
                f"  {elapsed:.1f}s, generation {sandbox_metadata['generation']}, resumed={sandbox_metadata['resumed']}"
            )

        await run(1)
        await run(2)
        coordinator.warm_computer_seconds = 3
        print("Warm window shortened to 3s for the next commit.")
        await run(3)
        print("Waiting 5s, past the window...")
        await asyncio.sleep(5)
        await run(4)
        print(
            f"  turn 4's checkpoint holds every turn: {workspace_turns(checkpoints, f'{session_id}-4', root)}"
        )
        removed = await coordinator.aretire_computer(
            session_id, agent_id=turn["agent_id"]
        )
        print(f"Done; the warm computer left by turn 4 was removed: {removed}")


if __name__ == "__main__":
    asyncio.run(main())
