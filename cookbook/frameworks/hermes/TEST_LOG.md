# Hermes test log

**Status:** NOT RUN

The adapter regression tests and cookbook examples are authored but have not
been executed. Unit tests, provider calls and server startup remain deferred until the user
requests them. Static-check results are recorded below.

Pending unit suite: `libs/agno/tests/unit/agents/test_hermes.py`.

Pending cookbooks: `hermes_basic.py`, `hermes_native_sdk.py`, `hermes_tools.py`,
`hermes_session.py` and `hermes_agentos.py`.

## Static checks — 2026-10-12

- `./scripts/format.sh`: PASS with repository-pinned Ruff 0.15.20.
- `./scripts/validate.sh`: FAIL in the Agno mypy step, with mypy 2.1.0.
- All Ruff checks, agnoctl mypy and the quickstart pattern check pass.
- Both isolated adapter branches report the same 83 errors in 21 unchanged files,
  including existing typing errors and untyped optional dependencies. Neither
  new adapter has reported type errors after the fixes.
- These are static checks only. No unit suite, cookbook, provider call or server
  was executed. The PR remains a draft pending validation and runtime verification.
