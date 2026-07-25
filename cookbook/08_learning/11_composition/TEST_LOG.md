# Test Log: 11_composition

> Tested 2026-07-25 against gpt-5.5 (OpenAIResponses), branch feat/entity-memory-revamp,
> Postgres (pgvector container on 5532).

### basic.py

**Status:** PASS

**Result:** With no learning=, the hand-placed tools captured the preference (user memory)
and the Meridian project + Priya link (entity memory); the printed manual-door surfaces
show the guidance block and a data block whose relevance recall expanded Meridian for the
message "what about meridian?" with the one-hop "runs <- Priya" edge.

---

### with_filesystem.py

**Status:** PASS

**Result:** One deliberate order: learning tools + fs tools + both instruction blocks. The
agent wrote notes/vector-db-comparison.md with the deadline. Model behavior note: it also
wrote the "conclusions first" preference INTO the note alongside saving it - the
one-claim-one-home discipline is exactly what the second-brain instructions add on top.

---

### context_block.py

**Status:** PASS

**Result:** build_context() placed via additional_context, no tools: the read-only agent
answered from its own knowledge. Model behavior note: despite the seeded
"conclusions first" memory in the context, the summary put its conclusion last - the
data-only block informs but does not compel; the preference lands more reliably with the
memory tools + guidance attached.

---

### always_capture.py

**Status:** PASS

**Result:** post_hooks=[learning.capture_hook()] ran ALWAYS extraction in the background:
profile (Name/Preferred Name: Dana) and one memory (data engineer, Lisbon, ClickHouse
pipelines) appeared without any tool call. First run FAILED with empty stores - the manual
door injects nothing, so the machine needed model= passed explicitly; the file and README
now say so.

---
