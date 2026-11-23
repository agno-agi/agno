# Test Log: 11_composition

> Tested 2026-07-25 against gpt-5.5 (OpenAIResponses), branch feat/entity-memory-revamp,
> Postgres (pgvector container on 5532). Re-tested 2026-07-26 after the missing-model fix.

### basic.py

**Status:** PASS

**Result:** With no learning=, the hand-placed tools captured the preference (user memory)
and the Meridian project + Priya link (entity memory); the printed manual-door surfaces
show the guidance block and a data block whose relevance recall expanded Meridian for the
message "what about meridian?" with the one-hop "runs <- Priya" edge.

**2026-07-26 correction:** the first log was wrong about the user memory. The machine
carried no `model=`, so `update_user_memory` returned "No model provided for memories
extraction" and stored nothing - only the entity write (no model needed) landed. The
same hole `always_capture.py` hit below; the manual door injects nothing. Re-run with
`model=` on the machine: `update_user_memory` stored "Prefers sources with primary data",
verified in the learnings table.

---

### with_filesystem.py

**Status:** PASS

**Result:** One deliberate order: learning tools + fs tools + both instruction blocks. The
agent wrote notes/vector-db-comparison.md with the deadline. Model behavior note: it also
wrote the "conclusions first" preference INTO the note alongside saving it - the
one-claim-one-home discipline is exactly what the second-brain instructions add on top.

**2026-07-26 correction:** same missing `model=`, so the note was written but the
preference was not stored. Re-run with the model: `update_user_memory(task=User prefers
conclusions first in every summary.)` and `append_file(notes/tasks.md)` both fired, and
the memory is in the table.

---

### context_block.py

**Status:** PASS

**Result:** build_context() placed via additional_context, no tools: the read-only agent
answered from its own knowledge.

**2026-07-26 correction:** the earlier "despite the seeded memory in the context, the
summary put its conclusion last" reads a model failure into a store failure - the seeding
call needed a model too, so nothing was seeded and the context block was empty. With
`model=` on the machine the seed lands; the answer still leads with its list and closes
with the conclusion, so the original observation (a data-only block informs but does not
compel) holds on the re-run.

---

### always_capture.py

**Status:** PASS

**Result:** post_hooks=[learning.capture_hook()] ran ALWAYS extraction in the background:
profile (Name/Preferred Name: Dana) and one memory (data engineer, Lisbon, ClickHouse
pipelines) appeared without any tool call. First run FAILED with empty stores - the manual
door injects nothing, so the machine needed model= passed explicitly; the file and README
now say so.

**2026-07-26:** this was the only file that had learned the lesson. `LearningMachine.get_tools()`
now warns once when a store that captures through a model has none, so the next person
finds out at attach time instead of from an empty table.

---
