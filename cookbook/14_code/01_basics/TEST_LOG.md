# Test Log - 01_basics

Tested 2026-08-21 against `gpt-5.5` (OpenAIResponses), ipykernel 7.3.0, jupyter_client 8.9.1, dill 0.4.1, with the worktree's Python (agno from this branch, `from agno.tools.code import CodeMode`).

Every run prints one ipykernel line on stderr, `[IPKernelApp] WARNING | Kernel is running over TCP without encryption...`. It comes from ipykernel 7 at kernel start, does not apply to the loopback-only kernel CodeMode runs, and is not something this branch changes.

### basic.py

**Status:** PASS

**Description:** An agent with `CodeMode()` builds the first 200 Fibonacci numbers in a kernel variable and reports how many are even and how many digits the largest has.

**Result:** One `execute` call; the cell printed `even_count=67, largest_digits=42` and the answer was "67 even; 42 digits." Both are correct for the zero-first sequence the cell built (the largest, 173402521172797813159685037284371942044301, has 42 digits). Exit 0, no traceback.

---

### with_shell.py

**Status:** PASS

**Description:** A `%%bash` cell counts the Python files in the tree and reports the Python version.

**Result:** The first cell called bare `python`, which does not exist on this machine; the agent re-issued it with `python3` on its own. The answer, 4,577 Python files and Python 3.14.6, matches `find . -name '*.py' -type f | wc -l` and `python3 -V` in a bash subshell. Exit 0, no traceback.

---

