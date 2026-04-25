# WorkspaceTools

A polished local-machine toolkit. Read / write / edit / delete / search / shell,
scoped to a sandboxed `base_dir`. Destructive operations require human
confirmation by default — AgentOS renders these as approval cards in the run
timeline; in a plain console you drive the loop yourself.

## Quick reference

```python
from agno.tools.workspace import WorkspaceTools

# Default: reads auto-pass, writes/edits/deletes/shell require confirmation.
tools = [WorkspaceTools(base_dir=".")]

# Explicit partition for clarity (recommended for the homepage demo style):
tools = [
    WorkspaceTools(
        base_dir=".",
        allowed_tools=["read_file", "list_files", "search_content"],
        confirm_tools=["write_file", "edit_file", "delete_file", "run_command"],
    )
]

# Read-only:
tools = [WorkspaceTools(base_dir=".", allowed_tools=["read_file", "list_files", "search_content"])]
```

`allowed_tools` and `confirm_tools` are mutually exclusive partitions — a tool
in `allowed_tools` runs silently, a tool in `confirm_tools` requires approval,
a tool in neither isn't registered, and a tool in both raises `ValueError`.

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
