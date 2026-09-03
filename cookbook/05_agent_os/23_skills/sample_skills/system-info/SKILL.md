---
name: system-info
description: Inspect the host operating system, Python runtime, and local files
license: MIT
metadata:
  version: "1.0.0"
  author: agno
---
# System Info Skill

Use this skill when the user asks about the host running the AgentOS process or
needs a directory inventory from that host.

## Available scripts

- `get_system_info.py` returns the hostname, operating system, architecture,
  Python version and executable, processor, and current UTC time.
- `list_directory.py` lists the direct children of a directory. It accepts one
  optional path argument and defaults to the skill directory.

## Execution

Load these instructions before choosing a script. Execute a script through the
skill tool and inspect its structured result:

```python
get_skill_script(
    skill_name="system-info",
    script_path="get_system_info.py",
    execute=True,
)
```

To list a directory:

```python
get_skill_script(
    skill_name="system-info",
    script_path="list_directory.py",
    execute=True,
    args=["."],
)
```

Only use data parsed from `stdout` when `returncode` is `0`. If execution
returns a nonzero code, report `stderr` or the JSON error instead of inferring
the result.
