# REVIEW_LOG.md - 91 Tools Root

**Review Date:** 2026-02-11
**Branch:** `cookbooks/v2.5-testing`
**Reviewer:** Opus 4.6

---

## Framework Issues

### [FRAMEWORK] searxng.py:34 — **kwargs forwarded to Toolkit.__init__() without filtering
The `Searxng.__init__()` accepts `**kwargs` and forwards them directly to `super().__init__()`. If callers pass tool-specific kwargs like `news=True`, these get forwarded to `Toolkit.__init__()` which raises TypeError. The Searxng class should filter out its own kwargs before calling super().

**Severity:** Medium (breaks cookbook usage)
**Action:** Log only

### [FRAMEWORK] searxng.py:15 — mutable default `engines=[]`
Same mutable default list pattern as in other tools.

**Severity:** Low
**Action:** Log only

---

## Quality Issues

### searxng_tools.py — passes invalid kwargs `news=True, science=True`
The cookbook passes `news=True, science=True` to `SearxngTools()` but these kwargs are not handled by the `Searxng` class. They get forwarded to `Toolkit.__init__()` which raises TypeError. Either the class should support these kwargs (to enable/disable search categories) or the cookbook should not pass them.

### Demo venv missing 48+ optional packages
Most tool cookbooks cannot be tested because their required packages are not in `.venvs/demo/`. The demo_setup.sh script should include these optional extras or there should be a comprehensive requirements file for testing all tool cookbooks.

---

## Compatibility

No v2.5-specific compatibility issues found. All files that could be run use standard v2.5 APIs correctly. The one FAIL (searxng_tools) is a pre-existing bug, not a v2.5 regression.

## Fixes Applied

None needed. Framework issues logged only.
