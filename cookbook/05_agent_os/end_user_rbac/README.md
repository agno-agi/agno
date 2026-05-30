# End-User RBAC

Examples for the "developer mints scoped tokens for THEIR end-users" flow.

The existing `cookbook/05_agent_os/rbac/` directory covers operator-facing
RBAC — humans logging into the AgentOS UI. This directory covers the end-user
case: a developer (e.g. Nia) issuing scoped tokens to their own customers so
each customer only sees their own sessions, memories, and agent runs.

This is Track A (Phase 1) of the user-governance product. Track B will add
persistent subjects, scope templates, audit logs, and a `/tokens` endpoint —
the cookbooks here use `AgentOS.issue_token()` directly, which is the
unmanaged primitive that Track B builds on top of.

## Prerequisites

```bash
export AGNO_JWT_SIGNING_KEY="a-long-random-string-at-least-32-chars-please"
export OPENAI_API_KEY="..."
./scripts/demo_setup.sh   # if not already done
```

`AGNO_JWT_SIGNING_KEY` is the symmetric (HS256) secret that AgentOS uses to
both sign tokens via `issue_token()` and verify incoming tokens. In production
prefer a long random value (>= 32 bytes); for local testing any non-empty
string works.

## Examples

### 1. Basic — issue and verify a scoped token

```bash
.venvs/demo/bin/python cookbook/05_agent_os/end_user_rbac/01_basic_issue_and_verify.py
```

Starts a server, mints a token for end-user "alice" with `agents:read` +
permission to run `research-agent`, and prints curl commands so you can verify:

- Alice can list agents.
- Alice can run `research-agent`.
- Alice **cannot** delete the agent (no `agents:delete` scope) — expect 403.
- An admin token can do everything.

### 2. End-user simulation — per-subject data isolation

```bash
.venvs/demo/bin/python cookbook/05_agent_os/end_user_rbac/02_end_user_simulation.py
```

Boots an in-process server, mints tokens for `alice` and `bob`, has each one
chat with the agent, then lists `/sessions` for each token. With
`user_isolation=True` on `AuthorizationConfig`, the JWT `sub` claim is
threaded into every DB read — so alice only sees alice's sessions, and bob
only sees bob's. The script asserts the isolation invariant at the end.

This is the demo to run when explaining the product to a customer: "your
20,000 users each get their own token, and our framework guarantees they only
ever see their own data."

### 3. Revocation preview

```bash
.venvs/demo/bin/python cookbook/05_agent_os/end_user_rbac/03_revocation_preview.py
```

Demonstrates `jti`-based revocation using a tiny in-memory denylist. Every
token from `issue_token()` carries a unique `jti` claim, so revocation is
just "remember the jti and reject requests carrying it." This is a *preview*
of Track B — Track B will persist the denylist in the OS DB and add an
audit log.

### 4. SaaS flow — `POST /tokens` endpoint

```bash
.venvs/demo/bin/python cookbook/05_agent_os/end_user_rbac/04_tokens_endpoint.py
```

The cookbook that matters for the managed-service pitch. The developer's
backend doesn't run the AgentOS Python process — they hit the AgentOS HTTP
API to mint tokens for their end-users.

It demonstrates:

- **Bootstrap token** with `tokens:issue` scope, held in the dev's backend env
  (never exposed to end-users).
- **`POST /tokens`** — Nia's backend calls this with the bootstrap token to
  mint a short-lived token for end-user "alice".
- **Alice can use her token** to list agents (200) but not delete (403).
- **Alice cannot escalate** by calling `POST /tokens` herself (403 — she lacks
  `tokens:issue`).
- **Guardrail**: even Nia's backend cannot ask `/tokens` to mint a token
  carrying `tokens:issue` itself (400) — that would be a privilege-escalation
  footgun.

This is the flow the SaaS product is built on. Track B layers persisted
subjects, scope templates, revocation, and audit on top.

## Two ways to mint tokens

| Mechanism | Who calls it | When to use |
|-----------|--------------|-------------|
| `agent_os.issue_token(...)` Python helper | Dev's backend, if they're running the AgentOS Python process | Self-hosted: dev imports Agno, holds the signing key |
| `POST /tokens` HTTP endpoint | Dev's backend over HTTP | SaaS / managed: dev does NOT run the Python process, only consumes the HTTP API |

Both paths produce the same kind of JWT — same claims, same signing key, same
audience. The HTTP endpoint is itself gated by the `tokens:issue` scope, so
the dev's backend must hold a bootstrap token before it can mint anything.

## What `issue_token()` produces

```python
agent_os.issue_token(
    subject="alice",            # JWT `sub`
    scopes=["agents:run"],      # JWT `scopes`
    ttl_seconds=3600,           # JWT `exp` = now + 1h
    session_id=None,            # optional JWT `session_id`
)
```

The token's audience (`aud`) is pinned to the AgentOS `id` so it cannot be
replayed against a different OS instance. Every token also includes a `jti`
(unique JWT ID) for revocation/audit purposes.

## Track B: User Governance & RBAC (the $2k/mo product)

Track B layers persisted state on top of the Track A primitives. Enable it by
passing `governance=True` to `AgentOS(...)`. AgentOS auto-creates four tables
(`os_scope_templates`, `os_end_users`, `os_api_tokens`, `os_audit_log`) on
your existing `db` adapter — no extra DB connection.

### What you get

- **Scope templates** — name a bundle of scopes once (`free-tier`,
  `pro-tier`), reuse forever.
- **Persisted end-users** — register each customer once with a template
  assignment; mint tokens for them on every login without re-stating scopes.
- **Token revocation** — `DELETE /tokens/{jti}` revokes a token; the next
  request 401s once the in-process cache TTL (~30s) expires.
- **Audit log** — every governance event and every minted/revoked token is
  recorded. `GET /audit-log` answers the SOC2-style "who did what?" question.
- **Soft delete** — `DELETE /end-users/{id}` flips the user to `deleted` and
  revokes all of their active tokens. Audit history is preserved forever.

### Track B examples

| # | File | What it demonstrates |
|---|------|----------------------|
| 5 | [`05_governance_crud.py`](05_governance_crud.py) | Templates and end-user CRUD basics. |
| 6 | [`06_governed_issuance_and_revocation.py`](06_governed_issuance_and_revocation.py) | Mint a token from a template, use it, revoke it, watch the next request 401. |
| 7 | [`07_tier_upgrade.py`](07_tier_upgrade.py) | Move alice from `free-tier` to `pro-tier`; new tokens reflect new scopes automatically. |
| 8 | [`08_nia_onboarding_e2e.py`](08_nia_onboarding_e2e.py) | The full "Nia onboards three customers and watches the audit log" story. |

### Endpoint summary

| Method + path | Required scope | Notes |
|---------------|----------------|-------|
| `GET    /scope-templates` | `templates:read` | |
| `POST   /scope-templates` | `templates:write` | Refuses templates that grant `tokens:issue` |
| `PATCH  /scope-templates/{id}` | `templates:write` | |
| `DELETE /scope-templates/{id}` | `templates:delete` | Refuses delete while users reference it |
| `GET    /end-users` | `users:read` | Filter by `status` / `template_id` |
| `POST   /end-users` | `users:write` | |
| `PATCH  /end-users/{id}` | `users:write` | Tier change happens here |
| `DELETE /end-users/{id}` | `users:delete` | Soft delete + revoke tokens |
| `POST   /end-users/{id}/tokens` | `tokens:issue` | Mints using user's template scopes |
| `GET    /end-users/{id}/tokens` | `tokens:read` | |
| `DELETE /tokens/{jti}` | `tokens:revoke` | |
| `GET    /audit-log` | `audit:read` | Filter by `external_id` / `action` / `limit` |

### Operator vs Nia: who calls what

- **Operator** (the AgentOS administrator) holds an `agent_os:admin` token.
  Mints the bootstrap token for Nia, manages Nia's tenancy.
- **Nia's backend** holds the bootstrap token (long-lived, lives in their env
  var). Calls every governance endpoint above. Never gives this token to
  end-users.
- **End-users** (Nia's customers) hold short-lived tokens minted from their
  template. They never touch `/scope-templates`, `/end-users`, `/tokens/*` or
  `/audit-log` — the scopes on their tokens don't allow it.
