# Test Log: rbac/asymmetric

### basic.py

**Status:** PASS

**Description:** Basic RBAC with RS256 asymmetric keys. Uses `generate_rsa_keys()` from `agno.utils.cryptography`, persists keys to `/tmp` for reload consistency.

**Result:** Import and app construction OK. JWT middleware added with RS256 algorithm.

---

### custom_scope_mappings.py

**Status:** PASS

**Description:** Custom scope mappings with RS256. Manually adds JWTMiddleware with custom scopes and `admin_scope="foo:bar"` override.

**Result:** Import and app construction OK. Custom scope mappings applied.

---
