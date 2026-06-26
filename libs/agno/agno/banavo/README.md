# agno.banavo — Banavo extensions on upstream agno 2.6.x

Banavo-specific code lives here so **banavo-agent-os** consumes a single `agno` git
dependency instead of vendoring `agno_custom` locally.

## Layout

| Module | Status | Notes |
|--------|--------|-------|
| `message_persistence.py` | **Delta** | Patches `Message.to_dict` to persist `provider_data` (GPT-5 follow-up chat) |
| `storage/`, `memory/v2/`, `run/response.py`, `run/compat.py` | **Delta** | V1 storage + V1/V2 run event bridge |
| `events/stream_events.py` | **Delta** | `BaseBanavoStreamEvent` for typed tool stream events |
| `models/` | **Delta** | Banavo `Model` base, GPT-5 Responses, Claude tool-schema fixes |
| `memory/`, `utils/`, `run/team.py`, `base/` | **Delta** | V1 `RunResponse` orchestration helpers |
| `tools/` | **Thin** | Re-exports `agno.tools` (no forked copy) |
| `agent/`, `team/` | **Legacy** | V1-runtime `Agent`/`Team` (pending migration — see below) |

## Thinning roadmap

### Done
- PR 1: PostgresStorage + V1 import stubs (~1.4k lines)
- PR 2: Move extensions from banavo-agent-os into `agno.banavo`
- Tools re-export from upstream `agno.tools`

### Next (Agent / Team)
Forked `agent/agent.py` and `team/team.py` (~12k lines) implement the **agno 1.x
`RunResponse` / `RunResponseEvent` runtime**. Upstream 2.6.x uses `RunOutput` /
`RunOutputEvent` instead.

Migration path:
1. Migrate banavo streaming + members to V2 run events (`agno.run.agent.RunEvent`, etc.)
2. Replace `agno.banavo.agent.Agent` with thin subclass of `agno.agent.Agent`
3. Replace `agno.banavo.team.Team` with thin subclass of `agno.team.Team`
4. Delete `base/orchestrator.py` shared V1 logic once unused

Until step 1–2 complete, banavo-agent-os imports `Agent`/`Team` from `agno.banavo`
(not `agno.agent`) intentionally.

## Consumer imports (banavo-agent-os)

```python
from agno.banavo.agent import Agent
from agno.banavo.team import Team
from agno.banavo.models import Model, OpenAIChat, Claude
from agno.banavo.memory import Memory
import agno.banavo.message_persistence  # noqa: F401
```
