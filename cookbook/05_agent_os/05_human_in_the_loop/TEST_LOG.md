# Test Log: 05_human_in_the_loop

Tested on 2026-07-24 against Agno source commit
`37496c5ccd3be632cdbb97a9111a4a09999850fb`.

### basic.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Ran the checked-in server and `--demo` client with OpenAI
Responses `gpt-5.5`.

**Result:** The agent returned `PAUSED` with `restart_service`; the client set
`confirmed=true`, posted the serialized tools to `/continue`, and observed
`COMPLETED` with `Restarted the billing service.` The server smoke returned
200 from `/health` and `/config`, which listed `confirmation-agent`.

---

### user_input.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Ran the team server and its checked-in multi-round input
client with OpenAI Responses `gpt-5.5`.

**Result:** Round one collected `name`; round two collected `name`,
`destination`, and `budget` from the propagated requirement shapes. The final
team result returned Ada, Kyoto, and 2500 USD with `COMPLETED`. `/health` and
`/config` returned 200; config listed `trip-survey-agent` and
`trip-planning-team`.

---

### external_execution.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Ran the team until its member requested external email
execution, then used the checked-in client to attach the provider result.

**Result:** The client observed the exact recipient and subject, attached
`demo-message-001`, continued the run, and received `COMPLETED`. `/health` and
`/config` returned 200; config listed `email-agent` and
`communications-team`.

---

### with_approval_record.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Created a required approval, listed it through
`GET /approvals`, resolved it through the approval REST API, and continued the
agent.

**Result:** The row moved from `pending` to `approved` with
`resolved_by=cookbook-admin`; the deployment tool ran and the agent returned
`COMPLETED`. `/health` and `/config` returned 200; config listed
`approval-record-agent`.

---

### audit_record.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Confirmed an audit-decorated ephemeral tool pause and queried
the approvals API after continuation.

**Result:** The run completed and AgentOS returned exactly one `audit` row for
the run with status `approved` and tool name `rotate_api_key`. `/health` and
`/config` returned 200; config listed `audit-record-agent`.

---

### team_approval.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Ran both persistent approval placements with `gpt-5.5`,
resolved each approval record, applied the approved team requirement, and
continued it.

**Result:** `leader-approval-team` produced a `source_type=team` record for
`approve_release`; `member-approval-team` produced a `source_type=agent` record
for `approve_database_change`. Both returned `COMPLETED`. `/health` and
`/config` returned 200; config listed both teams and
`database-specialist`.

---

### workflow_hitl.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Booted the credentials-free workflow server and ran its HTTP
client through every pause.

**Result:** Three continuations resolved step confirmation, user input
(`environment=staging`), and output review in order. The workflow returned
`COMPLETED` with the approved change record. `/health` and `/config` returned
200; config listed `release-review-workflow`.

---

## Validation

- Recursive pattern validation: exactly 7 Python files checked, 0 violations.
- All seven apps imported, built OpenAPI, and exposed `/health`, `/config`, and
  their component-specific run and continuation routes.
- Targeted Ruff format and check passed.
- All seven checked-in server/client flows passed live; no construction-smoke
  substitutions were used.
