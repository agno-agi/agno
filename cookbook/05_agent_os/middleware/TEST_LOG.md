# Test Log — middleware/

### agent_os_with_custom_middleware.py

**Status:** PASS

**Description:** Custom middleware demo with rate limiting (per-IP, sliding window) and request/response logging. Shows `app.add_middleware()` pattern after `agent_os.get_app()`.

**Result:** Imports OK. Middleware classes defined. AgentOS app constructed with middleware attached.

---

### agent_os_with_jwt_middleware.py

**Status:** PASS

**Description:** JWT middleware via Authorization header. Shows `JWTMiddleware` from `agno.os.middleware` with claim extraction (`user_id_claim`, `session_id_claim`, `dependencies_claims`). Demonstrates `validate=False` for parameter injection without token validation.

**Result:** Imports OK. JWTMiddleware configured and attached to app.

---

### agent_os_with_jwt_middleware_cookies.py

**Status:** PASS

**Description:** JWT middleware via HTTP-only cookies. Uses `TokenSource.COOKIE` for secure cookie-based auth. Includes `/set-auth-cookie` and `/clear-auth-cookie` endpoints. Shows `base_app` pattern with custom FastAPI routes.

**Result:** Imports OK. Cookie-based JWT middleware configured with security settings.

---

### custom_fastapi_app_with_jwt_middleware.py

**Status:** PASS

**Description:** JWT middleware on a custom FastAPI app with a `/auth/login` endpoint. Shows `base_app` pattern where middleware is added to FastAPI before passing to AgentOS. Includes `excluded_route_paths` for unprotected endpoints.

**Result:** Imports OK. Custom FastAPI app with JWT middleware and AgentOS integration.

---

### extract_content_middleware.py

**Status:** PASS

**Description:** Content extraction middleware that captures response bodies from both streaming (SSE) and non-streaming responses for notifications. Demonstrates SSE parsing and body interception.

**Result:** Imports OK. StreamingResponse handling configured. AgentOS app built.

---

### guardrails_demo.py

**Status:** PASS

**Description:** Guardrails on agent and team using `pre_hooks` (v2.5 pattern). Uses `OpenAIModerationGuardrail`, `PromptInjectionGuardrail`, and `PIIDetectionGuardrail` from `agno.guardrails`.

**Result:** Imports OK. All three guardrails loaded. Agent and team constructed with pre_hooks.

---
