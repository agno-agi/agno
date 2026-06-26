# agno.banavo — Banavo extensions on upstream agno 2.6.x

Small patches on upstream agno so **banavo-agent-os** consumes one `agno` git dependency
without vendoring a forked V1 Agent/Team runtime.

## Layout

| Module | Status | Notes |
|--------|--------|-------|
| `agent/`, `team/` | **Upstream** | Re-export `agno.agent.Agent` and upstream `Team` via `team/upstream_team.py` |
| `team/upstream_team.py` | **Shim** | Banavo kwarg aliases (`message`→`input`, `storage`→`PostgresDb`, etc.) |
| `message_persistence.py` | **Delta** | `Message.to_dict` persists `provider_data` for GPT-5 follow-up chat |
| `storage/`, `memory/v2/`, `run/response.py`, `run/compat.py` | **Delta** | V1 storage stubs + V2 event bridge (transitional) |
| `models/` | **Delta** | GPT-5 Responses, Claude fixes — thin subclasses on upstream models |
| `memory/memory.py` | **Transitional** | V1 `Memory` wrapper; migrate call sites to upstream `PostgresDb` |
| `tools/` | **Thin** | Re-exports `agno.tools` |
| `events/stream_events.py` | **Delta** | `BaseBanavoStreamEvent` for typed tool stream events |

## Imports (banavo-agent-os)

```python
from agno.banavo.agent import Agent      # → agno.agent.Agent
from agno.banavo.team import Team        # → upstream Team + banavo kw aliases
from agno.banavo.models import OpenAIChat, Claude
import agno.banavo.message_persistence  # noqa: F401
```

Target end state:

```python
from agno.agent import Agent
from agno.team import Team
```

## Deleted (legacy V1 runtime)

- `agent/agent.py`, `team/team.py`, `base/orchestrator.py` — forked 1.x `RunResponse` runtime (~15k lines)
