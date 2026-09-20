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
- [ ] Live API quality, latency, and threshold evaluation (private-branch testing).

This branch uses Python 3.10+ for the optional SDK while retaining Agno's
existing core Python requirement. No PR or publication is part of this work.
