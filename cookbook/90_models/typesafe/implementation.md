# Jev integration

- [x] Official SDK sync/async evaluation and metadata.
- [x] SDK questions and Pydantic `JevField` schema compilation.
- [x] Typed Agent and workflow decisions.
- [x] Route-mode Team leader with a current roster and unchanged member input.
- [x] Optional routing confidence and fallback/abstention.
- [x] Finite tool mode, one dispatch, approval/external execution resume.
- [x] Fixed and opt-in dynamic `JevTools`.
- [x] Custom and preset input/output `JevGuardrail` checks.
- [x] Guardrail service failure propagation and output-stream preflight.
- [x] Provider registration, model policy serialization, semantic cache keys.
- [x] Cookbook examples and mocked SDK tests.
- [x] 464 regression tests passed; lint, formatting and focused type checks passed.
- [x] Recorded full-repository mypy failures in untouched files in TEST_LOG.md.
- [x] Ported named guardrail checks, shorthand custom questions, per-check thresholds, and diagnostic errors from `integrate-jev`.
- [x] Added sync/async `ask_jev`, typed question arguments, toolkit guidance, and the `agno.tools.typesafe` import.
- [x] Retained fixed-tool defaults, custom guardrail policies, service-failure propagation, and output-stream checks.
- [x] Reorganized cookbooks by feature, including review comparison, draft checks, and workflow routing.
- [x] Kept Jev Team leaders restricted to route mode; removed broadcast judging and its example.
- [x] Pretty-printed Jev example results; the support router uses `team.print_response`.
- [x] Validated the final scope: 507 tests passed, 16 skipped, including rejection of broadcast Jev leaders before execution.
- [ ] Live API quality, latency, and threshold evaluation (private-branch testing).

This branch uses Python 3.10+ for the optional SDK while retaining Agno's
existing core Python requirement. No PR or publication is part of this work.
