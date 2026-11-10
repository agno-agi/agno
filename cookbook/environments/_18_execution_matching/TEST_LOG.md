# Test Log - _18_execution_matching

Tested 2026-07-20 with `OpenAIResponses(id="gpt-5.5", reasoning_effort="low")`.

### basic.py

**Status:** PASS

**Description:** Required a clean validation-tool execution and the exact
computed argument.

**Result:** `checksum-submission` passed 7/8 (0.875). The failed attempt called
the correct tool with `20420655`; the argument check correctly rejected it.

---

### failed_calls.py

**Status:** PASS

**Description:** Raised from the tool on a wrong code so request evidence and
errored execution evidence could be distinguished from a clean execution.

**Result:** `checksum-verification` passed 4/8 (0.50). Four wrong-code calls
raised as designed, remained visible in the evidence report, and did not satisfy
the name-only execution scorer.

---

### argument_matching.py

**Status:** PASS

**Description:** Matched the exact code as an argument subset while allowing the
real execution to include an additional source argument.

**Result:** `checksum-recording` passed 5/8 (0.625), producing a genuine spread
despite every attempt being able to execute the tool successfully.

---
