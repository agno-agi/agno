# Test Log: 07_security

Last updated: 2026-07-24

Server verification used `.venvs/demo` with the pinned worktree library on
`PYTHONPATH`. The eight local server examples (`basic_scopes.py`,
`asymmetric_keys.py`, `per_resource_scopes.py`, `custom_scope_mappings.py`,
`cookie_auth.py`, `jwt_claims.py`, `user_isolation.py`, and
`service_accounts.py`) were started through `AgentOS.serve()`: all returned
200 from `/health` and 401 from an unauthenticated `/config` request before
clean termination.

### basic_scopes.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Built the HS256 AgentOS app with authorization and audience
verification enabled, then exercised its REST routes with a FastAPI
`TestClient`.

**Result:** Reader list 200; reader run without `agents:run` 403; runner list
200; admin config 200; mismatched audience 401.

---

### asymmetric_keys.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Generated an RS256 keypair, signed a token with the private
key, and verified it in AgentOS with only the public key.

**Result:** Audience-bound `GET /agents` returned 200.

---

### per_resource_scopes.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Built two agents, one team, and one workflow, then requested
all three list endpoints with both per-resource and wildcard read/run scopes.

**Result:** The per-id token exposed exactly `research-agent`,
`research-team`, and `review-workflow`, filtering out `private-agent`. The
wildcard token exposed both agents plus the registered team and workflow.

---

### custom_scope_mappings.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Overrode `GET /config` to require `app:read` and added
`app:execute` alongside `agents:run` for agent runs.

**Result:** `app:read` received 200 from `/config`; a token with only
`agents:read` received 403.

---

### cookie_auth.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Requested the local login route over HTTPS, accepted its
secure HTTP-only JWT cookie, and called the protected AgentOS list route.

**Result:** No cookie returned 401; setting the cookie returned 200; the
cookie-authenticated `GET /agents` returned 200.

---

### jwt_claims.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Sent a verified JWT to `/whoami`, built the same `RunContext`
injected into the registered agent tool, and read its trusted dependencies.

**Result:** `sub` became `request.state.user_id`; the audience was preserved;
name, email, and roles became `RunContext.dependencies`; organization id
became session state.

---

### user_isolation.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Created one session as each of two unique JWT subjects while
`user_isolation=True`, including an attempted owner spoof in the first body.

**Result:** The spoofed owner was replaced by the JWT subject. Each caller saw
exactly its own session, while the admin response included both.

---

### service_accounts.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Used an admin JWT to mint and list a service account,
exercised the opaque token, checked its authorization boundary, revoked it, and
retried it.

**Result:** Mint returned 201 and an `agno_pat_` token with the exact current
defaults: `agents:run`, `teams:run`, `workflows:run`, `sessions:read`, and
`config:read`. The admin list contained the new account; the PAT received 200
from `/config`, 403 from `/service-accounts`, and 401 after the admin revoked
it with a 204 response.

---

### workos_byot.py

**Status:** PASS

**Test mode:** CONSTRUCTION_SMOKE

**Description:** Generated a local RS256 JWKS equivalent, constructed the
WorkOS configuration with `permissions` scopes and explicit audience
verification, and inspected the mounted OpenAPI paths.

**Result:** The app constructed successfully with 70 routes; `/health`,
`/config`, and `/agents` were mounted. A live provider run still requires
`WORKOS_CLIENT_ID`, `WORKOS_API_KEY`, and the `workos` package.

---

### test_scopes.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Ran the same local enforcement matrix as a script and with
pytest.

**Result:** Eleven checks passed: anonymous 401; agent/team/workflow list 200;
reader agent/team/workflow runs 403; authorized local workflow run 200;
component create 403; admin config 200; mismatched audience 401. Pytest
reported `1 passed`.

---
