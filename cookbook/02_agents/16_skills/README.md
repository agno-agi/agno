# skills

Examples for defining and using agent skills and helper scripts.

## Files
- `basic_skills.py` - Demonstrates basic skills.
- `mcp_skills.py` - Loads skills served by an MCP server through the MCP Skills extension (`io.modelcontextprotocol/skills`) with `MCPSkills`.
- `mcp_skills_execution_gate.py` - Once a run loads an MCP-served skill, code-execution tools such as `ShellTools` require confirmation for the rest of the run. Shows approving or rejecting each call. The gate covers the tools of the agent or team that loads the skill, not a team's members: give `MCPSkills` to the member that runs code, or set `requires_confirmation` on the members' execution tools.
- `mcp_skills_huggingface.py` - Loads skills from Hugging Face's public MCP server (`https://huggingface.co/mcp`). No API key is needed for the skills.
- `mcp_skills_server.py` - A minimal MCP server that serves `sample_skills/` through the Skills extension. Started over stdio by `mcp_skills.py`.
- `sample_skills/code-review/scripts/check_style.py` - Demonstrates check style.
- `sample_skills/git-workflow/scripts/commit_message.py` - Demonstrates commit message.

## Prerequisites
- Load environment variables with `direnv allow` (including `OPENAI_API_KEY`).
- Create the demo environment with `./scripts/demo_setup.sh`, then run cookbooks with `.venvs/demo/bin/python`.
- Some examples require optional local services (for example pgvector) or provider-specific API keys.

## Run
- `.venvs/demo/bin/python cookbook/02_agents/<directory>/<file>.py`
