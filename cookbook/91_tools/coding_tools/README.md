# CodingTools

A minimal, powerful toolkit for coding agents. Provides 4 core tools and 3 optional exploration tools.

## Philosophy

Inspired by the Pi coding agent: a small number of composable tools is more powerful than many specialized ones. With `read_file`, `edit_file`, `write_file`, and `run_shell`, an agent can perform any coding task.

## Tools

### Core (enabled by default)

| Tool | Description |
|------|-------------|
| `read_file` | Read files with line numbers and pagination |
| `edit_file` | Exact text find-and-replace with unified diff output |
| `write_file` | Create or overwrite files, auto-creates parent dirs |
| `run_shell` | Execute shell commands with timeout and output truncation |

### Exploration (opt-in)

| Tool | Description |
|------|-------------|
| `grep` | Search file contents for a pattern |
| `find` | Search for files by glob pattern |
| `ls` | List directory contents |

## Usage

```python
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.coding import CodingTools

# Core tools only (default)
agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[CodingTools(base_dir="./workspace")],
)

# All 7 tools
agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[CodingTools(base_dir="./workspace", all=True)],
)

# Selective
agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[CodingTools(base_dir="./workspace", enable_grep=True, enable_find=True)],
)
```

## Examples

| File | Description |
|------|-------------|
| `01_basic_usage.py` | Core 4 tools with a coding agent |
| `02_all_tools.py` | All 7 tools enabled |
