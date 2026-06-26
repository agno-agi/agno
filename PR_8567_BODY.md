## Summary

Targeted patches on upstream agno **2.6.9** for [banavo-agent-os](https://github.com/andromeda360/banavo-agent-os).

**No `agno/banavo/` namespace** — framework fixes live in existing agno modules. Banavo app code (team shim, V1 run events, custom models) lives in banavo-agent-os under `banavo/agno_compat/` and `banavo/models/agno/`.

### Changes (upstream files only)

- **`agno/storage/postgres.py`** — real PostgresStorage for team session persistence
- **V1 import stubs** — `agno.storage`, `agno.memory.v2`, `agno.run.response`
- **`agno/models/openai/gpt5_responses.py`** — GPT-5 Responses API reasoning + tool chaining
- **`agno/team/_tools.py`** — `_agent` injection for custom transfer tools
- **`scripts/test_setup.sh`** — CI dependency pins

### Motivation

- Session persistence broke after agno 2.x upgrade
- GPT-5 reasoning requires `provider_data` / `previous_response_id` chaining
- Reviewer guidance: small patches in actual source files, not a copied runtime

Related: andromeda360/agno `banavo/agno-patches-2.6.9`, banavo-agent-os `progress_test/agno_upgrade_2.6.9`.

## Type of change

- [x] Bug fix
- [x] Improvement

## Test plan

- [ ] `./scripts/test_setup.sh && pytest libs/agno/tests/unit`
- [ ] banavo-agent-os: `uv sync && python scripts/validate_agent_imports.py`
- [ ] banavo-agent-os: `pytest tests/agno/ tests/automated/models/test_gpt5_responses_tool_schema.py`
