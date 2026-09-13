"""
Load an Antigravity agent from a local directory and run it.

Mirrors the Managed Agents docs' "agent directory" convention:

    example_agent/
    ├── agent.yaml        # id, base_agent, description, system_instruction
    ├── AGENTS.md         # System instructions (overrides agent.yaml.system_instruction)
    ├── skills/           # Mounted under /.agents/skills/<name>/ in the sandbox
    │   └── haiku/SKILL.md
    └── workspace/        # Mounted at the sandbox root
        └── about.txt

`AntigravityAgent.from_agent_directory(...)` parses the directory, builds the
inline source list, and (when `register=True`, the default) registers the named
agent with the API via POST /v1beta/agents before returning. 409 / already-exists
is treated as success, so re-running this script is idempotent.

Pass `register=False` to defer registration if you want to inspect the parsed
agent first; in that case call `agent.ensure_custom_agent()` before the first run.

Files larger than 75 KB are skipped with a warning (API inline-source limit).
Binary files are skipped — the API currently supports text files only.

Requirements:
    export GEMINI_API_KEY=...
    pip install pyyaml

Usage:
    .venvs/demo/bin/python cookbook/frameworks/antigravity/antigravity_from_agent_directory.py
"""

from pathlib import Path

from agno.agents.antigravity import AntigravityAgent

AGENT_DIR = Path(__file__).parent / "example_agent"

# `from_agent_directory` POSTs to /agents before returning (register=True default).
agent = AntigravityAgent.from_agent_directory(str(AGENT_DIR))

agent.print_response("Topic: autumn maples.", stream=True)
agent.print_response("Topic: a quiet beach at dawn.", stream=True)
