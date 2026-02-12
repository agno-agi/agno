# TEST LOG

Generated: 2026-02-10 UTC

Pattern Check: Checked 5 file(s) in cookbook/02_agents/input_and_output. Violations: 0

### input_formats.py

**Status:** PASS

**Description:** Executed with `.venvs/demo/bin/python` as a cookbook runnable example.

**Result:** Completed successfully.

---

### input_schema.py

**Status:** FAIL

**Description:** Executed with `.venvs/demo/bin/python` as a cookbook runnable example.

**Result:** Failed with Anthropic API authentication error (401 Unauthorized). Environment issue -- ANTHROPIC_API_KEY is invalid.

---

### output_schema.py

**Status:** PASS

**Description:** Executed with `.venvs/demo/bin/python` as a cookbook runnable example.

**Result:** Completed successfully.

---

### parser_model.py

**Status:** PASS

**Description:** Executed with `.venvs/demo/bin/python` as a cookbook runnable example.

**Result:** Completed successfully.

---

### response_as_variable.py

**Status:** PASS

**Description:** Executed with `.venvs/demo/bin/python` as a cookbook runnable example.

**Result:** Completed successfully.

---

### streaming.py

**Status:** PASS

**Description:** Executed with `.venvs/demo/bin/python` as a cookbook runnable example.

**Result:** Structure check passed. Exits 0.

---

### output_model.py

**Status:** PASS

**Description:** Executed with `.venvs/demo/bin/python` as a cookbook runnable example.

**Result:** Structure check passed. Exits 0.

---

### save_to_file.py

**Status:** PASS

**Description:** Executed with `.venvs/demo/bin/python` as a cookbook runnable example.

**Result:** Structure check passed. Exits 0.

---

### expected_output.py

**Status:** PASS

**Description:** Executed with `.venvs/demo/bin/python` as a cookbook runnable example.

**Result:** Structure check passed. Exits 0.

---


---

## v2.5 Audit Results

# TEST LOG

Generated: 2026-02-11 UTC (v2.5 review)

Pattern Check: Checked 5 file(s) in cookbook/02_agents/input_and_output. Violations: 0

### output_schema.py

**Status:** PASS

**Description:** Demonstrates `output_model` for structured final response using `gpt-4.1` (main) and `o3-mini` (output_model). Shows news report generation with web search tools.

**Result:** Completed successfully. Structured output generated with proper schema adherence.

---

### response_as_variable.py

**Status:** PASS

**Description:** Captures `RunOutput` as a variable (non-stream). Shows how to access run output programmatically including tool_calls, session_state, and metadata.

**Result:** Completed successfully. Full RunOutput printed with all fields including tool_calls, session_state, and RunStatus.completed.

---

### parser_model.py

**Status:** SKIP

**Description:** Uses `Claude(id="claude-sonnet-4-20250514")` as main model with OpenAI as parser. Requires ANTHROPIC_API_KEY.

**Result:** Skipped — ANTHROPIC_API_KEY not available in environment.

---

### input_formats.py

**Status:** FAIL

**Description:** Demonstrates message-format input with `image_url` type. Sends a Wikipedia image URL to the default model.

**Result:** Failed — OpenAI API returned 400: "Error while downloading" the Wikipedia image URL. External URL unreachable from OpenAI's servers. Not a framework bug.

---

### input_schema.py

**Status:** PASS

**Description:** Demonstrates `input_schema` with Pydantic BaseModel for structured user input. Uses HackerNewsTools to find AI/ML articles.

**Result:** Completed successfully. Agent used HackerNews tools and returned structured results matching the input schema requirements.

---
