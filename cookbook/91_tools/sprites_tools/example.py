"""Use a caller-owned Sprite with Agno. See README.md for setup and lifecycle."""

import argparse
import json
import os
from uuid import uuid4

from sprites import SpritesClient

from agno.tools.sprites import SpritesTools


def check_workspace(tools: SpritesTools) -> None:
    """Verify file continuity across two commands without making an LLM call."""
    path = f"/tmp/agno-sprites-{uuid4().hex}.txt"
    expected = "Agno can reuse this Sprite."
    try:
        write = json.loads(
            tools.run_shell_command(
                [
                    "python",
                    "-c",
                    "import pathlib, sys; pathlib.Path(sys.argv[1]).write_text(sys.argv[2], encoding='utf-8')",
                    path,
                    expected,
                ]
            )
        )
        if write.get("exit_code") != 0:
            raise RuntimeError(f"Write failed: {write}")

        read = json.loads(tools.run_shell_command(["cat", path]))
        if read.get("exit_code") != 0 or read.get("stdout") != expected:
            raise RuntimeError(f"Read did not return the earlier file: {read}")
        print(
            "Workspace check passed: the second command read the first command's file."
        )
    finally:
        # Remove only this check's uniquely named file. Keep the caller's Sprite.
        cleanup = json.loads(tools.run_shell_command(["rm", "-f", "--", path]))
        if cleanup.get("exit_code") != 0:
            print(f"Temporary file cleanup was not confirmed: {path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sprite", required=True, help="Name of an existing Sprite you own"
    )
    parser.add_argument(
        "--model",
        help="Agno provider:model ID; omit to run the workspace check without an LLM",
    )
    args = parser.parse_args()

    client = SpritesClient(token=os.environ["SPRITES_TOKEN"])
    try:
        tools = SpritesTools(sprite=client.get_sprite(args.sprite))
        if args.model:
            from agno.agent import Agent

            agent = Agent(
                name="Sprites coding agent",
                model=args.model,
                tools=[tools],
                instructions=[
                    "Use run_shell_command to execute commands in the Sprite.",
                    "Pass an executable and arguments; use bash -lc explicitly if you need shell syntax.",
                    "Check exit_code, stderr, and truncation flags before interpreting a result.",
                    "If execution status is unknown, report that instead of retrying the command.",
                ],
                markdown=True,
            )
            agent.print_response(
                "Run Python to calculate the first ten square numbers and show the result."
            )
        else:
            check_workspace(tools)
    finally:
        # The client owns local connections. Closing it does not delete the Sprite.
        client.close()


if __name__ == "__main__":
    main()
