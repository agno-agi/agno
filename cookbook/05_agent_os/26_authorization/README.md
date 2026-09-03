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
decide who is allowed, without calling a model. `fga_relationship_based.py` runs
against an in-memory FGA store; point it at OpenFGA or WorkOS FGA with
`pip install "agno[fga]"`. `idp_workos_auth0.py` mints its own throwaway keys, so
it runs offline against a simulated issuer.

## Files

| File | Lesson |
|---|---|
| `managed_roles.py` | Start here. Roles defined in scope terms, persisted to your DB, changed at runtime with no re-login |
| `managed_users.py` | The credential-less user directory and the disabled-user kill switch that outlives a valid token |
| `managed_roles_sessions.py` | Roles protecting real data: who may delete a chat session |
| `managed_roles_audit.py` | The audit trail — who changed what, plus every allow/deny decision |
| `manage_users_and_roles.py` | Serve the `/authz` user and role management API for a frontend |
| `custom_authorization_provider.py` | Bring your own decision engine in about thirty lines |
| `idp_workos_auth0.py` | Let WorkOS, Auth0, or Okta own identity while you enforce what a role may do |
| `fga_relationship_based.py` | Relationship-based access (ReBAC): "alice may run this because she owns its folder" |
| `console.html` | A small browser console for driving the `/authz` admin API by hand |

## Start Here

`managed_roles.py` needs no database server and no model key. It creates three
roles and two people, makes real requests, and prints ALLOWED or BLOCKED for
each:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/26_authorization/managed_roles.py
```

Then read `managed_users.py` for the directory tier, and
`custom_authorization_provider.py` once you want your own decision logic.

`manage_users_and_roles.py` is the only file that blocks: it serves an AgentOS on
port 7777 so you can drive the admin API (or `console.html`) against it.

## Choosing a Tier

| You have | Use |
|---|---|
| Only JWT scopes, no directory | `07_security` — no provider needed |
| No identity provider, want roles in your DB | `managed_roles.py` + `managed_users.py` |
| An existing IdP (WorkOS / Auth0 / Okta) | `idp_workos_auth0.py` |
| Permissions that depend on relationships, not roles | `fga_relationship_based.py` |
| An authorization service of your own | `custom_authorization_provider.py` |

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
