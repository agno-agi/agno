# dynamic_subagent

Dynamic subagents let an Agent or Team's LLM spawn, use, and discard ephemeral specialist agents mid-run — entirely on its own initiative, with no extra developer code after initial setup.

## Files

- `01_basic.py` — Minimal setup: `enable_dynamic_subagents=True` and the LLM decides everything.
- `02_with_tools.py` — Tool delegation with a whitelist: subagents inherit specific parent tools.
- `03_parallel.py` — Async parallel spawning: multiple subagents run concurrently in one LLM turn.
- `04_team.py` — Team integration: a Team leader spawns subagents alongside registered members.
- `05_model_tiers.py` — Cost-aware tier selection: LLM picks `fast` / `standard` / `powerful` per task.
- `06_context_isolation.py` — Full context isolation: mock DB and KB tools stay out of the parent's context.

## Prerequisites

- Load environment variables with `direnv allow` (including `OPENAI_API_KEY`).
- Create the demo environment with `./scripts/demo_setup.sh`, then run cookbooks with `.venvs/demo/bin/python`.

## Run

```
.venvs/demo/bin/python cookbook/02_agents/18_dynamic_subagents/<file>.py
```

## Reference

See `DYNAMIC_SUBAGENTS.md` for the full API reference, architecture explanation, and concurrency details.
