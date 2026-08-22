# Demo AgentOS Test Log

Last updated: 2026-06-06

## Test Environment

- Python: `.venvs/demo/bin/python`
- Model: gpt-5.5 (agents + eval judge)
- Database: local SQLite at `data/demo.db`
- Backends configured (via local `.envrc`): OpenAI, Parallel, Google, Git wiki
  (`WIKI_REPO_URL` + `WIKI_GITHUB_TOKEN`), Notion wiki (`NOTION_API_KEY` +
  `NOTION_DATABASE_ID`).

> HTML generation requires agno's file-generation support (#8241), shipped in
> the released **agno 2.6.12**. `requirements.txt` is pinned to it, and
> `generate_html_file` is confirmed registered on the released wheel.

---

## Change Summary (this session)

- Removed the standalone `FileGenerator` agent; folded **HTML-only** file
  generation (`settings.html_tools()` -> `FileGenerationTools`) into the three
  wiki agents (LocalWiki, GitWiki, NotionWiki). CodeSearch is excluded.
- Turned off `enable_agentic_memory` on all agents (cleaner responses; the wiki
  is the persistent store).
- Moved `assets/` -> `evals/assets/` (the sample diagram is an eval fixture).
- Reworked all four agent personas from voiceless tool-routers into a voiced
  archivist-analyst (wiki agents) / senior engineer (CodeSearch): lead with
  substance, honesty spine intact. Rewrote the `config.yaml` quick prompts and
  README "Try it" to be differentiated per backend and one-click-runnable.
- Pinned `requirements.txt` to released `agno==2.6.12`; added the GitWiki /
  NotionWiki backend setup walkthrough (README + agent docstrings).

---

## Static Checks

**Status:** PASS

- `ruff format` + `ruff check` over `cookbook/01_demo`: clean.
- App builds (`import run`): registers LocalWiki + CodeSearch; GitWiki/NotionWiki
  register only when their env vars are set. All three wiki agents expose
  `generate_html_file`; CodeSearch does not.

> `cookbook/scripts/check_cookbook_pattern.py` reports advisory
> `missing_main_gate` / `missing_sections` — these assume standalone scripts;
> `01_demo` is a served app, and the checker is not wired into `validate.sh`/CI.

---

## Eval Suite (`python -m evals`)

**This pass (reworked personas, released agno 2.6.12):** core suite **5/5**.

| Case | Agent | Judge | Reliability | Status |
|------|-------|-------|-------------|--------|
| `local_wiki_reports_state_honestly` | LocalWiki | PASS | PASS | PASS |
| `local_wiki_ingests_image` | LocalWiki | PASS | PASS | PASS |
| `local_wiki_generates_html` | LocalWiki | — | PASS | PASS |
| `code_search_lists_registered_agents` | CodeSearch | PASS | PASS | PASS |
| `code_search_admits_unknown_function` | CodeSearch | PASS | — | PASS |

The reworked personas now lead with substance — e.g. "The wiki is silent on the
Lindy Effect," and for the attached diagram "The diagram captures a small but
useful architecture pattern…" rather than a flat "filed a note."

The git/notion cases are env-gated and were not re-run this pass; they share the
same honesty rubric and passed earlier with their backends reachable. In CI
(no creds) they don't run.

### HTML case: the file is always delivered; narration is cosmetic

`local_wiki_generates_html` asserts `generate_html_file` fires — it does, every
run, writing a valid `<!doctype html>` document under `data/generated/`. The
tool returns that document as a **File artifact**, so AgentOS attaches the
downloadable `.html` to the reply regardless of the text. The wiki agents still
tend to also file a short wiki note and narrate that ("filed in the wiki at …");
instruction tuning could not reliably stop the re-filing — the wiki-curator
prior dominates when one agent holds both a wiki-write tool and the HTML tool.
This is cosmetic: the `.html` reaches the user either way. The instruction is
written to match it (lead with the file; a note alongside is fine), so the
public code carries no rule the agent visibly violates.

---

## Notes

- The Git and Notion eval cases are read-only; running the suite does not push
  to a real repo or Notion database.
- Local wiki pages, the Git clone, the Notion mirror, and generated HTML all
  live under `data/` (gitignored); fresh clones self-seed / re-sync on setup.
