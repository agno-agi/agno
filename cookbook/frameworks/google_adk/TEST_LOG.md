# Google ADK cookbook test log

**Date:** 2026-10-19

**Environment:** Python 3.12.2; editable Agno from this checkout; google-adk 2.12.0; google-genai 2.30.1; Gemini API key from the local environment (not read or printed). Every script made real model calls with `gemini-3.7-flash`; the API reported `gemini-3.8-flash` as the served model version in run metrics.

The adapter is also covered by `libs/agno/tests/unit/agents/test_google_adk.py`, which drives a real ADK Runner with a scripted ADK agent (no model) through the standalone and AgentOS paths.

### google_adk_basic.py

**Status:** PASS

**Description:** Standalone streaming run of an `LlmAgent` through `print_response()`.

**Result:** One-paragraph answer on quantum computing, status COMPLETED. A separate check of `run(stream=True)` on a 150-word answer produced 8 content events whose text joined exactly to the final content, so the complete event ADK sends after the partial chunks is not emitted twice.

---

### google_adk_tools.py

**Status:** PASS

**Description:** `LlmAgent` with two Python function tools; tool calls shown as tool events while streaming.

**Result:** Both tools called (`get_weather(city=Tokyo)`, `get_population(city=Tokyo)`) and listed in the Tool Calls panel; the answer used both results. `result.tools` named both calls.

---

### google_adk_multi_agent.py

**Status:** PASS

**Description:** A `SequentialAgent` with researcher and writer sub-agents served as one agent; each step's text is part of the run content.

**Result:** The researcher's bullet list and the writer's paragraph both appear in the response, separated by a blank line. google-adk 2.12.0 prints a DeprecationWarning that `SequentialAgent` will be replaced by `Workflow`; the example keeps `SequentialAgent` because `Workflow` cannot yet be an `LlmAgent` sub-agent.

---

### google_adk_session.py

**Status:** PASS

**Description:** Three turns on one session with SQLite run storage; the ADK session keeps the native context, Agno stores the runs.

**Result:** Turn 2 answered "You said Neptune." and turn 3 summarised both turns, so the ADK session carried the conversation. Three runs were stored in `tmp/google_adk_sessions.db`.

---

### google_adk_image.py

**Status:** PASS

**Description:** A bundled sample image (`cookbook/07_knowledge/testing_resources/restaurant_invoice.jpeg`) sent to Gemini as an inline part of the user message.

**Result:** The model described the invoice and read the line items and the total ($41.57) correctly. The first version of the script used a Wikimedia image URL; that failed before reaching Gemini because the Wikimedia CDN answers 403 to the default `python-httpx` user agent that Agno's media download uses, so the example now reads a local file.

---

### google_adk_agentos.py

**Status:** PASS

**Description:** The tools agent behind AgentOS: `/agents`, streaming and non-streaming runs, SQLite session storage.

**Result:** Served with uvicorn on a local port. `GET /agents` listed `adk-assistant` with `metadata.sdk` = `google-adk`. The non-streaming run returned the weather answer with the tool call and result in `messages`, `model` = `gemini-3.7-flash`, `model_provider` = `Google` and token metrics. A second, streaming run on the same session emitted RunStarted, ToolCallStarted, ToolCallCompleted, RunContent and RunCompleted events. The quickstart variant (`cookbook/frameworks/00_quickstart/google_adk_agent.py`) was served the same way and answered one non-streaming request.

---
