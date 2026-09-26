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
- [x] Added the optional TypeSafe SDK to mypy's missing-import overrides for CI environments using only `agno[dev]`.
- [x] Added the selected support-triage, concurrent-review, refund-policy, and smart-home tool-selection scenarios with the existing schema API and pretty printers.
- [x] Preserved the original support-queue `tool_use.py`; added smart-home selection separately as `tools_use_with_fallback.py`. Model examples use `print_response`/`aprint_response` and retrieve saved runs for diagnostics without repeated model calls.
- [ ] Live API quality, latency, and threshold evaluation (private-branch testing).
- [x] Restored minimal `route_team.py` and linear `workflow.py` model examples alongside the expanded feature-folder examples, demonstrating classification and routing with generative models reserved for prose.
- [x] Led the README with Jev's classification and routing role and added one request per department option in `basic.py` and `questions.py`.
- [x] Added `agent_os.py` with a typed Jev classifier, a Jev-led routing team, local session storage, and API checks for JSON and streamed responses from both departments.
- [x] Added `JevAccuracyScorer` with one native Noul comparison, sync/async clients, probability thresholds, metadata, and stable scoring fingerprints. Existing accuracy and AgentOS eval APIs remain unchanged.
- [x] Added supplied-answer, concurrent, and suite examples in the accuracy cookbook plus a generated-answer introduction in the model cookbook.
- [x] Expanded the AgentOS routing demo into a tech team: Python/Node.js source artifacts, HTML artifacts, host shell commands, and web research, selected one specialist at a time by Jev.
- [x] Added one shared Jev input guardrail through team and specialist `pre_hooks`, keeping the example focused on user-input checks.

This branch uses Python 3.10+ for the optional SDK while retaining Agno's
existing core Python requirement. No PR or publication is part of this work.
