# Skills with AgentOS

This example demonstrates how to serve an agent with skills via AgentOS, including the ability to execute scripts from skills.

## Features

- Agent with skills loaded from local filesystem
- `get_skill_script` tool to read or execute scripts
- Served via AgentOS with playground UI

## Running the Example

```bash
python cookbook/06_agent_os/skills/skills_with_agentos.py
```

## Skill Structure

```
skills/
└── system-info/
    ├── SKILL.md           # Skill definition with frontmatter
    └── scripts/
        ├── get_system_info.py   # Returns system info as JSON
        └── list_directory.py    # Lists directory contents
```

## Available Tools

The agent has access to these skill-related tools:

| Tool | Description |
|------|-------------|
| `get_skill_instructions` | Load full instructions for a skill |
| `get_skill_reference` | Load a reference document |
| `get_skill_script` | Read or execute a script (use `execute=True` to run) |
