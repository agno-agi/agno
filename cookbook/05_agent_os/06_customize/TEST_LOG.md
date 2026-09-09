# Test Log: 06_customize

Tested on 2026-07-24 against Agno source commit
`37496c5ccd3be632cdbb97a9111a4a09999850fb`.

### basic.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Started the combined FastAPI/AgentOS application and queried
its base-app and discovery routes.

**Result:** The server booted, `/health` and `/config` returned HTTP 200, and
the preserved `/customers` route returned Ada and Grace. Config listed
`custom-base-app-agent`.

---

### route_conflicts.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Started the preserved-route policy example and queried both
conflicting base-app routes plus AgentOS discovery.

**Result:** With `preserve_base_app`, custom `/` and `/health` handlers remained
active (`owner=base_app`) while AgentOS `/config` returned HTTP 200 and listed
`route-conflict-agent`.

---

### lifespan.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Entered the custom lifespan, queried the live app, and exited
it to exercise startup, resync, and shutdown.

**Result:** Startup injected the AgentOS instance, appended `startup-agent`,
resynced the app, and `/health` and `/config` returned 200. Config returned
exactly `initial-agent` and `startup-agent`.

---

### custom_middleware.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Sent live health and discovery requests through the logging
and rate-limit middleware stack.

**Result:** `/config` returned HTTP 200 with `X-Request-Count`,
`X-RateLimit-Limit: 10`, and a decremented remaining-request header.
`/health` returned 200 and config listed `custom-middleware-agent`.

---

### response_middleware.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Ran the live JSON and SSE clients through the response-body
ASGI wrapper, then queried health and discovery.

**Result:** The checked-in client completed one JSON run and one ten-event SSE
run. The public ASGI wrapper emitted exactly two notifications and captured
`Non-streaming capture works.` and `Streaming capture works.` respectively.
`/health` and `/config` returned 200; config listed
`response-middleware-agent`.

---

### custom_events.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Ran the model-backed SSE client and inspected the served
agent through the live health and discovery routes.

**Result:** The `gpt-5.5` agent called `get_customer_profile`; the client
observed `CustomEvent` with `Ada Lovelace <ada@example.com>` in the live SSE
stream. `/health` and `/config` returned 200; config listed
`customer-profile-agent`.

---

### dependencies.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Posted a model-backed run with request-scoped dependencies,
then queried the server's health and discovery routes.

**Result:** The HTTP request supplied `{"robot_name": "Anna"}` and the completed
`gpt-5.5` response used the exact dependency value. `/health` and `/config`
returned 200; config listed `dependency-aware-agent`.

---

### cors_and_security_key.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Exercised anonymous and authenticated discovery plus a CORS
preflight, then queried authenticated health and config.

**Result:** Anonymous `/config` returned HTTP 401, the configured Bearer key
returned HTTP 200, and a preflight from `https://console.example.com` returned
that exact `Access-Control-Allow-Origin`. Authenticated `/health` and `/config`
returned 200; config listed `secured-agent`.

---

## Validation

- Recursive pattern validation: exactly 8 Python files checked, 0 violations.
- Every app imported, built OpenAPI, and exposed the expected routes.
- Every credentials-free server booted and returned HTTP 200 for its live
  health/discovery surface (or the expected authenticated equivalent).
- Targeted Ruff format and check passed.
- All eight examples passed live; no construction-smoke substitutions were
  used.
