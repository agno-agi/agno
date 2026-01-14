# MCP Agents using Agno

Model Context Protocol (MCP) gives Agents the ability to interact with external systems through a standardized interface. Using Agno's MCP integration, you can build Agents that can connect to any MCP-compatible service.

## Examples in this Directory

1. Filesystem Agent (`filesystem.py`)

This example demonstrates how to create an agent that can explore, analyze, and provide insights about files and directories on your computer.

2. GitHub Agent (`github.py`)

This example shows how to create an agent that can explore GitHub repositories, analyze issues, pull requests, and more.

3. Groq with Llama using MCP (`groq_mcp.py`)

This example uses the file system MCP agent with Groq running the Llama 3.3-70b-versatile model.

4. Include/Exclude Tools (`include_exclude_tools.py`)

This example shows how to include and exclude tools from the MCP agent. This is useful for reducing the number of tools available to the agent, or for focusing on a specific set of tools.

5. Multiple MCP Servers (`multiple_servers.py`)

This example shows how to use multiple MCP servers in the same agent. 

6. Sequential Thinking (`sequential_thinking.py`)

This example shows how to use the MCP agent to perform sequential thinking.

7. Airbnb Agent (`airbnb.py`)

This example shows how to create an agent that uses MCP and Gemini 2.5 Pro to search for Airbnb listings.


## Getting Started

### Prerequisites

Install the required dependencies:

```bash
pip install agno mcp openai
```

Export your API keys:

```bash
export OPENAI_API_KEY="your_openai_api_key"
```

> For the GitHub example, create a Github PAT following [these steps](https://github.com/modelcontextprotocol/servers/tree/main/src/github#setup).

### Run the Examples

```bash
python filesystem.py
python github.py
```

## How It Works

These examples use Agno to create agents that leverage MCP servers. The MCP servers provide standardized access to different data sources (filesystem, GitHub), and the agents use these servers to answer questions and perform tasks.

The workflow is:
1. Agent receives a query from the user
2. Agent determines which MCP tools to use
3. Agent calls the appropriate MCP server to get information
4. Agent processes the information and provides a response

## Customizing

You can modify these examples to:
- Connect to different MCP servers
- Change the agent's instructions
- Add additional tools
- Customize the agent's behavior

## More Information

- Read more about [MCP](https://modelcontextprotocol.io/introduction)
- Read about [Agno's MCP integration](https://docs.agno.com/tools/mcp)
