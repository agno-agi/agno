"""Explicit read-only commands over a published Knowledge namespace.

Uses the same demo database as public_pages.py. Run sync there first.
"""

import argparse
import asyncio

from agno.knowledge.page import PageError, PageFileSystem, tool_error


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Read published pages with bounded commands"
    )
    parser.add_argument("command", nargs="?", default="ls /")
    args = parser.parse_args()

    from public_pages import knowledge

    knowledge.setup()
    page_files = PageFileSystem(knowledge=knowledge, max_output_chars=30_000)

    # Applications retain their tool name, description, error wording and prompts.
    async def query_pages(command: str) -> str:
        """Read or search published Markdown using cat, ls, tree, find or rg."""
        try:
            return await page_files.arun_command(command)
        except PageError as exc:
            return tool_error(exc)

    print(asyncio.run(query_pages(args.command)))
    # Synchronous callers can use page_files.run_command(args.command).


if __name__ == "__main__":
    main()
