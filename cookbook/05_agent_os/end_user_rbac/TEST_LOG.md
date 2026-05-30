# End-User RBAC — Test Log

Tracks runs of the `end_user_rbac/` examples. Update this file every time you
run one of the scripts.

Format per the project convention:

```
### filename.py

**Status:** PASS/FAIL

**Description:** What the test does and what was observed.

**Result:** Summary of success/failure.

---
```

## Runs

### 01_basic_issue_and_verify.py

**Status:** NOT YET RUN

**Description:** Starts an AgentOS, mints scoped tokens for alice + admin,
prints curl commands. Manual verification via curl.

**Result:** _pending_

---

### 02_end_user_simulation.py

**Status:** NOT YET RUN

**Description:** Boots a server in-process, has alice and bob each chat, then
asserts each only sees their own `/sessions` (per-subject data isolation).

**Result:** _pending_

---

### 03_revocation_preview.py

**Status:** NOT YET RUN

**Description:** Issues a token, hits `/agents` (200), revokes the jti, hits
`/agents` again (401). Validates the in-memory denylist pattern that Track B
will productize.

**Result:** _pending_

---

### 04_tokens_endpoint.py

**Status:** NOT YET RUN

**Description:** Boots an AgentOS, mints a bootstrap token for Nia's backend
(`tokens:issue`), uses it via `POST /tokens` to mint an end-user token for
alice, verifies alice's access (200 on `/agents`, 403 on delete and on
`/tokens`), and confirms the privilege-escalation guardrail (400 when
attempting to mint a token carrying `tokens:issue`).

**Result:** _pending_

---

### 05_governance_crud.py

**Status:** NOT YET RUN

**Description:** Boots `governance=True` AgentOS, creates two templates, two
end-users, lists/updates/deletes them, prints audit log entries.

**Result:** _pending_

---

### 06_governed_issuance_and_revocation.py

**Status:** NOT YET RUN

**Description:** Registers alice on free-tier, mints a token via
`POST /end-users/alice/tokens`, hits `/agents` (200), revokes via
`DELETE /tokens/{jti}`, sleeps past cache TTL, hits `/agents` again (401).

**Result:** _pending_

---

### 07_tier_upgrade.py

**Status:** NOT YET RUN

**Description:** Free-tier alice gets a token, upgrades to pro via PATCH, a
new token is minted with pro scopes; old token revoked. Audit log shows the
tier change.

**Result:** _pending_

---

### 08_nia_onboarding_e2e.py

**Status:** NOT YET RUN

**Description:** Full Nia journey: bootstrap → templates → onboard three
customers → each chats → tier upgrade → audit log review → per-user data
isolation confirmation.

**Result:** _pending_

---
