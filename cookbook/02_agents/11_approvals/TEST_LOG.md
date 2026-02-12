# Test Log — 11_approvals

Tested: 2026-02-12 | Branch: cookbook/v25-merge-fixes

| File | Status | Notes |
|------|--------|-------|
| approval_async.py | FAIL | AssertionError: Expected run to complete but run was paused |
| approval_basic.py | PASS | Completed successfully |
| approval_external_execution.py | PASS | Deployment approval flow completed |
| approval_list_and_resolve.py | FAIL | AssertionError: Expected pause but got RunStatus.completed |
| approval_team.py | PASS | Completed successfully |
| approval_user_input.py | PASS | All checks passed, sent $50 to Alice |
| audit_approval_async.py | PASS | All checks passed, user data deletion completed |
| audit_approval_confirmation.py | PASS | Completed successfully |
| audit_approval_external.py | FAIL | AssertionError: Expected paused but got RunStatus.completed |
| audit_approval_overview.py | PASS | Completed successfully |
| audit_approval_user_input.py | PASS | Completed successfully |
