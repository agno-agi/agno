# Workspace

A polished local-machine toolkit. Read / write / edit / move / delete / search /
shell, scoped to a `root` directory (paths that resolve outside it are rejected).
Destructive operations require human confirmation by default — AgentOS renders
these as approval cards in the run timeline; in a plain console you drive the
loop yourself.

This is a path-scoping boundary, not a process sandbox — the agent can still
read env vars, hit the network via shell, etc. For untrusted code, run the
agent inside a real sandbox (container, VM, Daytona).

## Quick reference

```python
from agno.tools.workspace import Workspace

# Default: reads auto-pass, writes/edits/moves/deletes/shell require confirmation.
tools = [Workspace(".")]

# Explicit partition for clarity (recommended for the homepage demo style):
tools = [
    Workspace(
        ".",
        allowed=["read", "list", "search"],
        confirm=["write", "edit", "delete", "shell"],
    )
]

# Read-only:
tools = [Workspace(".", allowed=["read", "list", "search"])]

# Defensive: also block writes-to-files-the-agent-hasn't-read:
tools = [Workspace(".", require_read_before_write=True)]
```

## Permission model

`allowed` and `confirm` are mutually exclusive partitions of short
aliases. An alias in `allowed` runs silently, an alias in `confirm`
requires approval, an alias in neither isn't registered, and an alias in both
raises `ValueError`. The full alias mapping:

| Alias    | Registered tool name | What it does                            |
| -------- | -------------------- | --------------------------------------- |
| `read`   | `read_file`          | Read a file (line-numbered, optional range) |
| `list`   | `list_files`         | List a directory (optional glob, optional recursive with `max_depth`) |
| `search` | `search_content`     | Recursive content grep                  |
| `write`  | `write_file`         | Create or overwrite a file (atomic)     |
| `edit`   | `edit_file`          | Replace a substring (with `replace_all`)|
| `move`   | `move_file`          | Move or rename a file                   |
| `delete` | `delete_file`        | Delete a file                           |
| `shell`  | `run_command`        | Run a shell command in `root`           |

The aliases keep snippets compact; the registered tool names stay descriptive
so the LLM tool spec is self-explanatory.

## Notable behaviors

- **`read_file` returns line-numbered output** (`cat -n` style). Numbers reflect
  actual file lines, so the agent can chain into `edit_file` precisely.
- **`list_files` returns rich entries**: each is `{path, type, size}`. Use
  `recursive=True` (default `max_depth=3`) to walk the tree.
- **`edit_file` defaults to unique-or-fail**, with `replace_all=True` for renames.
- **`write_file` is atomic** — writes to `<file>.tmp`, then `os.replace`.
- **`run_command` strips ANSI codes** and tails to the last 100 lines (configurable).
- **`require_read_before_write=True`** (opt-in) blocks `write_file` / `edit_file` /
  `move_file` / `delete_file` on existing files until the agent has read them
  this session. Catches the "agent hallucinated the file's contents" bug.

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
