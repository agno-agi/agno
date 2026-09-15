# Test Log - _25_support_triage

## Re-test 2026-07-20 — fix/cookbooks-claude (Agno 2.8.0 source)

gpt-5.5 aced the classification tasks (including the 20- and 32-issue handoffs) at
`reasoning_effort="low"`, so `basic.py` and `ambiguous_tickets.py` saturated. Made
the in-schema handoff checksum genuinely hard (sum of `position^2 * suffix^3` mod
9973), which the model slips on at low effort.

### basic.py — FIXED

**Fix:** added a `handoff_checksum` field computed over the active-issue set; the
20-issue task's checksum is now error-prone.

**Grid (k=8):** `self-login-plus-charge` 8/8; `resolved-token-history` 8/8;
`twenty-issue-handoff` 7/8 (0.88, zone).

### ambiguous_tickets.py — FIXED

**Fix:** replaced the easy `active_issue_checksum` (position * suffix^2 mod 97) with
the hard formula; the safety-override tasks also carry genuine classification
ambiguity.

**Grid (k=6):** `feature-with-hypothetical-risk` 5/6 (0.83, zone); the other five
tasks 6/6.

`precedence_rules.py` (card-data-not-outage 4/6, zone) re-ran clean and unchanged.

---

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
