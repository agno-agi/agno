# TEST_LOG

Tested 2026-08-31 against `gpt-oss-120b`, agno @ main (1b7800746), with a live
`CEREBRAS_API_KEY` (and `OPENAI_API_KEY` for the embedder) and Postgres started
via `cookbook/scripts/run_pgvector.sh`. `oss_gpt.py` was not run.

### basic.py

**Status:** PASS

**Description:** Runs the same prompt through all four variants: sync,
sync + streaming, async, and async + streaming.

**Result:** All four variants returned complete responses.

---

### db.py

**Status:** PASS

**Description:** Two sequential questions with `add_history_to_context=True`
and session history persisted through `PostgresDb`.

**Result:** Both questions answered; the second ("What is their national anthem
called?") correctly resolved "their" to Canada from the persisted history.

---

### knowledge.py

**Status:** PASS

**Description:** Inserts the Thai recipes PDF into PgVector (OpenAI embedder),
then asks the agent a question answerable only from the PDF.

**Result:** 14 documents upserted; the agent retrieved 10 documents and
answered the Thai curry question with the recipe content from the PDF, citing
the cookbook page.

---

### structured_output.py

**Status:** PASS

**Description:** Structured output via `output_schema=MovieScript`.

**Result:** Returned a valid `MovieScript` JSON object. No strict-mode
complaints from the API.

---

### tool_use.py

**Status:** PASS (transient rate limiting disclosed)

**Description:** Web-search tool use through all four variants (sync,
sync + streaming, async, async + streaming).

**Result:** Across two full passes: the first pass completed all four variants
cleanly; the second pass completed 2 of 4, with the other two failing on
transient Cerebras 429 `queue_exceeded` ("high traffic") errors under
back-to-back load. Not a model or code issue, but expect occasional 429s when
running the variants in quick succession. Tool calls now run in parallel
(steps with 2 and 5 calls at once were observed) — the previous model id
forced `parallel_tool_calls=False` via a library special-case that no longer
matches.

---
