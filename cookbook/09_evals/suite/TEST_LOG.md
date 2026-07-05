# Test Log: suite

### suite_basic.py

**Status:** PASS

**Description:** Runs two cases (judge + reliability on a calculator agent, judge-only on a prose answer) through the built-in suite CLI. Tested `--list`, a full run with `--json-output`, an unknown `--tag` selector, and the `python -m agno.eval suite_basic --list` module entry.

**Result:** 2/2 cases passed with exit code 0. JSON payload written with the expected summary/cases shape. Unknown tag exited with code 2 and listed the available case names.

---
