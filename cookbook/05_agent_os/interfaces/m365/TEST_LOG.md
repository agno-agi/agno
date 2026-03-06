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
