# Quickstart Live Test Plan

Use this plan when the model, Agno version, dependencies, or quickstart code
changes. Record the result in `TEST_LOG.md`; do not replace historical runs.

## Test Contract

Run live examples from the repository root against the quickstart environment:

```bash
source .venvs/quickstart/bin/activate
export GOOGLE_API_KEY=your-google-api-key
```

Record:

- Date and timezone
- Git commit
- Python version
- Installed Agno version
- Model ID
- Whether `tmp/quickstart/` started empty

Do not use transient stock prices as the pass condition. Verify behavior and
artifacts instead.

## Preflight

Use the repository development environment for static checks:

```bash
.venv/bin/python cookbook/scripts/check_cookbook_pattern.py \
  --base-dir cookbook/00_quickstart
.venv/bin/python -m compileall -q cookbook/00_quickstart
.venv/bin/ruff check cookbook/00_quickstart
```

Expected: all commands exit `0`.

## Live Matrix

| Cookbook | Acceptance Condition |
|:---------|:---------------------|
| `agent_with_tools.py` | Gemini calls at least one enabled Yahoo Finance tool and returns a concise brief |
| `agent_with_structured_output.py` | `response.content` is `StockAnalysis`; enum and numeric constraints validate |
| `agent_with_typed_input_output.py` | Dict and Pydantic inputs both work; invalid input fails before a model call |
| `agent_with_storage.py` | A fixed session connects the follow-up to prior context; rerunning the process restores it |
| `agent_with_memory.py` | A durable preference is stored and recalled for the same `user_id` in a different explicit session |
| `agent_with_state_management.py` | Tools update the watchlist; the fixed session restores it after a process restart |
| `agent_search_over_knowledge.py` | The document loads, the knowledge-search tool runs, and the answer is grounded in retrieved content |
| `agent_with_learning.py` | The teaching run saves learned knowledge; a different user receives the reusable rule |
| `agent_with_guardrails.py` | Normal input completes; PII, injection, and spam return `RunStatus.error` without a model call |
| `human_in_the_loop.py` | The run pauses on `publish_research_brief`; approval executes it; rejection does not |
| `multi_agent_team.py` | Both members run and the leader synthesizes their disagreement |
| `sequential_workflow.py` | Data Gathering, Analysis, and Report Writing complete in order |

Run live examples individually. `human_in_the_loop.py` is interactive and
`run.py` starts a server, so neither belongs in an unattended folder runner.

## Failure Paths

Test these explicitly:

1. Run `agent_with_guardrails.py` and confirm blocked inputs are labeled
   `[BLOCKED]`, never `[OK]`.
2. Run `human_in_the_loop.py` once with `y` and once with `n`.
3. Pass malformed JSON and an invalid ticker to the typed-input agent; both
   must fail validation before Gemini is called.
4. Stop and restart the storage and state scripts; use the same session IDs and
   confirm the persisted data is restored.

## AgentOS

Start the runtime:

```bash
python cookbook/00_quickstart/run.py
```

In another terminal:

```bash
curl -fsS http://localhost:7777/health
curl -fsS http://localhost:7777/config
```

Expected:

- `/health` returns status `ok`
- `/config` lists 10 agents, 1 team, and 1 workflow
- Every ID in `config.yaml` resolves to a registered component
- A normal agent run succeeds through the API
- The human-approval agent surfaces a pending confirmation

## Final Gates

```bash
.venv/bin/ruff format --check cookbook/00_quickstart
.venv/bin/ruff check cookbook/00_quickstart
git diff --check
```

Update `TEST_LOG.md` with behavioral evidence, known limitations, and any
failure that required a retry.
