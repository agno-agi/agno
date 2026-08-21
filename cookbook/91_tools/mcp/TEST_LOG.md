# Test Log

### structured_content.py

**Status:** PASS

**Description:** Connects to the hosted DeepWiki MCP server (public, no auth) and asks
about facebook/react. Verifies the agent answers from the tool's `structuredContent`
and that `structured_content_hook` reads the typed object from
`ToolResult.metadata["structured_content"]`.

**Result:** `ask_question` returned successfully (with `timeout_seconds=60` for DeepWiki's
slower analysis), the hook printed the `structured_content` payload read from metadata, and
the agent produced a grounded one-sentence answer about the repository.

---

### unstructured_transform.py

**Status:** PASS

**Description:** End-to-end run against the hosted Unstructured Transform MCP server (`https://mcp.transform.unstructured.io`) via `mcp-remote`. Sample input: 1-page PDF at `$TMPDIR/sample.pdf` (1923 bytes). Agent orchestrated the full five-step flow autonomously: `request_file_upload_url` -> `upload_file` (local `@tool` PUT via `httpx`) -> `transform_files` with `chunk_by_title` -> polling `check_transform_status` until COMPLETED -> `get_transform_results` with `output_format=json`.

**Result:** COMPLETED. Agent response time 73.9s (dominated by server-side partition + chunk; balance is model tool-call orchestration). Returned 2 elements (`CompositeElement` + `Table`, TATR extraction) totaling 1216 characters. `upload_file` invoked exactly once, on the source PDF, returning `HTTP 200`. Signed download URL for the Element JSON returned for out-of-band GET (agent reported the URL to the user rather than calling `upload_file` on it, per the tool docstring).

### Pending

**Status:** NOT RUN

**Description:** Tests for the other cookbook files in this directory have not been executed yet in this workspace.

**Result:** Add individual run results after executing examples.

---
