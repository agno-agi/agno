# Test Log: rbac/symmetric

### basic.py

**Status:** PASS

**Description:** Basic RBAC with HS256 JWT and `AuthorizationConfig`. Creates AgentOS with `authorization=True`, generates test tokens with different scopes.

**Result:** Import and app construction OK. JWT middleware added with HS256 algorithm.

---

### advanced_scopes.py

**Status:** PASS

**Description:** Advanced scope hierarchy with wildcards, per-resource scopes, and audience verification. Uses `AuthorizationConfig` with `verify_audience=True`.

**Result:** Import and app construction OK. JWT middleware added with HS256 algorithm.

---

### agent_permissions.py

**Status:** PASS

**Description:** Per-agent permission scopes. Agents have individual `permission_scopes` lists, MCPTools with streamable-http transport.

**Result:** Import and app construction OK. JWT middleware added with HS256 algorithm.

---

### with_cookie.py

**Status:** PASS

**Description:** Cookie-based JWT RBAC. Creates a custom FastAPI app, adds JWTMiddleware with `token_source=TokenSource.BOTH`, passes `base_app=` to AgentOS.

**Result:** Import and app construction OK. Custom FastAPI app with JWT middleware.

---

### custom_scope_mappings.py

**Status:** PASS

**Description:** Custom scope mappings via JWTMiddleware. Manually adds middleware to AgentOS app with custom `scope_mappings` dict and `admin_scope` override.

**Result:** Import and app construction OK. Custom scope mappings applied.

---
