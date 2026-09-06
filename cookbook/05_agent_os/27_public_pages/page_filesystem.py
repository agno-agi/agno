"""Explicit read-only commands over a published Knowledge namespace.

Uses the same demo database as public_pages.py. Run sync there first.
"""

import argparse
import asyncio

from agno.agent import Agent
from agno.knowledge.page import PageFileSystem
from agno.models.openai import OpenAIResponses


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Read published pages with bounded commands"
    )
    parser.add_argument("command", nargs="?", default="ls /")
    parser.add_argument(
        "--ask",
        action="store_true",
        help="Let the agent explore pages to answer the command text",
    )
    args = parser.parse_args()

    from public_pages import knowledge

    knowledge.setup()
    page_files = PageFileSystem(knowledge=knowledge, max_output_chars=30_000)

    # Tool exposure is explicit; setup and retrieval policy stay in the application.
    agent = Agent(
        model=OpenAIResponses(id="gpt-5.6-luna"),
        tools=[page_files.tools()],
    )
    if args.ask:
        agent.print_response(args.command)
    else:
        print(asyncio.run(page_files.arun_command(args.command)))
    # Synchronous callers can use page_files.run_command(args.command).


if __name__ == "__main__":
    main()
