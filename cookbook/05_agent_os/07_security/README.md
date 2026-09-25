# AgentOS Security

This lesson secures AgentOS from the outside in: authenticate a caller, verify
that the token was issued for this AgentOS, authorize the requested route, and
isolate user-owned data. It also covers cookie transport, trusted claim
plumbing, machine identities, and a bring-your-own token issuer.

## Prerequisites

The local JWT, scope, isolation, and service-account smokes need no external
credentials. Set `OPENAI_API_KEY` only for model-backed agent or team runs.
The WorkOS example additionally needs `WORKOS_CLIENT_ID`, `WORKOS_API_KEY`,
and the `workos` package for live issuer provisioning; without them it runs
the documented construction smoke.

## Files

| File | Lesson |
|---|---|
| `basic_scopes.py` | HS256 JWT authentication, default scopes, admin bypass, and real audience rejection |
| `asymmetric_keys.py` | RS256 signing and the production private-key/public-key boundary |
| `per_resource_scopes.py` | Wildcard and per-id scopes for agents, teams, and workflows |
| `custom_scope_mappings.py` | Add or override route-to-scope mappings |
| `excluded_routes.py` | Mark custom routes as public using fnmatch patterns |
| `cookie_auth.py` | Read a JWT from a secure HTTP-only cookie |
| `jwt_claims.py` | Move trusted claims through request state into agent dependencies |
| `user_isolation.py` | Restrict sessions and other user-owned data to the JWT subject |
| `user_isolation_knowledge.py` | Read shared and owned knowledge content, but modify only owned rows |
| `service_accounts.py` | Mint, use, list, and revoke opaque `agno_pat_` machine credentials |
| `workos_byot.py` | Verify WorkOS JWKS tokens and read scopes from `permissions` |
| `test_scopes.py` | Executable and pytest enforcement matrix |

## Start Here

Run the enforcement test first. It does not call a model or require external
credentials:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/07_security/test_scopes.py
.venv/bin/pytest -q cookbook/05_agent_os/07_security/test_scopes.py
```

Then run the basic server:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/07_security/basic_scopes.py
```

The file performs a local smoke test before serving on port 7777. It prints
reader, runner, and admin tokens that can be used with the REST API.

## Authentication and Authorization

JWT validation answers "who presented this credential, and is it valid?"
Authorization answers "may that identity perform this operation?" Set
`authorization=True` to enforce scopes. Without it, valid JWTs are
authenticated but their scopes are not used to protect routes.

The default scope vocabulary includes:

```text
agent_os:admin
config:read
registry:read
agents:read
agents:run
agents:<agent-id>:read
agents:<agent-id>:run
agents:*:run
teams:read
teams:run
teams:<team-id>:read
teams:<team-id>:run
workflows:read
workflows:run
workflows:<workflow-id>:read
workflows:<workflow-id>:run
sessions:read
sessions:write
```

Per-id and wildcard scopes apply to agents, teams, and workflows. Other
protected AgentOS domains use the global `resource:action` form. See
`agno/os/scopes.py` for the complete current route map.

Custom mappings are additive and replace an entry when the same route key is
provided. Built-in resource routes also apply their resource-aware filtering
and run dependencies, so retain the matching resource scope when adding an
extra application-specific requirement. For example, the custom lesson makes
an agent run require both `agents:run` and `app:execute`.

## Audience Verification

`basic_scopes.py` enables `verify_audience=True`. Its valid tokens carry
`aud="security-demo"` and receive 200 on an allowed route. The in-file smoke
also mints a token for `another-agent-os` and observes a 401 rejection. The
other JWT examples that mint tokens follow the same audience-bound pattern.

If one issuer serves several AgentOS instances, pass an explicit `audience`.
Otherwise, audience verification uses the AgentOS id.

## Excluded Routes

Some routes should be public even when JWT authentication is enabled. Use
`AuthorizationConfig.excluded_route_paths` to mark them:

```python
AgentOS(
    authorization=True,
    authorization_config=AuthorizationConfig(
        verification_keys=[JWT_SECRET],
        excluded_route_paths=[
            "/public/*",     # Wildcard: matches /public/anything
            "/webhooks/*",   # External webhooks with their own auth
        ],
    ),
)
```

Patterns use `fnmatch` syntax - `*` matches any characters including `/`. Note
that `/public/*` does not match the bare `/public` path; list both if needed.
The default exclusions (`/`, `/health`, `/info`, `/docs`, `/redoc`,
`/openapi.json`) are always preserved; custom paths are additive. Use this for
webhooks, login flows, or any route that handles authentication differently.

## Cookies and Trusted Claims

`cookie_auth.py` changes only the credential transport. Scopes and audience
checks remain the same. Production cookies should be secure, HTTP-only, and
paired with an appropriate CSRF defense.

`jwt_claims.py` is intentionally separate from RBAC. It demonstrates:

```text
signed JWT claims
  -> request.state
  -> session_state and dependencies
  -> agent tool arguments
```

Only extract claims from a verified token or a trusted upstream identity
layer. Do not use `validate=False` for internet-facing applications.

## User Isolation

RBAC controls routes; `user_isolation=True` also scopes user-owned database
operations. A non-admin JWT caller is pinned to its `sub` value for session
reads and writes. The configured admin scope bypasses isolation. Unauthenticated
requests remain rejected because the example enables JWT authentication.

Knowledge content adds a shared arm on top of that pinning: a content row with
no owner is org-wide. A non-admin reads their own rows plus the shared ones but
may only modify or delete rows they own, so a scoped `PATCH` or `DELETE` on
shared content returns 403 and a bulk delete clears only the caller's own rows.
Another user's row is invisible, so acting on it returns 404. Only an admin can
remove shared content.

Metrics are stored one bucket per user, with the empty string as the bucket for
unowned sessions. A scoped caller reads only its own bucket. An unscoped read
folds every bucket into one row per date and aggregation period, returned under
a synthesised `{date}_{period}` id.

Schedules have a nullable owner but no shared arm: a scoped caller sees,
updates, and deletes only the schedules it owns, and a schedule name is unique
per owner rather than globally. An unowned schedule is invisible to every
scoped caller but still fires, because the poller claims due schedules across
all users.

## Service Accounts

Service accounts are first-party machine identities. Their plaintext
`agno_pat_` token is returned once, while AgentOS stores only its hash. The
current default scopes are:

```text
agents:run
teams:run
workflows:run
sessions:read
config:read
```

The default expiry is 90 days. Successful verification is cached for 30
seconds by default. Revocation evicts the token immediately on the worker that
handles it; other workers converge when their cache entry expires. Set
`service_account_cache_ttl_seconds=0` when every request must check storage.

Write, delete, admin, and service-account-management scopes are privileged.
Minting them requires `allow_privileged_scopes=true`, and a scoped minter may
grant only scopes it already holds.

## WorkOS BYOT

`workos_byot.py` keeps the AgentOS integration small:

1. Download the WorkOS JWKS to a local file.
2. Set `scopes_claim="permissions"`.
3. Enable authorization and audience verification.
4. Use the WorkOS client id as the expected audience.

The optional demo provisioning ceremony is isolated in
`provision_demo_tokens()`. Without WorkOS credentials, the file constructs an
equivalent local JWKS, builds the protected app, and asserts `/health`,
`/config`, and `/agents` are mounted. A live WorkOS run additionally needs
`WORKOS_CLIENT_ID`, `WORKOS_API_KEY`, and the `workos` Python package.

## Validation

Run the folder checks with:

```bash
.venv/bin/python cookbook/scripts/check_cookbook_pattern.py \
  --base-dir cookbook/05_agent_os/07_security \
  --recursive
.venv/bin/pytest -q cookbook/05_agent_os/07_security/test_scopes.py
```

See `TEST_LOG.md` for the observed live and construction-smoke results.
