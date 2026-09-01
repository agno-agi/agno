# Test Log: second_brain

> Tested 2026-07-25 against gpt-5.6 (via model="openai:gpt-5.6"), branch
> feat/entity-memory-revamp. Rebuilt on the LearningMachine: entity memory (four tools,
> shared "global" namespace) + AGENTIC user profile/memory + shared "brain" notes
> namespace + the one-claim-one-home rule, with identity pinned (Agent(user_id="owner")).
> The pre-2.8.4 store (enable_agentic_memory era) was set aside as
> tmp/second_brain_pre284.db.bak; this brain starts fresh on the learnings table.

## second_brain.py - REST live proof (8 turns, DB verified between turns)

**Status:** PASS

Served with uvicorn on 7777; turns driven via POST /agents/second-brain/runs, each in a
fresh session; every claim below checked in tmp/second_brain.db between turns.

1. Capture (project + decision): harbor filed with the index line
   "database: Postgres, over DynamoDB - see note", the reasoning ONLY in notes/harbor.md,
   and the note pointer on the entity (properties.note = notes/harbor.md). The agent also
   linked postgres/dynamodb, created as minimal entity_type="unknown" targets - the
   designed link-first-describe-later shape.
2. Capture (person): Sarah Chen recorded; the edge landed on BOTH rows with the far end's
   type (harbor: designs <- sarah_chen, entity_type person).
3. Correction: "not blocked anymore, v0.1 shipped" retired
   "status: blocked on the auth review" (superseded_by = the new fact's id, verified in
   the fact record) and appended a dated entry to the note.
4. Why-question (fresh session): answered with the note's reasoning verbatim shape
   (multi-row transactions, team knows SQL, single-table modeling) - the note pointer
   round-trip works.
5. Negative: "Have we ever discussed the Acme contract?" -> "No - I searched the entity
   directory and all notes for Acme and contract and found nothing." A grounded no.
6. Archive: legacy-sync archived (archived_at set in DB; all other entities live), and
   the subsequent index turn did NOT list it.
7. Browse: the full index listed the four live entities from the directory.
8. Private confidence: "keep it between us" about the harbor budget went to user_memory
   (user_id=owner), explicitly NOT to the shared entity, and the brain said so.

Model behavior notes (findings, not failures):
- The note template included a literal "**Date recorded:** Not provided" line in turn 1 -
  harmless, but the model narrates missing dates rather than omitting them.
- "Numbers before prose" (stored as a user memory in turn 8) visibly shaped later answers
  across channels, including MCP - the preference survived and applied.
- The profile store was not used in this run (name-shaped facts never came up); the
  preference went to user_memory, which is the right home for it.

## /mcp live proof (4 turns, in-process fastmcp client)

**Status:** PASS

The client saw the eight built-in AgentOS tools. Each run_agent call was a fresh session
(no session echo - exactly the MCP shape), and the pinned user_id carried the brain:

1. "Where does harbor stand?" recalled the REST-era state (v0.1 shipped, Postgres over
   DynamoDB) across the channel boundary.
2. A write from MCP: Tom Alvarez / load tests, recorded with a note pointer
   ("load testing: Tom Alvarez will run the tests next week - see note").
3. A THIRD fresh session recalled that write.
4. The why-question over MCP answered from the note's reasoning.

## test.py

**Status:** PASS

Capture session filed quill (advisory locks over SELECT FOR UPDATE SKIP LOCKED) with the
reasoning in notes/quill.md; a fresh recall session answered tersely and correctly
("advisory locks ... because Quill's workers are long-lived"). The shared brain listing
shows both notes/harbor.md (with its dated updates) and notes/quill.md.

## 2026-07-26 — add_datetime_to_context, cold-start proof

**Status:** PASS

The "**Date recorded:** Not provided" line above was the agent having no clock: the
instructions ask for dated notes, and until an entity fact renders its "(as of ...)" date
there is nothing in the prompt to date them with. Two prior runs produced headings like
"## Date not provided - architecture".

With `add_datetime_to_context=True` on the agent, a fresh db and one turn ("we picked
Postgres over Dynamo for the radar ingest queue") produced `notes/radar-ingest-queue.md`
with the heading `## 2026-07-26 - Postgres over Dynamo`. Dated on the first turn, with no
entity in the store to borrow a date from.

## 2026-07-26 — the pinned user_id does NOT survive an MCP client that fills it

**Status:** FAIL (identity, deployment-shaped - see the note in second_brain.py)

Measured in-process against the real `/mcp` app: `run_agent` advertises an optional
`user_id`, and a value supplied there overrides `Agent(user_id="owner")`. One call with
`user_id="claude-desktop"` wrote its session and its user memory under `claude-desktop`,
not `owner`. Entities are global so they stay shared; profile and user memory fork per
host. Unauthenticated `/mcp` is exactly where host models fill the field.

## 2026-07-26 — four turns after the review fixes (fresh db, gpt-5.6)

**Status:** PASS

| Turn | Expected | Result |
|---|---|---|
| Decision + people + systems in one message | note written dated, entity indexed with a pointer, both links reciprocal | `write_file notes/quill.md` (`## 2026-07-26 - Concurrency control decision`), `remember_about(Quill, facts=["concurrency control: Postgres advisory locks... - see note"])`, `link_entities` twice |
| "Priya has moved off Quill" | the old relationship retired, the new one recorded | `forget("Priya Raman", "runs -> Quill")` **removed the edge on both rows**, then `link_entities(Priya, works_on, Billing rewrite)`. Quill's row keeps only `backed_by -> postgresql` |
| "Between us: the Nimbus renewal is shaky" | private memory, no shared entity | `update_user_memory(...)` only; no Nimbus entity exists in the store |
| "What is the state of Quill, and why advisory locks?" | read the note, answer from it | `search_entities` → `read_file(notes/quill.md)` → answered with the reasoning, and volunteered that no replacement lead is recorded |

The retirement turn is the one that mattered: on the pre-fix code the same call
matched nothing it could act on, or matched two candidates it printed
identically. Model behavior note: turn 2 rewrote the whole note with
`write_file` rather than `replace_lines` - allowed, and the note stayed correct.
