"""Inspect typed page results and configure matching chat/MCP tools."""

import argparse
import asyncio

from agno.knowledge.page import PageCommandResult, PageFileSystem


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", nargs="?", default="cat /agent")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check Unicode result bounds without storage calls",
    )
    args = parser.parse_args()
    if args.check:
        result = PageCommandResult(text="Documentation 🙂\n" * 1000).bounded(1024)
        assert result.truncated and len(result.model_dump_json().encode()) <= 1024
        print(result.model_dump_json())
        return

    from public_pages import knowledge

    await knowledge.asetup()
    files = PageFileSystem(knowledge=knowledge)
    result = await files.arun_command_result(args.command, max_output_bytes=24000)
    print(result.model_dump_json(indent=2))

    # Supply these explicitly to Agent.tools and MCPConfig.tools respectively.
    chat_search = knowledge.get_tools(page_results=True, tool_name="search_docs")
    mcp_search = knowledge.get_tools(
        page_results=True, tool_name="search_docs", transport="mcp", async_mode=True
    )
    mcp_files = files.tools(tool_name="query_docs_filesystem", transport="mcp")
    assert chat_search and mcp_search and mcp_files


if __name__ == "__main__":
    asyncio.run(main())
