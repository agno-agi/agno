# Workspace

A polished local-machine toolkit. Read / write / edit / delete / search / shell,
scoped to a sandboxed `root`. Destructive operations require human confirmation
by default — AgentOS renders these as approval cards in the run timeline; in a
plain console you drive the loop yourself.

## Quick reference

```python
from agno.tools.workspace import Workspace

# Default: reads auto-pass, writes/edits/deletes/shell require confirmation.
tools = [Workspace(".")]

# Explicit partition for clarity (recommended for the homepage demo style):
tools = [
    Workspace(
        ".",
        allowed_tools=["read", "list", "search"],
        confirm_tools=["write", "edit", "delete", "shell"],
    )
]

# Read-only:
tools = [Workspace(".", allowed_tools=["read", "list", "search"])]
```

`allowed_tools` and `confirm_tools` are mutually exclusive partitions of short
aliases — an alias in `allowed_tools` runs silently, an alias in `confirm_tools`
requires approval, an alias in neither isn't registered, and an alias in both
raises `ValueError`. The full mapping:

| Alias    | Registered tool name | What it does                            |
| -------- | -------------------- | --------------------------------------- |
| `read`   | `read_file`          | Read a file (optionally a line range)   |
| `list`   | `list_files`         | List a directory (optional glob)        |
| `search` | `search_content`     | Recursive content grep                  |
| `write`  | `write_file`         | Create or overwrite a file              |
| `edit`   | `edit_file`          | Replace exactly one occurrence in a file|
| `delete` | `delete_file`        | Delete a file                           |
| `shell`  | `run_command`        | Run a shell command in `root`           |

The aliases keep snippets compact; the registered tool names stay descriptive
so the LLM tool spec is self-explanatory.

## Examples in this folder

- `basic_usage.py` — agent reads a tmp file and writes a summary, with
  confirmations disabled so the demo runs end-to-end.
- `with_confirmation.py` — same agent with the default safety on; you
  approve each write at the console.

## Running

```bash
.venvs/demo/bin/python cookbook/91_tools/workspace_tools/basic_usage.py
.venvs/demo/bin/python cookbook/91_tools/workspace_tools/with_confirmation.py
```
