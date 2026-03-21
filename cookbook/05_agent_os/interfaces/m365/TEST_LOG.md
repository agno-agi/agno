# M365 Interface Test Log

## Test Results

### basic.py

**Status:** NOT TESTED

**Description:** Basic Microsoft 365 Copilot agent example

**To Test:**
1. Set environment variables:
   ```bash
   export M365_TENANT_ID="your-tenant-id"
   export M365_CLIENT_ID="your-client-id"
   ```

2. Run the example:
   ```bash
   .venvs/demo/bin/python cookbook/05_agent_os/interfaces/m365/basic.py
   ```

3. Test endpoints:
   ```bash
   # Get manifest
   curl http://localhost:7777/m365/manifest

   # Get health
   curl http://localhost:7777/m365/health

   # List agents (requires JWT token)
   curl -H "Authorization: Bearer <token>" http://localhost:7777/m365/agents
   ```

---

### test_manual.py

**Status:** NOT TESTED

**Description:** Manual test suite for M365 interface without requiring authentication

**To Test:**
1. Start the server in a separate terminal:
   ```bash
   .venvs/demo/bin/python cookbook/05_agent_os/interfaces/m365/basic.py
   ```

2. Run the manual test suite:
   ```bash
   .venvs/demo/bin/python cookbook/05_agent_os/interfaces/m365/test_manual.py
   ```

**Tests:**
- Health check endpoint (no auth required)
- Manifest endpoint (no auth required)
- OpenAPI specification structure
- Agent discovery authentication requirement

**Expected Results:**
- All tests should pass
- Health check returns status=healthy
- Manifest contains valid OpenAPI 3.0.1 spec
- Agent discovery correctly requires authentication

---

### Integration Tests (test_m365_integration.py)

**Status:** NOT TESTED

**Description:** Automated integration tests with mock JWT tokens

**Location:** `libs/agno/tests/integration/os/interfaces/test_m365_integration.py`

**To Test:**
1. Start the server in a separate terminal:
   ```bash
   .venvs/demo/bin/python cookbook/05_agent_os/interfaces/m365/basic.py
   ```

2. Run integration tests:
   ```bash
   source .venv/bin/activate
   pytest libs/agno/tests/integration/os/interfaces/test_m365_integration.py -v --tb=short
   ```

**Tests:**
- `test_health_check`: Health check endpoint
- `test_manifest_endpoint`: OpenAPI manifest structure
- `test_manifest_schemas`: Schema definitions with examples
- `test_agent_discovery_requires_auth`: Authentication requirement
- `test_invoke_requires_auth`: Invoke endpoint authentication
- `test_invoke_with_invalid_token`: Invalid token rejection
- `test_invoke_request_validation`: Pydantic model validation
- `test_openapi_spec_generation`: OpenAPI spec generation

**Expected Results:**
- Health check and manifest tests should pass (no auth required)
- Auth-required tests should return 401
- Validation tests should enforce constraints

---
