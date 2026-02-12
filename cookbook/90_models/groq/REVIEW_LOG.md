# REVIEW_LOG — groq

## v2.5 Review — 2026-02-11

### Framework Issues

#### 1. groq.py — No credential fail-fast (shared pattern)
`Groq.__post_init__()` does not validate that `GROQ_API_KEY` is set. Same pattern as Claude and Gemini.

#### 2. base.py:257 — kwargs mutation in invoke() (shared with anthropic)
See anthropic REVIEW_LOG for details.

---

### Cookbook Quality Notes

#### Import path fix applied
`agent_team.py` used stale import `from agno.team.team import Team`. Fixed to `from agno.team import Team`. This was the only v2.5 compat fix needed in Batch 1.

#### Wrong provider in groq/ section
`transcription_agent.py` and `translation_agent.py` use `OpenAIChat` (not Groq) as the model. They're placed in the groq/ directory but don't actually use Groq models. Should either use Groq's Whisper endpoint or be moved to a more appropriate location.

#### Missing dependency
`research_agent_seltz.py` requires `seltz` package which isn't in demo requirements. Should be added to demo dependencies or the cookbook should document the install step.

#### Interactive cookbook not runnable in batch
`deep_knowledge.py` uses `typer` + `inquirer` for interactive terminal input. Can't be tested in automated batch runs.

#### Top-level execution
Some cookbooks execute at module level. Less prevalent than in anthropic/gemini directories.

---

### v2.5 Compatibility

**Status:** 1 fix applied.

| File | Issue | Fix |
|------|-------|-----|
| agent_team.py | `from agno.team.team import Team` | Changed to `from agno.team import Team` |

---

### Fixes Applied

1. `agent_team.py:10` — Import path: `from agno.team.team import Team` → `from agno.team import Team`

---

### Summary
- **20 files tested:** 18 PASS, 1 FAIL, 1 SKIP
- **Framework issues:** 1 (credential fail-fast)
- **Cookbook quality issues:** 3 (wrong provider x2, missing dependency, interactive cookbook)
- **v2.5 compat fixes:** 1 (agent_team.py import path)
