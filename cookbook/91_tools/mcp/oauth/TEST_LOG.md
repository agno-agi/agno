# TEST_LOG

### client.py

**Status:** PARTIAL

**Description:** Agent connecting to an OAuth-protected MCP server using `OAuthConfig`. The cookbook server (`server.py`) is a mock FastMCP instance that validates a static bearer token inside the `get_secret_data` tool — it is not a real OAuth authorization server (no `.well-known/oauth-authorization-server`, no token endpoint, no transport-level 401 challenge).

**Result:** The MCPTools session connected successfully with `OAuthConfig(client_id="demo-client-id", client_secret="demo-client-secret")` attached and the tool list was discovered:

```
Connected. Available tools: ['get_secret_data', 'ping']
```

Verifications:

- `OAuthConfig` is accepted by `MCPTools.__init__` and propagated into the underlying provider construction (see `libs/agno/agno/tools/mcp/oauth.py::create_oauth_provider`).
- `ClientCredentialsOAuthProvider` is instantiated and registered as the MCP transport's auth provider — the MCP session initialized over `streamable-http` without errors.
- The server received `POST /mcp` (initialize), `POST /mcp` (notifications), `GET /mcp`, `POST /mcp` (tools/list), `DELETE /mcp` (session close) and returned 200/202 to all of them.

Where it stopped:

1. The OAuth **token-fetch path was not exercised end-to-end**. The mock server does not return a `401 Unauthorized` with a `WWW-Authenticate: Bearer ...` challenge at the transport layer (it only checks the bearer token inside the `get_secret_data` tool body). The MCP SDK's `ClientCredentialsOAuthProvider` only triggers OIDC discovery + client-credentials token exchange in response to a 401 challenge — none was issued, so no `/.well-known/...` or token-endpoint requests were observed in the server log. This is the limitation the plan anticipated: a real OAuth-protected MCP server (e.g., one wrapped with FastMCP's `OIDCProxy`) is required to exercise the full flow.
2. The agent's LLM call failed because `OPENAI_API_KEY` is not set in this environment:

   ```
   ERROR    Model authentication error from OpenAI API: OPENAI_API_KEY not set.
            Please set the OPENAI_API_KEY environment variable.
   ERROR    Error in Agent run: OPENAI_API_KEY not set. Please set the
            OPENAI_API_KEY environment variable.
   ```

   This is unrelated to OAuth — it blocks the LLM from calling the tool, which is what would have caused the mock server to return its "Unauthorized: invalid token 'demo-access-token'" string (since the static token does not match what a real client_credentials grant against the mock would produce anyway).

Conclusion: the OAuth **wiring** in `MCPTools` is verified — `OAuthConfig` is accepted, the provider is constructed and attached to the MCP transport, and the MCP session establishes cleanly. The **token-exchange** itself was not observed because the cookbook's mock server does not issue 401 challenges and is not a real authorization server. End-to-end verification requires a real OAuth-protected MCP server.

**Environment:**
- demo venv: `.venvs/demo` (created via `./scripts/demo_setup.sh`; `fastmcp` was installed afterwards into the venv as it is not part of `agno[demo]`)
- OPENAI_API_KEY: not set
- Server: `cookbook/91_tools/mcp/oauth/server.py`, run via an inline wrapper on port **18000** because port 8000 was occupied by an unrelated local service on this machine. The cookbook source files were not modified; the wrapper imported `mcp` from `server.py` and called `mcp.run(transport="streamable-http", port=18000)`. The client was invoked with `url="http://localhost:18000/mcp"`.

---
