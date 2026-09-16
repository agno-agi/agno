"""Call the running release assistant over Streamable HTTP MCP."""

import asyncio

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

# ---------------------------------------------------------------------------
# Create the example
# ---------------------------------------------------------------------------


async def main():
    async with streamable_http_client("http://localhost:7777/mcp") as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(
                "write_release_notes",
                {
                    "message": "Write release notes for these changes: CSV export includes "
                    "active filters; saved reports can be renamed; duplicate notifications are fixed."
                },
            )
            if result.is_error:
                raise RuntimeError(result)
            for content in result.content:
                if content.type == "text":
                    print(content.text)


# ---------------------------------------------------------------------------
# Run the example
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    asyncio.run(main())
