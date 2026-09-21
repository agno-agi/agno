# TEST_LOG

### responses.py

**Status:** PASS

**Description:** Runs an agent through AzureOpenAIResponses against a live Azure AI Foundry resource with a gpt-5.6-luna deployment. Verified sync run, async run, sync streaming, and tool calling, with and without OPENAI_API_VERSION set (default api_version fallback).

**Result:** All modes produce correct responses. Endpoint must be the resource root (no path); the Foundry project-scoped URL rejects api-key auth.

---
