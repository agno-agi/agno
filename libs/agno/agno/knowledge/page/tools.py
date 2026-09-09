"""Transport adapters over public page search and command outcomes."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal, Optional

from agno.knowledge.page.types import PageCommandResult, PageError, SearchResult, tool_error

if TYPE_CHECKING:
    from agno.knowledge.knowledge import Knowledge
    from agno.knowledge.page.filesystem import PageFileSystem
    from agno.tools.function import Function
    from agno.tools.toolkit import Toolkit

READ_ONLY = {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}


def command_mcp_tools(files: PageFileSystem, *, tool_name: str, description: str, max_output_bytes: int) -> Toolkit:
    from agno.tools.toolkit import Toolkit

    PageCommandResult(text="").bounded(max_output_bytes)

    def check(result: PageCommandResult) -> PageCommandResult:
        if result.is_error:
            from fastmcp.exceptions import ToolError

            raise ToolError(result.text)
        return result

    def query_pages(command: str) -> PageCommandResult:
        return check(files.run_command_result(command, max_output_bytes=max_output_bytes))

    async def aquery_pages(command: str) -> PageCommandResult:
        return check(await files.arun_command_result(command, max_output_bytes=max_output_bytes))

    query_pages.__name__ = tool_name
    toolkit = Toolkit(name="page_filesystem", tools=[query_pages], async_tools=[(aquery_pages, tool_name)])
    for function in (toolkit.functions[tool_name], toolkit.async_functions[tool_name]):
        function.description = description
        function.annotations = dict(READ_ONLY)
    return toolkit


def page_search_tool(
    knowledge: Knowledge,
    *,
    async_mode: bool,
    transport: Literal["chat", "mcp"],
    tool_name: str,
    description: Optional[str],
    max_output_bytes: int,
    run_response: Any = None,
) -> Function:
    from agno.tools.function import Function

    if transport not in ("chat", "mcp") or not tool_name.strip():
        raise ValueError("Use a nonempty tool name and chat or mcp transport")
    if type(max_output_bytes) is not int or not 1024 <= max_output_bytes <= 32000:
        raise ValueError("max_output_bytes must be an integer from 1024 through 32000")

    def record(result: SearchResult, query: str) -> SearchResult:
        if run_response is not None:
            from agno.models.message import MessageReferences

            references = MessageReferences(
                query=query, references=[doc.to_dict() for doc in knowledge._page_documents(result)]
            )
            if run_response.references is None:
                run_response.references = []
            run_response.references.append(references)
        return result

    def failure(exc: Exception):
        if transport == "mcp":
            from fastmcp.exceptions import ToolError

            raise ToolError(exc.code if isinstance(exc, PageError) else "invalid_request") from exc
        return tool_error(exc)

    def search_pages(query: str, alternatives: Optional[list[str]] = None) -> str:
        """Search indexed documentation by question or identifier, optionally with alternative phrasings."""
        try:
            return record(
                knowledge.search_pages(query, alternatives=alternatives, max_output_bytes=max_output_bytes), query
            ).model_dump_json()
        except (PageError, ValueError) as exc:
            return failure(exc)

    async def asearch_pages(query: str, alternatives: Optional[list[str]] = None) -> str:
        try:
            return record(
                await knowledge.asearch_pages(query, alternatives=alternatives, max_output_bytes=max_output_bytes),
                query,
            ).model_dump_json()
        except (PageError, ValueError) as exc:
            return failure(exc)

    def search_mcp(query: str, alternatives: Optional[list[str]] = None) -> SearchResult:
        try:
            return record(
                knowledge.search_pages(query, alternatives=alternatives, max_output_bytes=max_output_bytes), query
            )
        except (PageError, ValueError) as exc:
            return failure(exc)

    async def asearch_mcp(query: str, alternatives: Optional[list[str]] = None) -> SearchResult:
        try:
            return record(
                await knowledge.asearch_pages(query, alternatives=alternatives, max_output_bytes=max_output_bytes),
                query,
            )
        except (PageError, ValueError) as exc:
            return failure(exc)

    entrypoint = (
        (asearch_mcp if async_mode else search_mcp)
        if transport == "mcp"
        else (asearch_pages if async_mode else search_pages)
    )
    function = Function.from_callable(entrypoint, name=tool_name)
    function.description = description or search_pages.__doc__
    function.annotations = dict(READ_ONLY)
    return function
