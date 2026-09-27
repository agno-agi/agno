# TEST_LOG

### oauth_device_login.py

**Status:** PASS

**Description:** SuperGrok device-flow sign-in run end to end with a real
subscription: verification URL and code printed, browser approval completed,
token stored encrypted on SQLite, and one agent response in each syntax
(model class and xai-responses string) with the system message accepted as
role developer. Also verified through an AgentOS server with XAI_API_KEY
removed from the process environment: chat completed via API and streaming
UI, and again after a server restart with no re-login. The env-gated live
suite passed 3/3 (forced refresh with rotation persist, live /v1/responses
call, catalog fetch).

**Result:** PASS. Pending-poll approval timing not measured (RFC state
machine is unit-covered); in-place margin refresh not observable within the
6h token lifetime — the forced-refresh path is covered by the live suite.

---

### oauth_chat_signin.py

**Status:** PASS

**Description:** Two-agent chat sign-in run end to end from a signed-out store
with XAI_API_KEY unset. Turn one dispatched sign_in_with_supergrok and returned
the approval URL and user code into the conversation; the sign-in was approved
in the browser; turn two dispatched check_supergrok_login and stored the token
encrypted on SQLite at the deployment slot. The Grok agent then answered on that
session, and the string-syntax variant answered again through a model resolved
from the registry rather than constructed directly. The same two-agent shape was
also driven through an AgentOS server over HTTP, where both tool calls and the
approval link appear in the run response.

**Result:** PASS. The two-agent split is required, not stylistic: a single agent
whose model is xAIResponses cannot reach the sign-in tool, because dispatching it
takes an inference call and that call is the one with no credential. Verified
before the reshape - the run returned status error with an empty tool list.

---

### oauth_multi_user.py

**Status:** PASS

**Description:** Per-user sign-in run end to end from an empty store with
XAI_API_KEY unset. The first user signed in and their token was stored under
their own user_id, with the per-user success message rather than the
deployment-wide one; their question then ran on that token. A second user, with
no row of their own and no deployment slot to fall back to, was refused with the
drafted no-token message and no request reached the provider. That user then
signed in, received their own row, and their question ran on their own token.

require_user_token was exercised separately against a seeded deployment slot,
both ways: an unknown user succeeded through the fallback with the flag off, and
with the flag on was refused at request assembly - no bearer on the wire - with
the drafted message. A user with a row of their own still succeeded with the
flag on, and a caller passing no user_id was still served by the deployment
slot, since an unidentified caller has requested no per-user guarantee. The
deployment slot was seeded from an existing row for that check, so the flag was
the only variable between the two outcomes.

**Result:** PASS for token selection and refusal policy. Billing isolation
between two SuperGrok subscriptions is NOT proven and cannot be from this
machine - it needs a second account. What is proven is which token each request
carries, checked at the outgoing Authorization header. Storage note: per-user
tokens require a database, since one token file holds one session; a per-user
sign-in against a database that cannot store tokens keeps the token in memory
for the process and says so.

---
