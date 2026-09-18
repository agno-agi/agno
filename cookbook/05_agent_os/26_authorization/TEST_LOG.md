# Test Log: 26_authorization

Last updated: 2026-09-18 (after the store fold: `RoleStore` is private behind `Authorization`
(`authz.set_role`, `authz.set_role_scopes`, `authz.roles_of`, `authz.audit_log`,
`authz.decisions`, ...), `UserStore` is folded into `UserDirectory` (the directory IS the roster:
`users.upsert`, `users.set_disabled`, ...), and the plumbing exports are gone. Re-ran
00/01/02/03/04/05/08/09/10/11 plus the three new files 12/13/14 end to end, all exit 0, and
booted 06/07 without serving to confirm they mount `/authz` and `/users` with `/users/metrics`.
Run with the demo venv and `PYTHONPATH` pointed at the branch's `libs/agno`.)

Earlier (2026-09-14): after the rename to `RoleStore` / `UserStore` / `UserDirectory` and the
`GET /users/metrics` endpoint landed on this branch: re-ran 00/01/02/03/04/05/08/09/10/11 end to end,
all exit 0, and booted 06/07 without serving to confirm they mount `/authz` and `/users` with
`/users/metrics`.

Earlier (2026-09-11): the user directory is now fully separate from `Authorization`. It is the
top-level `AgentOS(user_directory=...)` switch, a peer of `user_isolation`, and its roster is seeded
on the `UserStore` directly (`users.upsert(...)`). `Authorization` never touches it:
`seed()` bootstraps the admin ROLE only, and per-user roles are assigned via `role_store.assign(...)`.
The directory-using cookbooks (00/02/06/07) build the store, seed it, and pass it via
`UserDirectory(user_store=...)`. Re-ran 00/02 end to end (pass) and 06/07 to boot with the
correct `/authz` + `/users` routes. 03 was already top-level; 01/04/05/08/09/10 are roles-only or
no-directory and unchanged.

Earlier (2026-09-10): migrated 01-10 from AuthorizationConfig/RoleStore to the `Authorization`
object; all re-run clean.

All examples were run with `.venvs/demo/bin/python` against the branch's library.
None of the local examples need a database server, a model key, or an external
authorization engine: managed roles persist to throwaway SQLite under `tmp/`, the
FGA example runs on an in-memory store, and the IdP example mints its own
throwaway keys.

### 00_quickstart_authorization.py

**Status:** PASS

**Test mode:** LIVE (driven via TestClient; no model calls needed)

**Description:** The `Authorization` object carries verification + roles + audit + the
admin API in one object that borrows the OS db; the user directory is separate, a
`UserStore` seeded directly and passed as the top-level
`AgentOS(user_directory=...)`. Defines three roles, bootstraps an admin role, assigns
two users their roles, and makes real requests.

**Result:** alice (admin) ran vault, carol (runner) ran research, bob (viewer) read
research -- all ALLOWED; bob running research BLOCKED (viewer is read-only). dave, an
unknown subject, was JIT-provisioned with the default `viewer` role and could read
(ALLOWED). An operator token carrying `agent_os:admin` scope but no role ran vault
(ALLOWED, via `trust_token_scopes`). `/authz/roles` and `/users` were auto-mounted:
alice (admin) listed both; bob was refused (403). No `include_router` in the file.

---

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

### 11_user_management_metrics.py

**Status:** PASS

**Test mode:** LIVE (driven via TestClient; no model calls needed)

**Description:** Seeds a six-person directory (three of them backdated) and a role
store, then reads `GET /users/metrics` through the AgentOS pipeline. Checks that the
endpoint is admin-only like the rest of `/users`, that the date range bounds only the
per-day series, and that a delete moves every number on the next read with no
refresh step.

**Result:** Exit 0. The analyst was refused (403); the admin read the endpoint (200)
and got total 6, active 5, disabled 1, without_role 2, a three-day series (2, 1, 3)
and the role breakdown admin 1, analyst 2, viewer 1. `starting_date=today` returned
only today's point with the total still 6. After deleting carol the total dropped to
5 and analyst to 1 on the very next read.

Re-ran 2026-09-15 after role display names were added to the responses: each `by_role`
entry now carries `role_slug` and `role_name` ("Administrator", "Data analyst", and "viewer"
for the role defined without one), and `GET /users/bob` returned `role_slug analyst` with
`role_name Data analyst`. Exit 0, same counts as above.

---

### 12_idp_roles_claim.py

**Status:** PASS

**Test mode:** LIVE (driven via TestClient; no model calls needed)

**Description:** `Authorization(roles_claim="roles")`: roles are defined once in code and the
token names which role the caller holds. Exercises a list-valued claim (Auth0 style), a
string-valued claim (WorkOS style), an undefined role on the token, a token with no claim and
no stored assignment, a token with no claim but a stored `authz.assign`, and admin via a
role on the token.

**Result:** Exit 0. member ran the agent (200); viewer read (200) but could not run (403);
the undefined `guest` role and the claim-less unassigned user were refused (403); the
claim-less user with a stored viewer assignment read (200); the token-role admin listed
`/authz/roles` (200) and the member was refused there (403).

---

### 13_custom_policy_engine.py

**Status:** PASS

**Test mode:** LIVE (driven via TestClient; no model calls needed)

**Description:** `Authorization(engine=...)` with a dict-backed `PolicyEngine` written in
the file: `define_role`, `seed` and `assign` land in the custom engine, the route and
per-resource gates decide through it, and the `/authz` admin API edits a role on it at
runtime. Role metadata lives in the OS db the object borrows.

**Result:** Exit 0. The engine held the three roles and three assignments after setup;
member ran (200), viewer read (200) and could not run (403), an unknown subject was
refused (403); the seeded admin listed `/authz/roles` (200) and widened viewer through
`PUT /authz/roles/viewer/scopes` (200), after which the viewer's run was allowed (200) and
the engine's own dict showed the new scope.

---

### 14_custom_audit_sink.py

**Status:** PASS

**Test mode:** LIVE (driven via TestClient; no model calls needed)

**Description:** `Authorization(audit=<AuditSink>)` with a JSON-lines sink written in the
file. Makes three role changes (one by the system, two by an admin actor) and two real
requests, then tails the file.

**Result:** Exit 0. The file held five lines: three change events (`role.set_scopes` x2,
`user.assigned`) with actor and before/after, and two decision events (`access.allowed`
for the viewer's read, `access.denied` for the unknown caller's run) with the required
scopes in metadata. `authz.decisions()` returned an empty list, as documented for a sink
without a database reader.

