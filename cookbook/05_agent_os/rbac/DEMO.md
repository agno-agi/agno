# AgentOS authorization PoC — end to end

What this is: agno deciding **who is allowed to do what** with agents,
sessions, etc., on top of whatever login the customer already uses.

PR: https://github.com/agno-agi/agno/pull/8221

## Run it yourself (about a minute)

```bash
git clone https://github.com/agno-agi/agno.git
cd agno && git checkout poc/agentos-authz-providers
pip install -e "libs/agno[casbin,openai]"

cd cookbook/05_agent_os/rbac
python idp_enforce_only.py        # scenario 1: they have WorkOS, we just enforce
python managed_roles_api.py       # scenario 2: no login service, we manage it (+ audit log)
python casbin_external_idp.py     # scenario 3: a mix of both
```

No OpenAI key needed — each file signs in fake users, makes real requests, and
prints ALLOWED / BLOCKED. You're seeing the actual authorization layer decide.
Every file opens with a plain-English explainer; start with `managed_roles.py`.

## What you'll see (captured output)

## Scenario 1 — they have a login service (WorkOS); we only enforce

```
================================================================================
THEY HAVE A LOGIN SERVICE - WE ONLY ENFORCE (no user store on our side)
================================================================================
  the login service put each person's role on their token. we just read it.

  alice (token says role=member) RUN agent         -> ALLOWED (200)  member can run
  alice (token says role=member) LOOK at agent     -> ALLOWED (200)  member can look
  carol (token says role=guest)  LOOK at agent     -> BLOCKED (403)  guest has no permissions -> bounced
  dave  (token has no role)      LOOK at agent     -> BLOCKED (403)  no role on the token -> bounced
  root  (token says role=admin)  RUN agent         -> ALLOWED (200)  admin can do anything
================================================================================
the point: we stored no users and no assignments. WorkOS owns 'who is a
member'. we only own 'what a member can do', and we enforce it on every call.
================================================================================
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

## Scenario 3 — a mix of both at once

```
================================================================================
A MIX: SOME USERS FROM THE LOGIN SERVICE, SOME MANAGED BY US
================================================================================
  everyone below is asking to look at the same agent.

  alice  (login service, role on token = member) -> ALLOWED (200)  use the token's role -> in
  carol  (login service, role on token = guest)  -> BLOCKED (403)  use the token's role -> bounced
  bob    (not in login service, we listed as member) -> ALLOWED (200)  no role on token, fall back to our list -> in
  dave   (not in login service, no role anywhere) -> BLOCKED (403)  no role on token, none in our list -> bounced
================================================================================
the point: one AgentOS handles both. if the token brings a role we use it;
if not, we fall back to our own list. same agent, same protection, either way.
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

## Building block — turning access on/off live

```
==============================================================================
TURNING ACCESS ON AND OFF, LIVE
==============================================================================
  bob holds ONE login card the whole time. we never give him a new one.

  bob asks to look at the agent      -> BLOCKED (403)  starts with no access -> bounced

  >> grant bob access now (while the server is running)...

  bob asks again (same card)         -> ALLOWED (200)  access flipped on -> he's in

  >> ...now cut his access...

  bob asks again (same card)         -> BLOCKED (403)  access flipped off -> bounced again
==============================================================================
the point: you can revoke access instantly. bob never logged in again and
his card never changed - only the rule on the server side did.
==============================================================================
```

