# Test Log: middleware

> Tests not yet run. Run each file and update this log.

### agent_os_with_custom_middleware.py

**Status:** PENDING

**Description:** This example demonstrates how to add custom middleware to your AgentOS application.

---

### agent_os_with_jwt_middleware.py

**Status:** PENDING

**Description:** This example demonstrates how to use our JWT middleware with AgentOS.

---

### agent_os_with_jwt_middleware_cookies.py

**Status:** PENDING

**Description:** This example demonstrates how to use JWT middleware with cookies instead of Authorization headers.

---

### agent_os_with_service_accounts.py

**Status:** PASS

**Description:** Serves an AgentOS with JWT middleware (authorization enabled) and a sqlite db. An admin JWT mints a service account token for `claude-code` via POST /service-accounts; the plaintext `agno_pat_...` token is returned once with default run+read scopes and a 90-day expiry. The token then runs the agent over POST /agents/assistant-agent/runs.

**Result:** Verified end to end on 2026-07-04: mint returned 201 with principal `sa:claude-code`; the PAT-authenticated run COMPLETED with the model response and the run and session attributed to user `sa:claude-code`; the PAT could not mint further tokens (403); DELETE revoked the account (204) and the revoked token was rejected with a uniform 401 on its next request.

---

### custom_fastapi_app_with_jwt_middleware.py

**Status:** PENDING

**Description:** This example demonstrates how to use our JWT middleware with your custom FastAPI app.

---

### extract_content_middleware.py

**Status:** PENDING

**Description:** Example for AgentOS to show how to extract content from a response and send it to a notification service.

---

### guardrails_demo.py

**Status:** PENDING

**Description:** Example demonstrating how to use guardrails with an Agno Agent.

---
