# Test Log - _17_tool_reliability

Tested 2026-07-20 with `OpenAIResponses(id="gpt-5.5", reasoning_effort="low")`.

### basic.py

**Status:** PASS

**Description:** Scored the first clean validation-tool execution against the
exact computed code across eight isolated attempts.

**Result:** `checksum-submission` passed 7/8 (0.875), producing a true
learning-zone row.

**Calibration:** Two policy-lookup prompts first saturated at 4/4 each. A
single checksum tool that returned accepted/rejected feedback then saturated at
8/8 because the agent could self-correct. A doubled checksum with no feedback
overshot to 0/6. The final task uses the calibrated single checksum, neutral
receipt feedback, and a one-call limit; it produced 7/8.

---

### with_reliability_eval.py

**Status:** PASS

**Description:** Applied `ReliabilityEval` to every captured attempt with the
same clean-execution and exact-argument expectation as `ToolCallScorer`.

**Result:** `checksum-submission` passed 7/8 (0.875). `ReliabilityEval` also
reported 7/8, confirming agreement on execution evidence.

---

### repeated_reliability.py

**Status:** PASS

**Description:** Aggregated one `ReliabilityEval` verdict per isolated rollout
instead of relying on a single transcript.

**Result:** `checksum-submission` passed 6/8 (0.75), with statuses
`PASSED, FAILED, FAILED, PASSED, PASSED, PASSED, PASSED, PASSED`.

---
