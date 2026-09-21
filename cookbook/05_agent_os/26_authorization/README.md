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
decide who is allowed, without calling a model. `15_fga_relationship_based.py` runs
against an in-memory FGA store; point it at OpenFGA or WorkOS FGA with
`pip install "agno[fga]"`. `13_idp_workos_auth0.py` mints its own throwaway keys, so
it runs offline against a simulated issuer.

## Files

| File | Lesson |
|---|---|
| `01_managed_roles.py` | Roles only: define what each role may do and hand people roles through `authz.assign` / `authz.set_role`, no directory |
| `02_managed_users.py` | The credential-less user directory and the disabled-user kill switch that outlives a valid token |
| `03_directory_without_auth.py` | `AgentOS(db=db, user_isolation=True, user_directory=True)` with NO auth: a roster + per-user isolation that key off the run's user_id (advisory without auth) |
| `04_managed_roles_sessions.py` | Roles protecting real data: who may delete a chat session |
| `05_managed_roles_audit.py` | The audit trail — who changed what, plus every allow/deny decision |
| `06_complete_setup.py` | The complete built-in setup on one page: roles, a seeded directory with auto-provision, audit, two enforcement planes and the admin API, then real requests printing ALLOWED or BLOCKED |
| `07_manage_users_and_roles.py` | Serve the `/authz` user and role management API for a frontend |
| `08_manage_users.py` | Serve a users-ONLY management API (`/users`, no roles, no `/authz`) for a plain User-Management frontend |
| `09_user_management_metrics.py` | `GET /users/metrics`: directory size, users created per day, and users per role, computed live for a User Management page |
| `10_idp_roles_claim.py` | `Authorization(roles_claim=...)`: the identity provider names the caller's role on the token, you `define_role` what it may do, no per-user `assign` |
| `11_custom_audit_sink.py` | `Authorization(audit=...)` with your own `AuditSink`: ship both audit trails to a SIEM, a queue, or a file instead of the database |
| `12_custom_authorization_provider.py` | Bring your own decision engine in about thirty lines |
| `13_idp_workos_auth0.py` | Let WorkOS, Auth0, or Okta own identity while you enforce what a role may do |
| `14_custom_policy_engine.py` | `Authorization(engine=...)`: keep managed roles, the audit trail and the `/authz` admin API, but store policy and decide in your own `PolicyEngine` |
| `15_fga_relationship_based.py` | Relationship-based access (ReBAC): "alice may run this because she owns its folder" |
| `console.html` | A small browser console for driving the `/authz` admin API by hand |

## Start Here

`01_managed_roles.py` needs no database server and no model key. It defines three
roles, hands two people a role, makes real requests, and prints ALLOWED or BLOCKED
for each:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/26_authorization/01_managed_roles.py
```

The files read in increasing order of complexity. 01 to 05 stay on the built-in
setup and introduce one piece each: roles, the user directory, the directory with no
auth at all, roles on real data, the audit trail. `06_complete_setup.py` puts every
piece together on one page, and 07 to 09 serve that setup as the admin API for a
frontend. From 10 on, each file replaces one piece of the built-in setup with your
own, ordered by how much you write: the identity provider names the role on the token
(`roles_claim=`, 10), a one-method `AuditSink` (`audit=`, 11), an
`AuthorizationProvider` (12, then 13 against a real IdP with RS256 and JWKS
verification), a `PolicyEngine` behind the admin API (`engine=`, 14), and a
relationship engine composed with the scope plane (15).

`07_manage_users_and_roles.py` and `08_manage_users.py` are the only files that
block: each serves an AgentOS on port 7777 so you can drive the admin API (or
`console.html`) against it.

## Choosing a Tier

| You have | Use |
|---|---|
| Only JWT scopes, no directory | `07_security` — no provider needed |
| No identity provider, want roles in your DB | `01_managed_roles.py` + `02_managed_users.py` |
| An existing IdP (WorkOS / Auth0 / Okta) | `10_idp_roles_claim.py` (roles on the token, definitions in your DB) or `13_idp_workos_auth0.py` (a provider of your own) |
| Your own policy backend, but keep the `/authz` admin API | `14_custom_policy_engine.py` |
| Audit events that belong in your SIEM or log pipeline | `11_custom_audit_sink.py` |
| Permissions that depend on relationships, not roles | `15_fga_relationship_based.py` |
| An authorization service of your own | `12_custom_authorization_provider.py` |

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
