# GitHub Copilot SDK Examples

Examples demonstrating how to use GitHub Copilot SDK with Agno.

## Setup

### 1. Install and Authenticate GitHub Copilot CLI

Install and authenticate the GitHub Copilot CLI:

```bash
# Follow installation guide:
# https://docs.github.com/en/copilot/how-tos/set-up/install-copilot-cli

# Authenticate
copilot auth login

# Verify
copilot --version
```

### 2. Install Python SDK

```bash
pip install github-copilot-sdk
```

## Examples

Run examples with:

```bash
python cookbook/90_models/copilot/<example>.py
```

### Basic Examples

- **`basic.py`** - Simple completion
- **`basic_stream.py`** - Streaming responses
- **`async_basic_stream.py`** - Async streaming

### Tool Examples

- **`tool_use.py`** - Function calling with HackerNews
- **`async_tool_use.py`** - Async tools with WebSearch
- **`mcp_tools.py`** - MCP server integration (requires Node.js)

## Available Models

```
"gpt-5", "claude-sonnet-4", "claude-sonnet-4.5", "claude-haiku-4.5"
```

## Resources

- [GitHub Copilot CLI Docs](https://docs.github.com/en/copilot/how-tos/set-up/install-copilot-cli)
- [GitHub Copilot SDK](https://github.com/github/github-copilot-sdk)
- [Agno Documentation](https://docs.agno.ai)
