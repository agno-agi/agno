# AgentOS authorization PoC — end to end

What this is: agno deciding **who is allowed to do what** with agents,
sessions, etc., on top of whatever login the customer already uses.

PR: https://github.com/agno-agi/agno/pull/8221

## Run it yourself (about a minute)

```bash
git clone https://github.com/agno-agi/agno.git
cd agno && git checkout poc/agentos-authz-providers
pip install -e "libs/agno[roles,openai]"

cd cookbook/05_agent_os/rbac
python idp_workos_auth0.py        # scenario 1: they have WorkOS/Auth0, we just enforce
python managed_roles_api.py       # scenario 2: no login service, we manage it (+ audit log)
python managed_users.py           # scenario 2: the user directory + instant disable
```

No OpenAI key needed — each file signs in fake users, makes real requests, and
prints ALLOWED / BLOCKED. You're seeing the actual authorization layer decide.
Every file opens with a plain-English explainer; start with `managed_roles.py`.

## What you'll see (captured output)

## Scenario 1 — they have a login service (WorkOS/Auth0); we only enforce

```
====================================================================================
LOGIN SERVICE OWNS IDENTITY + ROLES - WE ONLY ENFORCE
====================================================================================
  the login service signs the token and stamps the role. we verify it and
  decide what that role may do. no users or assignments stored on our side.

  alice (roles=['member']) RUN the agent               -> ALLOWED (200)  member can run
  bob   (roles='member')   LOOK at agent               -> ALLOWED (200)  single-string role also works
  carol (roles=['guest'])  LOOK at agent               -> BLOCKED (403)  guest maps to nothing -> bounced
  dave  (no roles claim)   LOOK at agent               -> BLOCKED (403)  no role -> bounced
  root  (roles=['admin'])  RUN the agent               -> ALLOWED (200)  admin can do anything

  the token plumbing is enforced too (not just the role):

  mallory (token signed by a DIFFERENT key)            -> BLOCKED (401)  signature doesn't match the JWKS -> rejected
  eve (valid role but wrong issuer)                    -> BLOCKED (401)  issuer not trusted -> rejected
====================================================================================
the point: the login service owns WHO has a role; the ~30-line provider owns
WHAT a role can do. tokens are verified against the service's published keys,
and pinned to the right issuer + audience. nothing about users is stored here.
====================================================================================
```

## Scenario 2 — no login service; we manage users + roles (and log every change)

```
================================================================================
MANAGING ROLES OVER THE WEB (and who's allowed to)
================================================================================
  alice = admin (allowed to manage) | bob = normal user | anon = nobody logged in

  first, who can even use the management endpoints?
  alice (admin) opens the roles admin            -> ALLOWED (200)  admins can
  bob (normal)  opens the roles admin            -> BLOCKED (403)  normal users can't -> bounced
  nobody        opens the roles admin            -> BLOCKED (401)  not logged in -> bounced harder

  now watch alice give bob a new power, live:
  bob tries to RUN an agent (before)             -> BLOCKED (403)  bob can't run yet
    (alice created a 'runner' role that can run agents)
    (alice gave bob the 'runner' role)
  bob tries to RUN an agent (after)              -> ALLOWED (200)  same bob, now allowed
    (alice took the 'runner' role back)
  bob tries to RUN an agent (after revoke)       -> BLOCKED (403)  bounced again
================================================================================

THE RECORD: every change is logged - who did it, what changed, before -> after.
(this is what a security review wants to see)
  system role.set_scopes    viewer   [] -> ["agents:read"]
  system role.set_scopes    admin    [] -> ["agent_os:admin"]
  system user.assigned      alice    [] -> ["admin"]
  system user.assigned      bob      [] -> ["viewer"]
  alice  role.set_scopes    runner   [] -> ["agents:run"]
  alice  user.assigned      bob      ["viewer"] -> ["viewer", "runner"]
  alice  user.unassigned    bob      ["viewer", "runner"] -> ["viewer"]

```

## Scenario 2 (cont.) — the user directory + instant disable

```
================================================================================
A USER DIRECTORY - no identity provider, just AgentOS
================================================================================

  the directory (asked for by alice, an admin):
    - alice    alice@co     roles=['admin']  disabled=False
    - bob      bob@co       roles=['viewer']  disabled=False

  bob is a viewer, so he can look at the agent:
  bob asks to LOOK at the agent                    -> ALLOWED (200)  viewers can look

  >> now an admin DISABLES bob (e.g. he left the company)...

  bob asks to LOOK at the agent                    -> BLOCKED (403)  same valid token, but he's blocked now

  >> ...bob is back, re-enable him...

  bob asks to LOOK at the agent                    -> ALLOWED (200)  allowed again, instantly
================================================================================
the point: you keep the list of users and an off-switch per person. disabling
someone blocks their NEXT request even though their token is still valid -
something you can't do with tokens alone. no passwords are ever stored here.
================================================================================
```

## Building block — what roles are

```
==============================================================================
WHO CAN DO WHAT - three roles, two people
==============================================================================
  roles:  viewer = look at agents | member = look + run | admin = anything
  people: bob is a viewer         | alice is an admin
  below, each person makes a real request. ALLOWED = got in, BLOCKED = bounced.

  bob (viewer)  asks to LOOK at the agent        -> ALLOWED (200)  viewers can look
  bob (viewer)  asks to RUN the agent            -> BLOCKED (403)  viewers can't run, so he's bounced

  >> now we make bob a 'member' while the server is running...

  bob (member)  asks to RUN the agent            -> ALLOWED (200)  same bob, same token, now allowed

  >> ...and now we take the 'member' role back...

  bob (no role) asks to RUN the agent            -> BLOCKED (403)  bounced again, instantly
  alice (admin) asks to RUN the agent            -> ALLOWED (200)  admins can do anything
==============================================================================
the point: you control access by handing out roles, and a change takes effect
on the very next request - no new login, no new token.
==============================================================================
```

## Building block — roles protecting real data (deleting sessions)

```
==============================================================================
WHO CAN TOUCH THE SAVED SESSIONS
==============================================================================
  bob = support (look only) | val = operator (look, edit, delete)
  saved sessions right now: 2

  bob (support)  tries to LOOK at sessions     -> ALLOWED (200)  support can look
  bob (support)  tries to RENAME a session     -> BLOCKED (403)  editing isn't allowed -> bounced
  bob (support)  tries to DELETE a session     -> BLOCKED (403)  deleting isn't allowed -> bounced
  val (operator) tries to DELETE a session     -> ALLOWED (204)  operators can delete -> done for real

  saved sessions now: 1  (was 2 - the operator's delete really happened)
==============================================================================
the point: the support person was stopped before any data was touched.
only the operator's delete went through, and you can see the count drop.
==============================================================================
```


