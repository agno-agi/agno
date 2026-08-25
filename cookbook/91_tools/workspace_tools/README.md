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
- **`exclude_patterns` is an access boundary, not just a listing filter.** A path
  is excluded when any component of the path as written, or of the file it
  resolves to, matches a pattern (`.env*`, `*.env`, `.git`, `.venv`,
  `node_modules`, ...). Excluded paths are hidden from `list_files` /
  `search_content` and refused by `read_file`, `write_file`, `edit_file`,
  `move_file` (either end), and `delete_file` with
  `Error: <argument> is excluded from this workspace: <path>`. On a
  case-insensitive filesystem (macOS and Windows defaults) patterns match
  case-insensitively, so `.ENV` is refused there. Each pattern matches one path
  component; `dist/` raises `ValueError`, use `dist`. `run_command` is a process,
  not a path, and is outside this boundary; gate it with `confirm`.
- **`allow_paths=[...]`** names workspace-relative files or directories that stay
  visible and reachable even when they match an exclude pattern. Entries are
  literal paths. A directory entry covers the files beneath it, and exclude
  patterns still apply beneath the entry: `allow_paths=["build"]` reaches
  `build/index.html` but not `build/.env`.

```python
# Let the agent write the committed template while the real .env stays refused.
tools = [Workspace(".", allow_paths=[".env.example"])]
```

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
