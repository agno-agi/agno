## Summary

Banavo-maintained patches on upstream agno **2.6.9** for [banavo-agent-os](https://github.com/andromeda360/banavo-agent-os).

This PR adds targeted extensions so Banavo can consume **one official agno package**
(from our fork) instead of vendoring ~23k lines of `agno_custom` inside the app repo.

### Commit 1 — V1 storage & compat (~1.4k lines)
- Real `PostgresStorage` for team session persistence (follow-up chat)
- V1 import stubs: `agno.memory.v2`, `agno.storage`, `agno.run.response`
- `message_persistence` patch for `Message.provider_data` round-trips
- CI pins in `scripts/test_setup.sh` (numpy/scipy, google-genai, pydantic)

### Commit 2 — `agno.banavo` extensions package
- Moves Banavo Agent/Team runtime, models, memory, run events, and utils into `agno.banavo.*`
- `agno.banavo.tools` re-exports upstream `agno.tools` (no duplicate copy)
- banavo-agent-os deletes local `agno_custom/` and imports from this package

**Note:** `agno.banavo.agent` / `agno.banavo.team` still use the V1 `RunResponse` runtime.
A follow-up PR will thin these to subclasses of upstream `agno.agent.Agent` /
`agno.team.Team` after banavo streaming migrates to V2 run events.

### Motivation
- Session persistence broke with no-op storage after agno 2.x upgrade
- Banavo needs GPT-5 Responses API `provider_data` across Postgres round-trips
- Reviewer feedback: avoid 23k-line copy-paste; keep patches in the agno repo

Internal Banavo fork PR — not necessarily intended for upstream merge as-is.
Related: andromeda360/agno `banavo/agno-patches-2.6.9`, banavo-agent-os `progress_test/agno_upgrade_2.6.9`.

## Type of change

- [x] Bug fix
- [x] Improvement
- [ ] New feature
- [ ] Breaking change

## Checklist

- [x] Code complies with style guidelines
- [x] Self-review completed
- [x] Tested with banavo-agent-os import validation (`validate_agent_imports.py`)
- [ ] Ran `./scripts/format.sh` and `./scripts/validate.sh` (run before merge)
- [ ] Tests added/updated (agno unit tests — run on CI)

## Test plan

- [ ] `./scripts/test_setup.sh && pytest libs/agno/tests/unit` (exclude litellm/crawl4ai/scrapegraph)
- [ ] banavo-agent-os: `uv sync && python scripts/validate_agent_imports.py`
- [ ] banavo-agent-os: `uv run poe prod --port 8080` — server starts, follow-up chat persists
