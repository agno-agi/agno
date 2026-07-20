# Test Log - _25_support_triage

Tested 2026-07-20 against `gpt-5.5` through `OpenAIResponses`, Agno 2.7.4.

### basic.py

**Status:** PASS

**Description:** Queue precedence over mixed active and non-operative issues at K=8.

**Result:** `self-login-plus-charge` 8/8, `resolved-token-history` 8/8, and
`twenty-issue-handoff` 7/8. Queue-only, evidence-aware, and dense six-rollout
grids all saturated. The 20-issue handoff, exact active-issue provenance, and
an eight-rollout grid exposed the 7/8 middle band.

---

### precedence_rules.py

**Status:** PASS

**Description:** Exact queue, severity, and response-target routing at K=6.

**Result:** `owner-lockout` 6/6, `card-data-not-outage` 4/6,
`resolved-loss-active-outage` 6/6, `standard-user-and-bug` 5/6, and
`current-state-boundaries` 6/6. Queue-and-severity scoring saturated, and the
first exact matched-rule rerun also saturated. Adding a boundary case made the
evidence contract difficult enough to expose two middle-band rows.

---

### ambiguous_tickets.py

**Status:** PASS

**Description:** Requested-action routing, active-issue reconciliation, and safety
overrides at K=6.

**Result:** `bug-context-refund-request` 6/6,
`feature-with-hypothetical-risk` 5/6, `access-request-active-intrusion` 6/6,
`quoted-outage-current-access` 6/6, `refund-wording-active-outage` 6/6, and
`long-requested-action-handoff` 6/6. Queue/action scoring saturated; exact
active-issue provenance saturated; a 16-clause handoff saturated; a 32-clause
handoff saturated; and a simple checksum still saturated. The final weighted
reconciliation checksum exposed the 5/6 row.

---
