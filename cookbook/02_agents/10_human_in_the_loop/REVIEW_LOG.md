# REVIEW LOG

Generated: 2026-02-11 UTC (v2.5 three-layer review)

## Framework Issues

[FRAMEWORK] approval/decorator.py:72 — `@approval("audit")` (positional string) silently stamps the string as the target callable instead of raising an error. Should validate that `func_or_type` is actually callable when it's not `None`.

[FRAMEWORK] run/approval.py:35+41 — `_has_approval_requirement()` only checks the FIRST approval-marked tool. If an agent has mixed `required` + `audit` tools and the `audit` one comes first, the required gate would be skipped.

[FRAMEWORK] run/approval.py:113 — `_build_approval_dict()` hardcodes `"approval_type": "required"`. In a mixed-tool scenario where both required and audit tools pause simultaneously, the record would always be tagged as "required".

[FRAMEWORK] run/approval.py:300 — Rejected-path handling sets `confirmed=False` for user_input tools but does not clear populated `user_input_schema` field values. Stale values from a previous attempt could leak into a rejection continuation.

[FRAMEWORK] run/approval.py:372+394 — `check_and_apply_approval_resolution()` checks only `run_response.tools`, not `run_response.requirements`. Team-level approval gating would be bypassed since member tools are propagated via requirements.

[FRAMEWORK] tools/function.py:150-176 — `to_dict()`/`from_dict()` are asymmetric: `from_dict` omits `requires_user_input`, `external_execution`, and `approval_type`. Persisted/reconstructed tools lose HITL state, breaking continue_run for service-backed workflows.

[FRAMEWORK] tools/decorator.py:245 — `user_input_fields` auto-infer via `kwargs.get("requires_user_input", True)` can set `requires_user_input=True` AFTER the mutual exclusivity check at line 157, bypassing the guard.

[FRAMEWORK] run/requirement.py:31 — Custom `__init__` with undeclared `id` field weakens dataclass/type safety. `from_dict` fallback creates placeholder tool (`tool_name="unknown"`) that masks corrupt state.

[FRAMEWORK] agent/_tools.py:427-461 — Callable tool parsing catches ALL exceptions and only logs a warning. A broken @approval decorator or HITL flag would be silently swallowed at agent init time.

## Cookbook Quality

[QUALITY] confirmation_required.py — Clean minimal example of requires_confirmation. Good starting point.

[QUALITY] confirmation_toolkit.py — Good pattern for toolkit-level confirmation vs tool-level.

[QUALITY] external_tool_execution.py — Clear demonstration of external execution pattern with result injection.

[QUALITY] user_input_required.py — Good example of user_input_fields. Shows the requirement.needs_user_input check pattern.

[QUALITY] agentic_user_input.py — Advanced pattern using UserControlFlowTools for dynamic user queries during execution. Good real-world example.

[QUALITY] confirmation_advanced.py — Would be good multi-tool example but blocked by optional wikipedia dependency.

[QUALITY] confirmation_required_mcp_toolkit.py — Unique MCP confirmation pattern. Requires external MCP server so hard to test locally.

## Fixes Applied

None — all cookbooks are v2.5 compatible as-is. Framework issues logged only.
