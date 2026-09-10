# Test Log: 26_authorization

Last updated: 2026-08-17 (re-run after rebasing onto feat/extending-user-isolation)

All examples were run with `.venvs/demo/bin/python` against the branch's library.
None of the local examples need a database server, a model key, or an external
authorization engine: managed roles persist to throwaway SQLite under `tmp/`, the
FGA example runs on an in-memory store, and the IdP example mints its own
throwaway keys.

### 01_managed_roles.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Defines three roles and two subjects, then makes real requests
through the AgentOS pipeline and prints ALLOWED or BLOCKED for each, including a
role change applied while the server is running.

**Result:** Exit 0, no traceback. Viewer reads allowed and runs blocked; the
runtime role change took effect on the next request with no new token.

---

### 02_managed_users.py

**Status:** PASS

**Test mode:** LIVE

**Description:** The credential-less user directory: auto-provisioning a row from
token claims, granting the default role (is_default) on first provision, and the
disabled-user kill switch.

**Result:** Exit 0, no traceback. A disabled user is denied at the enforcement
point while still holding a valid, unexpired token. A brand-new user (dave),
never seen before, is auto-provisioned on his first request AND granted the
default role (`viewer`, flagged `is_default`) in the same request, so he is
ALLOWED (200) immediately with `role=viewer` rather than landing inert.

---

### 04_managed_roles_sessions.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Role enforcement over real session data — who may delete a chat
session.

**Result:** Exit 0, no traceback. Delete allowed for the owning role, blocked
otherwise.

---

### 05_managed_roles_audit.py

**Status:** PASS

**Test mode:** LIVE

**Description:** The audit trail: role-change events plus a record of every
allow/deny decision.

**Result:** Exit 0, no traceback. Both the change trail and the decision trail
were written and printed.

---

### 08_custom_authorization_provider.py

**Status:** PASS

**Test mode:** LIVE

**Description:** A hand-written `AuthorizationProvider` enforced at the same
choke points as the built-in one.

**Result:** Exit 0, no traceback. The custom decision was honoured on both the
route gate and the per-resource gate.

---

### 06_manage_users_and_roles.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Serves the `/authz` admin API through `AgentOS.serve()`. Started
in the background and driven over HTTP, then terminated.

**Result:** Admin `GET /users` and `GET /authz/roles` returned 200; an
unauthenticated request returned 401; a viewer token on an admin route returned
403; a viewer read returned 200.

---

### 10_fga_relationship_based.py

**Status:** PASS

**Test mode:** LIVE (in-memory FGA store)

**Description:** Relationship-based access through the `FGAClient` protocol. No
OpenFGA server is required — the example ships a stand-in implementing the same
two methods `OpenFGAClient` implements.

**Result:** Exit 0, no traceback. alice read and run allowed via her
relationship; bob and carol denied.

---

### 09_idp_workos_auth0.py

**Status:** PASS

**Test mode:** LIVE (offline, self-minted JWKS)

**Description:** An external identity provider owns identity while AgentOS
enforces what each role may do. Also exercises the token plumbing: a foreign
signing key and a foreign issuer.

**Result:** Exit 0, no traceback. Member run and read 200; guest and no-role 403;
admin 200; a token signed by a different key 401; a token from an untrusted
issuer 401.

Note: the wrong-issuer case returned 200 before `AuthorizationConfig(issuer=...)`
was implemented — the kwarg was silently dropped and the `iss` claim was never
verified. It is now enforced, and this example is the regression demo for it.

---

### console.html

**Status:** PASS

**Test mode:** LIVE (driven in a real Chrome via playwriter)

**Description:** The static browser console for the `/authz` admin API, served
from `http://localhost:3000` (a CORS-allowed origin) against a running
`06_manage_users_and_roles.py` and driven end to end in a real browser: connect
with the printed admin token, become bob (viewer), exercise the playground,
change his role live, and read every admin tab.

**Result:** Connect succeeded (`GET /authz/scopes` 200) and the persona bar
loaded. As bob (viewer): look 200, run 403 with the correct required-scope
message. After promoting bob to runner from the console (same token), the same
run returned 200; demoting back to viewer also took effect. Users, Roles and
Scope-catalog tabs rendered from the API; the Change-audit tab showed the live
`user.assigned bob ["viewer"] -> ["runner"]` entry and the Decisions tab showed
every allow/deny with its jti reference. No console errors.

---

### 03_directory_without_auth.py

**Status:** PASS

**Test mode:** LIVE (real gpt-5.5 runs via OpenAIResponses)

**Description:** The `AgentOS(db=db, user_isolation=True, user_directory=True)`
shape -- a user directory and per-user isolation with NO auth at all. Drives real,
unauthenticated runs through a `TestClient` (a form `user_id`, no Authorization
header) and checks the directory auto-provisions from them, then shows the
`disabled` flag is advisory without a verified identity.

**Result:** Boot logged the expected one-line warning that the disabled kill
switch and isolation are advisory. Directory started empty; a no-token run as
`chegizkhan` auto-registered him (`get` False -> True), and `subotai` registered
on his run too, leaving a two-person roster. After `set_disabled("chegizkhan",
True)`, his next no-token run still returned ALLOWED (200) -- confirming the flag
is advisory, not enforced, without auth. Points to 02_managed_users.py for the
enforced kill switch.

---

### 07_manage_users.py

**Status:** PASS

**Test mode:** LIVE (driven via TestClient; no model calls needed)

**Description:** A users-ONLY serving backend -- a user directory with authorization
(scope plane) but NO role store, mounting only `/users`. The users-only counterpart
of 06_manage_users_and_roles.py, for a frontend that renders a plain User-Management
page (no role selector).

**Result:** Admin token (agent_os:admin scope) listed the seeded users
(admin@example.com, bob, carol) and added `dave` -- both 200. A token with no admin
scope was refused (403). After `PATCH /users/bob {"disabled": true}`, bob's next
request bounced (403) -- the kill-switch is enforced here because auth is on. Route
inspection confirmed NO `/authz` surface exists (only `/users`, `/users/{user_id}`),
so a frontend gets a clean users-only API.

---

### 11_directory_metrics.py

**Status:** PASS

**Test mode:** LIVE (driven via TestClient; no model calls needed)

**Description:** Seeds a six-person directory (three of them backdated) and a role
store, then reads `GET /metrics/users` through the AgentOS pipeline. Checks that the
role decides access, that the date range bounds only the per-day series, and that a
delete moves every number on the next read with no refresh step.

**Result:** Exit 0. A subject with no role was refused (403); an analyst holding
metrics:read and the admin both read the endpoint (200). Counts came back as total 6,
active 5, disabled 1, without_role 2; the series had three days (2, 1, 3) and the role
breakdown admin 1, analyst 2, viewer 1. `starting_date=today` returned only today's
point with the total still 6. After deleting carol the total dropped to 5 and analyst
to 1 on the very next read.

