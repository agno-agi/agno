# Test Log: 09_evals

**Test date:** 2026-08-24
**Branch:** eval-run-id (per-execution `run_id`; the per-instance `eval_id` field has been removed from `AccuracyEval` / `PerformanceEval` / `ReliabilityEval`)

## How this log was produced

Every `.py` file under `cookbook/09_evals/` was executed once from the repo root with a 300s
per-file timeout, stdin closed, and stdout+stderr captured. Statuses below are taken from the
real process output, not from inspection.

**Environment caveats — read before trusting a status:**

- **Interpreter:** `.venv/bin/python` (Python 3.12.12). `CLAUDE.md` prescribes `.venvs/demo`, but
  that virtualenv does not exist in this worktree, so the dev venv was used instead. The dev venv
  does **not** carry the third-party agent frameworks, which is why every file under
  `performance/comparison/` fails on import here.
- **Library versions:** `agno 3.0.0a2`, `openai 3.3.1`, `anthropic 0.76.0`, `psycopg 3.3.4`,
  `sqlalchemy 2.0.52`. `anthropic` is installed but unused — every cookbook in this folder runs on
  OpenAI models only.
- **Postgres:** `cookbook/scripts/run_pgvector.sh` publishes the container on host port **5532**.
  The cookbooks are split on which port they ask for: the three `db_logging.py` files hardcode
  `localhost:5432`, while `agent_as_judge_basic.py` and the three `performance/team_response_*`
  files use `localhost:5532`. On this machine 5532 serves `ai/ai/ai` correctly; port 5432 is a
  different, unrelated Postgres that rejects the `ai` user. The three `db_logging.py` files are
  therefore recorded as FAIL for exactly that reason. They were not edited.
- **API keys:** `OPENAI_API_KEY` and `ANTHROPIC_API_KEY` were present in the environment.

## Summary

| Result | Count |
|--------|-------|
| PASS | 33 |
| FAIL | 9 |
| TIMEOUT | 0 |
| NOT RUN | 0 |
| Package markers (`__init__.py`, empty, exit 0) | 10 |
| **Total `.py` files** | **52** |

The 9 failures are the 6 `performance/comparison/*` files (missing third-party frameworks in this
venv) and the 3 `db_logging.py` files (Postgres port 5432 vs 5532).

## Findings relevant to the `run_id` change

1. **No cookbook in this folder still references `eval_id`.** A full-text search over
   `cookbook/09_evals/` returns zero hits. The five call sites that print an identifier already read
   the new field (`latest.run_id`).
2. **Reruns create a distinct row — no duplicate-key swallow.** Re-running
   `agent_as_judge/agent_as_judge_batch.py` took `tmp/agent_as_judge_batch.db` from 1 to 2
   `agno_eval_runs` rows with distinct ids (`7931dc33-…` then `05715e6d-…`). On the real Postgres at
   5532, `ai.agno_eval_runs` holds four separate rows for the eval named `Explanation Quality`
   (2026-08-19, 08-23, and two on 08-24), each with its own `run_id`.
3. **The `Eval ID:` lines printed the wrong run once a DB held more than one row -- fixed here.**
   Seven sites across six files took `eval_runs[-1]` after `db.get_eval_runs()`:
   `agent_as_judge_basic.py` (twice), `agent_as_judge_batch.py`, `agent_as_judge_post_hook.py`,
   `agent_as_judge_team.py`, `agent_as_judge_team_post_hook.py` and
   `agent_as_judge_with_guidelines.py`. That helper orders `created_at` descending, so `[-1]`
   was the *oldest* run, not the newest. Observed live before the fix: the batch rerun stored
   `05715e6d-…` while printing `Eval ID: 7931dc33-…` from the previous run, and
   `agent_as_judge_basic.py` printed a `run_id` first written on 2026-08-19. The two post-hook
   files print a score rather than an id, so they were reading the oldest run's `eval_data`.
   All seven now index `[0]`, and the five that print an id say `Run ID:` -- `eval_id` no longer
   exists on `EvalRunRecord`. Re-verified by running two of them twice: `agent_as_judge_batch.py`
   printed `c71235c9-…` and `agent_as_judge_with_guidelines.py` printed `b50b2d90-…`, each the
   row that run had just written.
4. **No cookbook anywhere under `cookbook/` sets `file_path_to_save_results`,** so this folder gives
   the placeholder no coverage. Probed out-of-tree instead: `{run_id}` resolves to the
   per-execution UUID (file written as `<name>_<uuid>.json`, and the eval `name` is interpolated
   verbatim, spaces included), and the legacy `{eval_id}` spelling still resolves to the same
   value. Both files were written to disk.
5. **DB failures are non-fatal.** All three `db_logging.py` files exit 0 with the connection error
   only logged as `ERROR`/`WARNING`, so a broken DB target does not fail the process — the reason
   they are marked FAIL here on evidence rather than on exit code.

---

## accuracy/

### accuracy_9_11_bigger_or_9_99.py

**Status:** PASS

**Description:** Single-iteration `AccuracyEval` asking whether 9.11 or 9.9 is bigger.

**Result:** Ran in 6.7s. Output "9.9 is bigger than 9.11", Accuracy Score 10/10, summary reports 1 run with average/min/max 10.00 and std dev 0.00.

---

### accuracy_basic.py

**Status:** PASS

**Description:** Three-iteration `AccuracyEval` over a calculator agent ("What is 10*5 then to the power of 2?").

**Result:** Ran in 28.2s. All three iterations scored 10/10; summary reports Number of Runs 3, Average Score 10.00, Std Dev 0.00.

---

### accuracy_eval_metrics.py

**Status:** PASS

**Description:** Accuracy eval that then prints the combined agent + evaluator token metrics.

**Result:** Ran in 3.6s. Score 10/10; "Total tokens (agent + eval): 604", agent 32 / eval 572, with the full `details` breakdown printed for both `gpt-4o-mini` entries (`model` and `eval_model`).

---

### accuracy_team.py

**Status:** PASS

**Description:** `AccuracyEval` against a Team, checking the language-restriction reply to "Comment allez-vous?".

**Result:** Ran in 4.5s. Team output matched the expected string word-for-word, Accuracy Score 10/10, 1 run averaging 10.00.

---

### accuracy_with_given_answer.py

**Status:** PASS

**Description:** Scores a pre-supplied answer string instead of running an agent.

**Result:** Ran in 4.0s. Output "2500" vs expected "2500", Accuracy Score 10/10, 1 run averaging 10.00.

---

### accuracy_with_tools.py

**Status:** PASS

**Description:** Accuracy eval over an agent with `CalculatorTools` ("What is 10!?").

**Result:** Ran in 6.3s. Output "10! = 3,628,800", Accuracy Score 10/10 (judge explicitly excused the comma formatting), 1 run averaging 10.00.

---

### db_logging.py

**Status:** FAIL

**Description:** Meant to store an `AccuracyEval` result in PostgreSQL via `PostgresDb(eval_table="eval_runs_cookbook")`.

**Result:** Ran in 7.4s and exited 0, but logged nothing. The file hardcodes `postgresql+psycopg://ai:ai@localhost:5432/ai` while the repo's `run_pgvector.sh` publishes 5532, so every DB call failed with `(psycopg.OperationalError) connection failed: connection to server at "127.0.0.1", port 5432 failed: FATAL: password authentication failed for user "ai"` — repeated as `Error checking if table exists`, `Could not create schema ai`, `Could not create table ai.eval_runs_cookbook`, `Error creating eval run`, and finally `WARNING Could not log eval run`. The eval itself scored 10/10 before the DB writes were attempted. Not edited; failing purely on the port mismatch.

---

### evaluator_agent.py

**Status:** PASS

**Description:** Accuracy eval driven by a custom evaluator agent rather than a bare model.

**Result:** Ran in 10.0s. Agent produced the step-by-step 2500 answer, Accuracy Score 10/10, 1 run averaging 10.00.

---

## agent_as_judge/

### agent_as_judge_basic.py

**Status:** PASS

**Description:** Sync judge backed by `PostgresDb` on port 5532 plus an async judge backed by `AsyncSqliteDb`, both with an `on_fail` callback.

**Result:** Ran in 16.1s. Sync: Score 9/10 PASSED (threshold 7), then "Total evaluations stored: 5" from Postgres. Async: Score 9/10 against threshold 10, so the `on_fail` callback fired and printed "Evaluation failed - Score: 9/10" and the summary showed Pass Rate 0.0% — that is the demo behaving as written, not an error. `tmp/agent_as_judge_async.db` ended with 2 `agno_eval_runs` rows. Caveat: the printed `Eval ID: 09ddcbe2-…` is the *oldest* Postgres row (first written 2026-08-19), not this run — see finding 3.

---

### agent_as_judge_batch.py

**Status:** PASS

**Description:** Batch judge over three customer-service responses, persisted to `tmp/agent_as_judge_batch.db`.

**Result:** Ran in 11.3s. All three cases PASSED, "Pass rate: 100.0%", "Passed: 3/3", "Cases evaluated: 3", one `agno_eval_runs` row written. Re-run to test the `run_id` change: row count went 1 → 2 with a new id (`05715e6d-…`), no duplicate-key warning — but the script still printed the previous run's id because of the `[-1]` indexing described in finding 3.

---

### agent_as_judge_binary.py

**Status:** PASS

**Description:** Binary (pass/fail) scoring strategy on a support reply, stored in `tmp/agent_as_judge_binary.db`.

**Result:** Ran in 6.3s. Status PASSED, Pass Rate 100.0%, final line "Result: PASSED"; 1 eval row persisted.

---

### agent_as_judge_custom_evaluator.py

**Status:** PASS

**Description:** Judge configured with a custom evaluator agent.

**Result:** Ran in 6.0s. Score 9/10, Status PASSED, trailing prints "Score: 9/10" and "Passed: True".

---

### agent_as_judge_eval_metrics.py

**Status:** PASS

**Description:** Prints the token/latency metrics attached to an agent-as-judge result.

**Result:** Ran in 4.1s. "Total tokens (agent + eval): 378" (agent 31 / eval 347), evaluator identified as `gpt-4o-mini (OpenAI Chat)`, full metrics dict printed including `additional_metrics.eval_duration`.

---

### agent_as_judge_post_hook.py

**Status:** PASS

**Description:** Runs the judge from an agent post-hook, in both a sync (`SqliteDb`) and an async (`AsyncSqliteDb`) variant.

**Result:** Ran in 19.6s. Sync: "Evaluation Results: Score: 9/10 / Status: PASSED". Async: "Async Evaluation Results: Score: 9/10 / Status: PASSED". One `agno_eval_runs` row in each of `tmp/agent_as_judge_post_hook.db` and `tmp/agent_as_judge_post_hook_async.db`.

---

### agent_as_judge_team.py

**Status:** PASS

**Description:** Judges a Team response about quantum computing and reads the stored run back out of `tmp/agent_as_judge_team.db`.

**Result:** Ran in 23.6s. Status PASSED, Pass Rate 100.0%, "Total evaluations stored: 1", "Team: Research Team". The DB file ended with 1 eval row and 3 agent/team runs.

---

### agent_as_judge_team_post_hook.py

**Status:** PASS

**Description:** Team post-hook variant of the judge.

**Result:** Ran in 27.6s. "Evaluation Results: Score: 8/10 / Status: PASSED"; 1 eval row and 3 runs written to `tmp/agent_as_judge_team_post_hook.db`.

---

### agent_as_judge_with_guidelines.py

**Status:** PASS

**Description:** Judge with three `additional_guidelines`, persisted to `tmp/agent_as_judge_guidelines.db`.

**Result:** Ran in 8.0s. Score 8/10, Status PASSED, "Total evaluations stored: 1", "Additional guidelines used: 3".

---

### agent_as_judge_with_tools.py

**Status:** PASS

**Description:** Judges a calculator agent's answer to "What is 15 * 23 + 47?" against a criteria demanding visible intermediate steps.

**Result:** Ran in 7.2s and exited 0. The judge verdict was Score 3/10, Status FAILED — the agent answered "392" without showing steps. The script only asserts `result is not None`, so a low score is a legitimate demo outcome, not a script error. Verdict is model-dependent and may differ per run.

---

## performance/

### async_function.py

**Status:** PASS

**Description:** `PerformanceEval` over an awaited async agent call, 10 iterations.

**Result:** Ran in 31.2s. All 10 runs tabulated; Average 0.901684s / 0.375205 MiB, Min 0.834768s, Max 1.002490s, Std Dev 0.052949.

---

### db_logging.py

**Status:** FAIL

**Description:** Meant to store a `PerformanceEval` result in PostgreSQL via `PostgresDb(eval_table="eval_runs_cookbook")`.

**Result:** Ran in 4.0s and exited 0; the benchmark itself completed (1 run, 1.466058s / 1.047235 MiB) but nothing was persisted. Hardcodes `localhost:5432` while the repo script publishes 5532, so the run ended with `ERROR Error creating eval run: (psycopg.OperationalError) connection failed: connection to server at "127.0.0.1", port 5432 failed: FATAL: password authentication failed for user "ai"` followed by `WARNING Could not log eval run: …`. Not edited.

---

### instantiate_agent.py

**Status:** PASS

**Description:** 1000-iteration benchmark of bare `Agent` instantiation.

**Result:** Ran in 6.0s. Average 0.000004s / 0.004965 MiB, Min 0.000004s, Max 0.000008s, Std Dev 0.000000.

---

### instantiate_agent_with_tool.py

**Status:** PASS

**Description:** 1000-iteration benchmark of `Agent` instantiation with a tool attached.

**Result:** Ran in 21.7s. Average 0.000007s / 0.006649 MiB, Min 0.000006s, Max 0.000054s.

---

### instantiate_team.py

**Status:** PASS

**Description:** 1000-iteration benchmark of `Team` instantiation.

**Result:** Ran in 21.3s. Average 0.000010s / 0.005750 MiB, Min 0.000010s, Max 0.000056s.

---

### response_with_memory_updates.py

**Status:** PASS

**Description:** 5-iteration benchmark of an agent run with memory updates against `tmp/memory.db`.

**Result:** Ran in 15.6s. Agent replied "Hi Tom—nice to meet you…"; Average 1.524017s / 0.349082 MiB, Min 1.080109s, Max 2.913651s (first run warm-up dominates).

---

### response_with_storage.py

**Status:** PASS

**Description:** Single-iteration benchmark of an agent run persisted to `tmp/storage.db`.

**Result:** Ran in 6.5s. Four agent responses printed (capital of France / population); 1 run at 2.455465s / 0.282310 MiB.

---

### simple_response.py

**Status:** PASS

**Description:** Single-iteration benchmark of a plain agent response.

**Result:** Ran in 3.3s. Two "Agent response:" lines printed; 1 run at 1.070905s / 1.046144 MiB.

---

### team_response_with_memory_and_reasoning.py

**Status:** PASS

**Description:** Memory-growth benchmark (`measure_runtime=False`) of a Team with memory and reasoning, backed by Postgres on 5532.

**Result:** Ran in 1.9s and exited 0, printing 5 memory rows (Average 0.086880 MiB, Min 0.013934, Max 0.378652). The process succeeded, but **the benchmark does no work**: lines 1064–1075 call `team.arun(...)` four times and assign the result to `_` without awaiting it, so no model call is ever made. The near-zero memory deltas and the 1.9s wall clock confirm it. Reported, not fixed.

---

### team_response_with_memory_multi_user.py

**Status:** PASS

**Description:** Memory-growth benchmark of concurrent multi-user Team runs against Postgres on 5532; this is the one file in the trio that does `await team.arun(...)` and `asyncio.gather`.

**Result:** Ran in 63.5s — real model traffic. 5 runs: Average 6.397702 MiB, Min 2.237964, Max 22.724978 (first iteration), Median 2.309915.

---

### team_response_with_memory_simple.py

**Status:** PASS

**Description:** Memory-growth benchmark of a Team with memory enabled, Postgres on 5532.

**Result:** Ran in 1.9s and exited 0 with 5 memory rows (Average 0.078935 MiB, Min 0.005336, Max 0.373071). Same defect as the reasoning variant: `run_team()` does `_ = team.arun(..., stream=True, stream_events=True)` and never consumes the stream, so no team run actually executes and the numbers measure nothing. Reported, not fixed.

---

## performance/comparison/

All six files fail identically in this worktree: the dev venv (`.venv`) has none of the competing
agent frameworks installed, and `.venvs/demo` — the environment `CLAUDE.md` intends for cookbooks —
does not exist here. Nothing about these files is specific to the `run_id` change.

The FAIL statuses below are therefore about this environment, not about the files. Re-run in a
throwaway virtualenv carrying agno 3.0.0a4 built from this worktree plus langgraph 1.2.11,
crewai 1.6.1, pydantic-ai-slim 2.31.1, openai-agents 0.20.0, smolagents 1.26.0 and
autogen-agentchat 0.7.5, all six complete 1000 measured iterations with no exceptions:

| File | Median (s) | p95 (s) | Median memory (MiB) |
|---|---|---|---|
| `openai_agents_instantiation.py` | 0.000355 | 0.000440 | 0.057710 |
| `langgraph_instantiation.py` | 0.001562 | 0.001878 | 0.142066 |
| `smolagents_instantiation.py` | 0.003669 | 0.004106 | 0.259882 |
| `autogen_instantiation.py` | 0.004035 | 0.004786 | 0.024355 |
| `pydantic_ai_instantiation.py` | 0.004084 | 0.005308 | 0.042462 |
| `crewai_instantiation.py` | 0.004670 | 0.006230 | 1.491657 |

For scale, `instantiate_agent_with_tool.py` measured 0.000006 s median / 0.006653 MiB in that
same venv and session. `langgraph_instantiation.py` also emits one deprecation warning:
`create_react_agent has been moved to langchain.agents` (LangGraph V1.0, removal in V2.0).

### autogen_instantiation.py

**Status:** FAIL

**Description:** Benchmarks AutoGen `AssistantAgent` instantiation for comparison against Agno.

**Result:** Exited 1 in 0.3s: `ModuleNotFoundError: No module named 'autogen_agentchat'` at line 11, `from autogen_agentchat.agents import AssistantAgent`.

---

### crewai_instantiation.py

**Status:** FAIL

**Description:** Benchmarks CrewAI `Agent` instantiation.

**Result:** Exited 1 in 0.3s: `ModuleNotFoundError: No module named 'crewai'` at line 11, `from crewai.agent import Agent`.

---

### langgraph_instantiation.py

**Status:** FAIL

**Description:** Benchmarks LangGraph react-agent instantiation.

**Result:** Exited 1 in 0.3s: `ModuleNotFoundError: No module named 'langchain_core'` at line 11, `from langchain_core.tools import tool`.

---

### openai_agents_instantiation.py

**Status:** FAIL

**Description:** Benchmarks OpenAI Agents SDK agent instantiation.

**Result:** Exited 1 in 0.2s. The file's own guard raised at line 15: `ImportError: OpenAI agents not installed. Please install it using 'uv pip install openai-agents'.`

---

### pydantic_ai_instantiation.py

**Status:** FAIL

**Description:** Benchmarks Pydantic-AI `Agent` instantiation.

**Result:** Exited 1 in 0.2s: `ModuleNotFoundError: No module named 'pydantic_ai'` at line 11, `from pydantic_ai import Agent`.

---

### smolagents_instantiation.py

**Status:** FAIL

**Description:** Benchmarks smolagents `ToolCallingAgent` instantiation.

**Result:** Exited 1 in 0.2s: `ModuleNotFoundError: No module named 'smolagents'` at line 9, `from smolagents import InferenceClientModel, Tool, ToolCallingAgent`.

---

## reliability/

### db_logging.py

**Status:** FAIL

**Description:** Meant to store a `ReliabilityEval` result in PostgreSQL via `PostgresDb(eval_table="eval_runs")`.

**Result:** Ran in 4.3s and exited 0. The reliability check itself passed — "Evaluation Status PASSED, Failed Tool Calls [], Passed Tool Calls ['factorial']" — but every DB call failed against the hardcoded `localhost:5432` (repo script publishes 5532): `ERROR Error checking if table exists`, `WARNING Could not create schema ai`, `ERROR Error creating eval run`, `WARNING Could not log eval run`, each with `(psycopg.OperationalError) connection failed: connection to server at "127.0.0.1", port 5432 failed: FATAL: password authentication failed for user "ai"`. Not edited.

---

### reliability_async.py

**Status:** PASS

**Description:** `ReliabilityEval.arun` asserting the agent called `factorial`.

**Result:** Ran in 4.4s. Evaluation Status PASSED, Failed Tool Calls `[]`, Passed Tool Calls `['factorial']`.

---

### multiple_tool_calls/calculator.py

**Status:** PASS

**Description:** Reliability over a multi-step calculator request, including an "additional tool calls" variant.

**Result:** Ran in 8.7s. First check PASSED with Passed Tool Calls `['multiply', 'exponentiate']`; second check PASSED with Passed `['multiply']` and Additional Tool Calls `['exponentiate']`.

---

### single_tool_calls/calculator.py

**Status:** PASS

**Description:** Reliability over single tool calls, second case also asserting call arguments.

**Result:** Ran in 5.5s. First check PASSED with `['factorial']`; second check PASSED with Passed Tool Calls `['multiply']` and Passed Argument Checks `['multiply']`.

---

### team/ai_news.py

**Status:** PASS

**Description:** Reliability over a Team that must delegate and search for AI news.

**Result:** Ran in 17.2s. Evaluation Status PASSED, Failed Tool Calls `[]`, Passed Tool Calls `['delegate_task_to_member', 'search_news']`.

---

## suite/

### suite_basic.py

**Status:** PASS

**Description:** Two `Case`s (judge + reliability) driven through the built-in `cli()` entry point, run with no CLI arguments.

**Result:** Ran in 12.0s, exit 0. `factorial_uses_calculator` — tools fired `factorial`, Judge PASS, Reliability PASS. `explains_compound_interest` — Judge PASS. Eval Summary table shows both rows PASS; final line "2/2 passed".

---

### suite_team_scoring.py

**Status:** PASS

**Description:** Same suite shape but with a Team as the subject, including delegation reliability.

**Result:** Ran in 21.6s, exit 0. `team_uses_calculator` — Judge PASS, Reliability PASS (tools fired `delegate_task_to_member`). `team_explains_clearly` — Judge PASS. Final line "2/2 passed".

---

## Package markers

### __init__.py (10 files)

**Status:** PASS

**Description:** `cookbook/09_evals/__init__.py` plus the `accuracy/`, `agent_as_judge/`, `performance/`, `performance/comparison/`, `reliability/`, `reliability/multiple_tool_calls/`, `reliability/single_tool_calls/`, `reliability/team/` and `suite/` package markers.

**Result:** All ten are 0 bytes and each exits 0 when executed. Nothing to test.

---
