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
