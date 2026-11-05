"""Two turns of one session on AgentCore microVMs. This creates billable compute.

Deploy a runtime with agentcore_setup.py, then set AGENTCORE_RUNTIME_ARN to the
ARN it printed. The default fixture harness makes no model calls.

--harness codex forwards OPENAI_API_KEY into the sandbox. --harness claude uses
Bedrock through the runtime's execution role, so it needs model access in that
account but no API key. Both real harnesses check that turn 2 recalls a codeword
that only the conversation from turn 1 holds.

By default turn 2 looks the sandbox up again with create, as a new request would:
the same session and generation name the same microVM, so the harness resumes
with nothing to restore. --replace checkpoints the computer after turn 1,
destroys it and restores generation 2 on a fresh microVM, the path a session
takes after its microVM ends.
"""

import argparse
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from agno.sandbox.agentcore import AgentCoreCheckpointTransfer, AgentCoreSandbox
from agno.sandbox.checkpoint import FileCheckpointStore
from agno.sandbox.client import SandboxRuntimeClient


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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--harness", choices=("fixture", "claude", "codex"), default="fixture"
    )
    parser.add_argument(
        "--model", help="Bedrock model for claude, OpenAI model for codex"
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Run turn 2 on a new microVM restored from a checkpoint",
    )
    args = parser.parse_args()

    runtime_arn = os.environ["AGENTCORE_RUNTIME_ARN"]
    if args.harness == "fixture":
        env = {"AGNO_SANDBOX_TEST_RUNTIME": "1"}
        config = {}
        turns = ["Create a file", "Continue in the same session"]
    else:
        if args.harness == "claude":
            env = {
                "CLAUDE_CODE_USE_BEDROCK": "1",
                "AWS_REGION": runtime_arn.split(":")[3],
            }
            config = {
                "model": args.model or "us.anthropic.claude-sonnet-5",
                "permission_mode": "acceptEdits",
                "allowed_tools": ["Read", "Write", "Edit", "Bash"],
            }
        else:
            # Only the selected model key enters compute. The microVM is the
            # isolation boundary, so Codex runs without its own nested sandbox.
            env = {"OPENAI_API_KEY": os.environ["OPENAI_API_KEY"]}
            config = {"sandbox": "full-access"}
            if args.model:
                config["model"] = args.model
        # The codeword is never written to a file, so only the conversation from
        # turn 1 can answer turn 2.
        turns = [
            "Remember the codeword BLUE-HERON, but do not write it to any file. "
            "Create primes.py that prints the first 10 primes, run it, and report the output.",
            "What codeword did I ask you to remember? Then add test_primes.py for primes.py, "
            "run it with python, and report the result.",
        ]

    sandbox = AgentCoreSandbox(
        runtime_arn, namespace="agentcore-example-" + uuid4().hex[:12], lifetime=1800
    )
    client = SandboxRuntimeClient(sandbox)
    identity = {"session_id": "example", "agent_id": "coder", "env": env}
    handles = [sandbox.create(**identity)]
    try:
        with TemporaryDirectory() as directory:
            transfer = AgentCoreCheckpointTransfer(
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
            place = "a restored microVM" if args.replace else "the same microVM"
            print(f"Turn 2 recalled the codeword on {place}.")
    finally:
        for handle in handles:
            sandbox.destroy(handle)
            print("Destroyed", handle.provider_ref)


if __name__ == "__main__":
    main()
