# AgentOS Authorization

This lesson covers pluggable authorization: swapping the built-in scope check for
a richer decision model. `07_security` gets a caller authenticated and enforces
JWT scopes; this lesson replaces the decision itself — managed roles stored in
your database, a credential-less user directory, an external identity provider,
relationship-based access, or a provider you write yourself.

The same `AuthorizationProvider` seam is enforced at every choke point: the REST
route gate, the per-resource gate, the WebSocket gates, and the MCP tool gate.

## Prerequisites

Managed roles need a SQL database; the examples use throwaway SQLite under
`tmp/`, so nothing external is required. Install the extra with
`pip install "agno[os]"`. No `OPENAI_API_KEY` is needed for most files — they
decide who is allowed, without calling a model. `14_fga_relationship_based.py` runs
against an in-memory FGA store; point it at OpenFGA or WorkOS FGA with
`pip install "agno[fga]"`. `12_idp_workos_auth0.py` mints its own throwaway keys, so
it runs offline against a simulated issuer.

## Files

| File | Lesson |
|---|---|
| `00_quickstart_authorization.py` | Start here. Verification, roles, audit and the admin API on one `Authorization` object, the user directory on `AgentOS(user_directory=True)`, all on the OS db |
| `01_managed_roles.py` | Roles only: define what each role may do and hand people roles through `authz.assign` / `authz.set_role`, no directory |
| `02_managed_users.py` | The credential-less user directory and the disabled-user kill switch that outlives a valid token |
| `03_directory_without_auth.py` | `AgentOS(db=db, user_isolation=True, user_directory=True)` with NO auth: a roster + per-user isolation that key off the run's user_id (advisory without auth) |
| `04_managed_roles_sessions.py` | Roles protecting real data: who may delete a chat session |
| `05_managed_roles_audit.py` | The audit trail — who changed what, plus every allow/deny decision |
| `06_manage_users_and_roles.py` | Serve the `/authz` user and role management API for a frontend |
| `07_manage_users.py` | Serve a users-ONLY management API (`/users`, no roles, no `/authz`) for a plain User-Management frontend |
| `08_user_management_metrics.py` | `GET /users/metrics`: directory size, users created per day, and users per role, computed live for a User Management page |
| `09_idp_roles_claim.py` | `Authorization(roles_claim=...)`: the identity provider names the caller's role on the token, you `define_role` what it may do, no per-user `assign` |
| `10_custom_audit_sink.py` | `Authorization(audit=...)` with your own `AuditSink`: ship both audit trails to a SIEM, a queue, or a file instead of the database |
| `11_custom_authorization_provider.py` | Bring your own decision engine in about thirty lines |
| `12_idp_workos_auth0.py` | Let WorkOS, Auth0, or Okta own identity while you enforce what a role may do |
| `13_custom_policy_engine.py` | `Authorization(engine=...)`: keep managed roles, the audit trail and the `/authz` admin API, but store policy and decide in your own `PolicyEngine` |
| `14_fga_relationship_based.py` | Relationship-based access (ReBAC): "alice may run this because she owns its folder" |
| `console.html` | A small browser console for driving the `/authz` admin API by hand |

## Start Here

`00_quickstart_authorization.py` needs no database server and no model key. It builds
the whole thing from one `Authorization` object, makes real requests, and prints
ALLOWED or BLOCKED for each:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/26_authorization/00_quickstart_authorization.py
```

The files read in increasing order of complexity. `01_managed_roles.py` is roles only,
for when you do not need a directory; `02_managed_users.py` adds the directory tier, and
03 to 05 stay on the built-in setup (no auth at all, roles on real data, the audit
trail). 06 to 08 serve the admin API for a frontend. From 09 on, each file replaces one
piece of the built-in setup with your own, ordered by how much you write: the identity
provider names the role on the token (`roles_claim=`, 09), a one-method `AuditSink`
(`audit=`, 10), an `AuthorizationProvider` (11, then 12 against a real IdP with RS256 and
JWKS verification), a `PolicyEngine` behind the admin API (`engine=`, 13), and a
relationship engine composed with the scope plane (14).

`06_manage_users_and_roles.py` is the only file that blocks: it serves an AgentOS on
port 7777 so you can drive the admin API (or `console.html`) against it.

## Choosing a Tier

| You have | Use |
|---|---|
| Only JWT scopes, no directory | `07_security` — no provider needed |
| No identity provider, want roles in your DB | `01_managed_roles.py` + `02_managed_users.py` |
| An existing IdP (WorkOS / Auth0 / Okta) | `09_idp_roles_claim.py` (roles on the token, definitions in your DB) or `12_idp_workos_auth0.py` (a provider of your own) |
| Your own policy backend, but keep the `/authz` admin API | `13_custom_policy_engine.py` |
| Audit events that belong in your SIEM or log pipeline | `10_custom_audit_sink.py` |
| Permissions that depend on relationships, not roles | `14_fga_relationship_based.py` |
| An authorization service of your own | `11_custom_authorization_provider.py` |

Providers compose: pass a list to run several planes at once (for example token
scopes for operators alongside a managed role store for end users), and a request
is allowed when any plane allows it.

## Token Verification

Authorization decides what a caller may do; it does not decide who they are. Pin
both claims that establish that, especially when more than one issuer can mint
tokens your keys verify:

```python
Authorization(
    verification_keys=[PUBLIC_KEY],
    verify_audience=True,
    audience=OS_ID,                          # this AgentOS, not another one
    issuer="https://acme.example-idp.com/",  # your IdP, not another trusted one
)
```

## Additional Resources

- [AgentOS Security documentation](https://docs.agno.com/agent-os/security/overview)
- `07_security` — authentication, JWT scopes, service accounts, user isolation
