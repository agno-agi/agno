# Test Log: 26_authorization

Last updated: 2026-07-27

All examples were run with `.venvs/demo/bin/python` against the branch's library.
None of the local examples need a database server, a model key, or an external
authorization engine: managed roles persist to throwaway SQLite under `tmp/`, the
FGA example runs on an in-memory store, and the IdP example mints its own
throwaway keys.

### managed_roles.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Defines three roles and two subjects, then makes real requests
through the AgentOS pipeline and prints ALLOWED or BLOCKED for each, including a
role change applied while the server is running.

**Result:** Exit 0, no traceback. Viewer reads allowed and runs blocked; the
runtime role change took effect on the next request with no new token.

---

### managed_users.py

**Status:** PASS

**Test mode:** LIVE

**Description:** The credential-less user directory: auto-provisioning a row from
token claims and the disabled-user kill switch.

**Result:** Exit 0, no traceback. A disabled user is denied at the enforcement
point while still holding a valid, unexpired token.

---

### managed_roles_sessions.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Role enforcement over real session data — who may delete a chat
session.

**Result:** Exit 0, no traceback. Delete allowed for the owning role, blocked
otherwise.

---

### managed_roles_audit.py

**Status:** PASS

**Test mode:** LIVE

**Description:** The audit trail: role-change events plus a record of every
allow/deny decision.

**Result:** Exit 0, no traceback. Both the change trail and the decision trail
were written and printed.

---

### custom_authorization_provider.py

**Status:** PASS

**Test mode:** LIVE

**Description:** A hand-written `AuthorizationProvider` enforced at the same
choke points as the built-in one.

**Result:** Exit 0, no traceback. The custom decision was honoured on both the
route gate and the per-resource gate.

---

### manage_users_and_roles.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Serves the `/authz` admin API through `AgentOS.serve()`. Started
in the background and driven over HTTP, then terminated.

**Result:** Admin `GET /authz/users` and `GET /authz/roles` returned 200; an
unauthenticated request returned 401; a viewer token on an admin route returned
403; a viewer read returned 200.

---

### fga_relationship_based.py

**Status:** PASS

**Test mode:** LIVE (in-memory FGA store)

**Description:** Relationship-based access through the `FGAClient` protocol. No
OpenFGA server is required — the example ships a stand-in implementing the same
two methods `OpenFGAClient` implements.

**Result:** Exit 0, no traceback. alice read and run allowed via her
relationship; bob and carol denied.

---

### idp_workos_auth0.py

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

**Status:** NOT RUN

**Description:** A static browser console for driving the `/authz` admin API by
hand against `manage_users_and_roles.py`. Nothing to execute in CI.
