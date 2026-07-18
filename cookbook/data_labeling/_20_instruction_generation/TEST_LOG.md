# Test Log - _20_instruction_generation

Tested 2026-07-18 against `gemini-3.5-flash`, agno 2.7.4.

### basic.py

**Status:** PASS

**Description:** Self-Instruct: one generator agent, 2 rounds, each round feeds a deterministic 3-seed slice of the 8 hand-written seeds as few-shot examples (rounds 1 and 2 use seeds 1-3 and 4-6; seeds 7-8 participate only in dedupe) and asks for 5 novel instructions. Candidates are deduplicated against seeds and already-accepted instructions with word-set Jaccard >= 0.7 before being written to data/generated/instructions.jsonl with seed_ids and round provenance.

**Result:** Summary line: "wrote 10 rows ... kept 10, dropped 0". All 10 candidates (2 rounds x 5) cleared the Jaccard filter this run - the model reliably produces genuinely novel instructions (fictional botany, logic puzzles, raw-chicken food safety, contract liability, gravitational lensing), so word-set overlap with the seeds stays far below 0.7. Kept/dropped counts can vary run to run; dropped 0 is the expected common case at this threshold.

---

### evol_instruct.py

**Status:** PASS

**Description:** Evol-Instruct: one evolver agent, 5 seeds x 2 chained evolution steps (seed -> depth 1 -> depth 2), operator chosen by deterministic round-robin over add_constraints / deepen / concretize / increase_reasoning / in_breadth so all five operators appear across the 10 calls. Stdlib eliminator drops evolutions with Jaccard vs parent > 0.85 (no-op) or fewer than 4 words (degenerate). Rows carry instruction, parent, operator, depth.

**Result:** Summary line: "wrote 10 rows ... from 10 evolution calls, kept 10, dropped 0". Every evolution was a real transformation this run - e.g. "Write a short story about a lighthouse keeper." gained word-count, setting, and forbidden-word constraints at depth 1, then a second-person POV, sensory, and structural-ending requirements at depth 2. The eliminator did not fire; it exists to catch the occasional no-op or degenerate return, which did not occur in this run.

---

### topic_tree.py

**Status:** PASS

**Description:** Topic-tree pipeline with three module-level agents: subtopic expander (root topic "database indexing" -> 3 subtopics), question writer (2 questions per subtopic), and answerer. Writes SFT-ready chat rows {"messages": [user, assistant], "provenance": {topic, subtopic, depth: 3}} to data/generated/topic_tree.jsonl.

**Result:** Summary line: "wrote 6 rows ... (3 subtopics x up to 2 questions each)". This run produced subtopics including "Index Data Structures and Algorithms" and questions such as B+ Tree vs LSM write amplification and PostgreSQL Bitmap Index Scan selection criteria, each with a substantive one-to-two-paragraph answer. Subtopic and question wording varies run to run; the 3 x 2 = 6 row count is an upper bound capped by slicing the model output (fewer subtopics or questions would yield fewer rows).

---
