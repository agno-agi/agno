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

## Going to Track B

Once Track B ships, the recommended path is:

```python
# Track A (today)
token = agent_os.issue_token(subject="alice", scopes=[...])

# Track B (coming)
agent_os.users.create(id="alice", template="pro-tier")
token = agent_os.users.issue_token(subject="alice")
# scopes are derived from the assigned template; revocation/audit are managed
```

The Track A primitive will continue to work — Track B's helpers will sit on
top of it.
