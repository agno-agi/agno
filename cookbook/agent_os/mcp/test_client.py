"""
First run the AgentOS with enable_mcp=True

```bash
python cookbook/agent_os/mcp/enable_mcp.py
```
"""

import asyncio

from fastmcp import Client

# HTTP server
client = Client("http://localhost:7777/llm/mcp")


async def main():
    async with client:
        # Basic server interaction
        await client.ping()

        # List available operations
        tools = await client.list_tools()
        print("\nAvailable tools:")
        print(tools)

        resources = await client.list_resources()
        print("\nAvailable resources:")
        print(resources)

        prompts = await client.list_prompts()
        print("\nAvailable prompts:")
        print(prompts)

        # Execute operations
        result = await client.read_resource("agent-os://configuration")
        print(result)


asyncio.run(main())
