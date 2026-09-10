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
`pip install "agno[roles]"`. No `OPENAI_API_KEY` is needed for most files — they
decide who is allowed, without calling a model. `10_fga_relationship_based.py` runs
against an in-memory FGA store; point it at OpenFGA or WorkOS FGA with
`pip install "agno[fga]"`. `09_idp_workos_auth0.py` mints its own throwaway keys, so
it runs offline against a simulated issuer.

## Files

| File | Lesson |
|---|---|
| `00_quickstart_authorization.py` | Start here. The whole setup in one `Authorization` object: verification, roles, users, audit, and the admin API, borrowing the OS db |
| `01_managed_roles.py` | The same model built from the primitives (`ManagedRoleStore` + `AuthorizationConfig`), for when you want full control |
| `02_managed_users.py` | The credential-less user directory and the disabled-user kill switch that outlives a valid token |
| `03_directory_without_auth.py` | `AgentOS(db=db, user_isolation=True, user_directory=True)` with NO auth: a roster + per-user isolation that key off the run's user_id (advisory without auth) |
| `04_managed_roles_sessions.py` | Roles protecting real data: who may delete a chat session |
| `05_managed_roles_audit.py` | The audit trail — who changed what, plus every allow/deny decision |
| `06_manage_users_and_roles.py` | Serve the `/authz` user and role management API for a frontend |
| `07_manage_users.py` | Serve a users-ONLY management API (`/users`, no role store, no `/authz` roles) for a plain User-Management frontend |
| `08_custom_authorization_provider.py` | Bring your own decision engine in about thirty lines |
| `09_idp_workos_auth0.py` | Let WorkOS, Auth0, or Okta own identity while you enforce what a role may do |
| `10_fga_relationship_based.py` | Relationship-based access (ReBAC): "alice may run this because she owns its folder" |
| `11_user_management_metrics.py` | `GET /users/metrics`: directory size, users created per day, and users per role, computed live for a User Management page |
| `console.html` | A small browser console for driving the `/authz` admin API by hand |

## Start Here

`00_quickstart_authorization.py` needs no database server and no model key. It builds
the whole thing from one `Authorization` object, makes real requests, and prints
ALLOWED or BLOCKED for each:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/26_authorization/00_quickstart_authorization.py
```

`01_managed_roles.py` builds the same model from the underlying primitives, for when
you want to hold each piece yourself. Then read `02_managed_users.py` for the
directory tier, and `08_custom_authorization_provider.py` once you want your own
decision logic.

`06_manage_users_and_roles.py` is the only file that blocks: it serves an AgentOS on
port 7777 so you can drive the admin API (or `console.html`) against it.

## Choosing a Tier

| You have | Use |
|---|---|
| Only JWT scopes, no directory | `07_security` — no provider needed |
| No identity provider, want roles in your DB | `01_managed_roles.py` + `02_managed_users.py` |
| An existing IdP (WorkOS / Auth0 / Okta) | `09_idp_workos_auth0.py` |
| Permissions that depend on relationships, not roles | `10_fga_relationship_based.py` |
| An authorization service of your own | `08_custom_authorization_provider.py` |

Providers compose: pass a list to run several planes at once (for example token
scopes for operators alongside a managed role store for end users), and a request
is allowed when any plane allows it.

## Token Verification

Authorization decides what a caller may do; it does not decide who they are. Pin
both claims that establish that, especially when more than one issuer can mint
tokens your keys verify:

```python
AuthorizationConfig(
    verification_keys=[PUBLIC_KEY],
    verify_audience=True,
    audience=OS_ID,                          # this AgentOS, not another one
    issuer="https://acme.example-idp.com/",  # your IdP, not another trusted one
)
```

## Additional Resources

- [AgentOS Security documentation](https://docs.agno.com/agent-os/security/overview)
- `07_security` — authentication, JWT scopes, service accounts, user isolation
