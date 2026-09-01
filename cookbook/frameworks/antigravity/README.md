# Antigravity (Gemini Agents API)

Examples for integrating Google's Gemini Agents API ("Antigravity") with Agno.

Antigravity is a managed agent loop: a single REST call spins up a sandboxed
Linux environment with web search, code execution, and file I/O built in,
runs an autonomous loop to satisfy the request, and returns or streams
events. Environments persist across turns via an `environment_id`.

Agno integrates Antigravity two ways. Pick based on who drives the loop:

| Integration | When to use | Example |
|---|---|---|
| `AntigravityAgent` (external agent) | You want Antigravity to **be** the agent — served through AgentOS, with Agno handling sessions, streaming, and the UI. | `antigravity_basic.py`, `antigravity_session_agentos.py` (this folder) |
| `AntigravityTools` (toolkit) | You want a regular Agno agent (any model) to **delegate** a sub-task to an Antigravity sandbox as one tool call. | [`cookbook/91_tools/antigravity/antigravity_tools.py`](../../91_tools/antigravity/antigravity_tools.py) |

## Setup

```bash
export GEMINI_API_KEY=...
```

## Files

- `antigravity_basic.py` — minimal standalone run
- `antigravity_session.py` — multi-turn session, environment reused across turns
- `antigravity_sources.py` — pre-load files into the sandbox (inline / GCS / repo)
- `antigravity_custom_agent.py` — register a named custom agent (Agents API) and invoke it
- `antigravity_from_agent_directory.py` — load an agent from a local `agent.yaml` + `AGENTS.md` + `workspace/` + `skills/` folder (see `example_agent/`)
- `antigravity_snapshot.py` — download an environment's filesystem as a tar archive
- `antigravity_session_agentos.py` — same with SQLite-backed sessions

For the toolkit examples (Antigravity-as-a-tool), see:
- [`cookbook/91_tools/antigravity/antigravity_tools.py`](../../91_tools/antigravity/antigravity_tools.py) — delegate a sub-task to a sandbox
- [`cookbook/91_tools/antigravity/antigravity_agents_crud_tools.py`](../../91_tools/antigravity/antigravity_agents_crud_tools.py) — full Agents API CRUD (create / get / update / list / versions / delete / invoke)
- [`cookbook/91_tools/antigravity/antigravity_directory_tools.py`](../../91_tools/antigravity/antigravity_directory_tools.py) — wire a local `agent.yaml` folder into the toolkit (parses, registers, routes future tool calls at the named agent)
- [`cookbook/91_tools/antigravity/antigravity_snapshot_tools.py`](../../91_tools/antigravity/antigravity_snapshot_tools.py) — have an Agno agent run a sandbox task then download the resulting environment as a tar

Test results are tracked in `TEST_LOG.md`.
