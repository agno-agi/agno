# Test Log: cookbook/03_teams/11_reasoning


## Pattern Check

**Status:** PASS

**Result:** Checked 1 file(s). Violations: 0

---

### reasoning_multi_purpose_team.py

**Status:** FAIL

**Description:** Validation issue: runtime

**Result:** Run: Traceback (most recent call last):
  File "/Users/ab/conductor/workspaces/agno/tallinn/libs/agno/agno/tools/e2b.py", line 19, in <module>
    from e2b_code_interpreter import Sandbox
ModuleNotFoundError: No module named 'e2b_code_interpreter'

During handling of the above exception, another exception occurred:

Traceback (most recent call last):
  File "/Users/ab/conductor/workspaces/agno/tallinn/cookbook/03_teams/11_reasoning/reasoning_multi_purpose_team.py", line 18, in <module>
    from agno.tools.e2b import E2BTools
  File "/Users/ab/conductor/workspaces/agno/tallinn/libs/agno/agno/tools/e2b.py", line 21, in <module>
    raise ImportError("`e2b_code_interpreter` not installed. Please install using `pip install e2b_code_interpreter`")
ImportError: `e2b_code_interpreter` not installed. Please install using `pip install e2b_code_interpreter`

---
