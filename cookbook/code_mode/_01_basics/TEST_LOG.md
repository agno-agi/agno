# Test Log - _01_basics

Tested 2026-08-08 against `gpt-5.5` (OpenAIResponses), agno 3.0.0a1, ipykernel 7.3.0, on `.venvs/demo`.

### basic.py

**Status:** PASS

**Description:** One `CodeMode()` toolkit, no options. The agent was asked to build the first 200 Fibonacci numbers in the kernel, keep them in a variable, and report only how many are even and how many digits the largest has.

**Result:** The model wrote a single cell building `fib200`, computing `even_count` and `largest_digit_count`, and printed only the three-key summary dict. Response in 12.0s: "Even: 67. Digits in largest: 42." Both correct (every third Fibonacci number is even; F(199) has 42 digits). The 200-element list never entered the transcript.

---

### with_shell.py

**Status:** PASS

**Description:** `%%bash` cells for shell orchestration. The agent was asked to count Python files in the tree and report the environment's Python version.

**Result:** Response in 9.4s. The model used a `%%bash` cell for the file count and read the Python version from the kernel, reporting both. Shell orchestration cost no extra tool surface — the model still holds exactly `execute` and `restart`.
