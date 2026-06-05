# Demo AgentOS Test Log

Last updated: 2026-06-05

## Test Environment

- Python: `.venvs/demo/bin/python`
- Model: gpt-5.5 (agents + eval judge)
- Database: local SQLite at `data/demo.db`
- Backends enabled (via local `.envrc`): OpenAI, Parallel, Google, Git wiki
  (`WIKI_REPO_URL` + `WIKI_GITHUB_TOKEN`), Notion wiki (`NOTION_API_KEY` +
  `NOTION_DATABASE_ID`) — so all three wiki backends were exercised.

---

## Static Checks

### App build (`run.py`)

**Status:** PASS

**Description:** Imported `run` in the demo venv with no backend creds set;
confirmed the FastAPI app builds and registers the expected agents.

**Result:** `LocalWiki` + `CodeSearch` register; `GitWiki` / `NotionWiki`
correctly skipped when their env vars are absent. Tools resolve
(`query_local_wiki`, `update_local_wiki`). No import or construction errors.

### Lint / format

**Status:** PASS

**Description:** `ruff format --check` and `ruff check` over the cookbook.

**Result:** 11 files already formatted; all checks passed.

> Note: `cookbook/scripts/check_cookbook_pattern.py` reports
> `missing_main_gate` / `missing_sections` for the agent and support modules.
> These assume standalone runnable scripts; `01_demo` is a served application
> (imported modules + `run.py`), so those advisory checks do not apply. The
> checker is not wired into `validate.sh` or CI.

---

## Eval Suite (`python -m evals`)

**Status:** PASS — 6/6

Each case runs one agent once, then checks the response with `AgentAsJudgeEval`
(LLM rubric, binary) and, where set, `ReliabilityEval` (tool-call assertion).

| Case | Agent | Judge | Reliability |
|------|-------|-------|-------------|
| `local_wiki_reports_state_honestly` | LocalWiki | PASS | PASS |
| `local_wiki_ingests_image` | LocalWiki | PASS | PASS |
| `code_search_lists_registered_agents` | CodeSearch | PASS | PASS |
| `code_search_admits_unknown_function` | CodeSearch | PASS | — |
| `git_wiki_reports_state_honestly` | GitWiki | PASS | PASS |
| `notion_wiki_reports_state_honestly` | NotionWiki | PASS | PASS |

### local_wiki_reports_state_honestly

**Status:** PASS

**Description:** Asks the LocalWiki about a topic the wiki has no page on.
Verifies the read tool fires and the agent reports the empty state honestly
rather than fabricating a page.

**Result:** `query_local_wiki` fired; agent stated no matching page exists.

### local_wiki_ingests_image

**Status:** PASS

**Description:** Attaches `assets/sample-diagram.png` and asks the agent to
digest it into structured markdown and file a page under `notes/`.

**Result:** Agent read the image (did not claim it couldn't), produced a
structured digest, and `update_local_wiki` fired to file the page.

### code_search_lists_registered_agents

**Status:** PASS

**Description:** Asks CodeSearch which agents are registered in this demo.

**Result:** `query_codebase` fired; response named the demo agents.

### code_search_admits_unknown_function

**Status:** PASS

**Description:** Asks for the definition site of a function that does not exist.

**Result:** Agent said the function is not defined in the project rather than
inventing a location. (Judge-only; no tool-call assertion.)

### git_wiki_reports_state_honestly

**Status:** PASS

**Description:** Read-only honesty check against the Git-backed wiki (gated on
`WIKI_REPO_URL` + `WIKI_GITHUB_TOKEN`).

**Result:** `query_git_wiki` fired; agent reported wiki state honestly. No write
occurred (read-only case).

### notion_wiki_reports_state_honestly

**Status:** PASS

**Description:** Read-only honesty check against the Notion-backed wiki (gated on
`NOTION_API_KEY` + `NOTION_DATABASE_ID`).

**Result:** `query_notion_wiki` fired; agent reported wiki state honestly. No
write occurred (read-only case).

---

## Notes

- The Git and Notion eval cases are read-only by design, so running the suite
  does not push pages to a real repo or Notion database.
- Local wiki pages, the Git clone, and the Notion mirror all live under `data/`
  (gitignored); fresh clones self-seed on first run.
</content>
</invoke>
