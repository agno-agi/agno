# CLAUDE.md - Tools Cookbook

Instructions for Claude Code when testing the tools cookbooks.

---

## Overview

This folder contains **tool** examples - all the built-in tools and how to create custom tools.

**Total Examples:** 200
**Organization:** By tool type

---

## Quick Reference

**Test Environment:**
```bash
.venvs/demo/bin/python
```

**Run a cookbook:**
```bash
.venvs/demo/bin/python cookbook/90_tools/mcp/basic_mcp.py
```

---

## Folder Structure

| Folder | Count | Description |
|:-------|------:|:------------|
| `mcp/` | 41 | MCP (Model Context Protocol) tools |
| `tool_decorator/` | 8 | Custom tools with @tool decorator |
| `tool_hooks/` | 10 | Pre/post hooks for tools |
| `async/` | 3 | Async tool patterns |
| `exceptions/` | 3 | Error handling |
| `models/` | 7 | Model-specific tool usage |
| `other/` | 11 | Misc tool patterns |

---

## MCP Tools (Model Context Protocol)

The `mcp/` folder is the largest, covering:
- Basic MCP setup
- Multiple MCP servers
- MCP with various backends (filesystem, git, etc.)
- Async MCP patterns

MCP allows connecting to external tool servers.

---

## Custom Tools

### @tool Decorator
```python
from agno.tools import tool

@tool
def my_tool(query: str) -> str:
    """Tool description."""
    return result
```

### Tool Hooks
Pre and post processing for tool calls.

---

## Testing Priorities

### High Priority
- `tool_decorator/basic_tool.py` - Custom tools
- `mcp/basic_mcp.py` - MCP basics

### MCP Examples
- Require Node.js for npx
- Various MCP servers available

---

## Dependencies

- `MCP_*` keys for various MCP servers
- Node.js for npx-based MCP servers
- Provider-specific API keys
