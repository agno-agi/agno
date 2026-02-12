# REVIEW LOG — Approvals

Generated: 2026-02-11 UTC (v2.5 three-layer review)

## Framework Issues

See parent `human_in_the_loop/REVIEW_LOG.md` for framework-level approval system issues that affect all approval cookbooks.

Additional approval-specific findings:

[FRAMEWORK] db/sqlite/sqlite.py:4622+ — Approval CRUD methods exist but `get_approvals` returns `(list, int)` tuple without documenting the second element (total count). Callers must destructure correctly or get cryptic errors.

[FRAMEWORK] db/base.py — `get_pending_approval_count()` is defined but not used by any cookbook or framework path. Dead code that could mislead integrators.

[FRAMEWORK] run/approval.py:232-292 — `create_audit_approval()` sync variant calls `db.create_approval()` directly, while async variant does `iscoroutinefunction()` check. Inconsistent patterns could cause issues if sync DB adapters gain async methods.

## Cookbook Quality

[QUALITY] approval_basic.py — Excellent reference example. 5-step verification pattern covers the full lifecycle: pause, DB check, confirm, continue, resolve.

[QUALITY] approval_async.py — Good async variant. Mirrors approval_basic exactly, showing sync/async parity.

[QUALITY] approval_user_input.py — Clean combination of @approval + user_input. Shows how user-provided values flow through the approval record.

[QUALITY] approval_external_execution.py — Clear pattern for external execution with approval logging.

[QUALITY] approval_list_and_resolve.py — Best example of the full approval API surface: list, filter, approve, reject, delete, double-resolve guard. Essential reference for API client implementations.

[QUALITY] approval_team.py — Critical example showing team-level approval. Verifies source_type=team in the approval record.

[QUALITY] audit_approval_confirmation.py — Excellent dual-path testing: both approval and rejection create audit records. Shows audit records are created AFTER resolution, not before.

[QUALITY] audit_approval_async.py — Good async variant of audit approval.

[QUALITY] audit_approval_external.py — Shows audit + external execution combination.

[QUALITY] audit_approval_overview.py — Best teaching example. Side-by-side comparison of required vs audit in same agent, with step-by-step verification and filtering by approval_type.

[QUALITY] audit_approval_user_input.py — Shows audit + user input combination. Completes the matrix of all audit+HITL combinations.

## Fixes Applied

None — all approval cookbooks are v2.5 compatible as-is.
