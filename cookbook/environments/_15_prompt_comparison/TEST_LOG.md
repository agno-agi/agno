# Test Log - _15_prompt_comparison

Tested 2026-07-20 with `OpenAIResponses(id="gpt-5.5", reasoning_effort="low")`.

### basic.py

**Status:** PASS

**Description:** Measured terse and step-checking prompt environments separately
and compared their summaries without using `EnvironmentDiff`.

**Result:** Terse: `product-a` 1/4 (0.25), `product-b` 4/4 (1.00). Checking:
`product-a` 2/4 (0.50), `product-b` 4/4 (1.00). The environment fingerprints
differed as expected.

---

### instruction_detail.py

**Status:** PASS

**Description:** Compared short and detailed arithmetic instructions, then
exercised the prompt-fingerprint mismatch guard.

**Result:** Short: `product-a` 3/4 (0.75), `product-c` 3/4 (0.75). Detailed:
`product-a` 1/4 (0.25), `product-c` 4/4 (1.00). `MismatchError` rejected the
cross-prompt diff.

---

### format_constraint.py

**Status:** PASS

**Description:** Compared concise and auditable reasoning-field instructions
under one typed output schema.

**Result:** Concise: `product-a` 1/4 (0.25), `product-d` 4/4 (1.00). Auditable:
`product-a` 2/4 (0.50), `product-d` 2/4 (0.50). The fingerprints differed and
the process exited successfully.

**Observation:** During client cleanup, the live run emitted one asynchronous
`httpx` "Event loop is closed" warning after the first rollout. Both rollout
results completed and the process exited 0. No library code was changed.

---
