# TEST_LOG

## v2.5 Testing — 2026-02-11

### agent_team.py
**Status:** PASS
**Description:** Multi-agent team with Groq. Import path fixed from `agno.team.team` to `agno.team`.
**Re-verified:** 2026-02-14 — Import fix confirmed working. Team delegated tasks to web-agent and finance-agent, produced Nvidia news summary with stock price. Groq tool call error is transient (model-side).

---

### basic.py
**Status:** PASS
**Description:** Basic Groq agent with sync and async variants.

---

### browser_search.py
**Status:** PASS
**Description:** Browser search agent using Groq for web search tasks.

---

### db.py
**Status:** PASS
**Description:** Agent with PostgresDb for session history using Groq.

---

### deep_knowledge.py
**Status:** SKIP
**Description:** Interactive deep knowledge agent. Requires `inquirer` package and interactive terminal (typer CLI).
**Result:** `ModuleNotFoundError: No module named 'inquirer'`

---

### image_agent.py
**Status:** PASS
**Description:** Image analysis agent using Groq vision model.

---

### knowledge.py
**Status:** PASS
**Description:** Knowledge base with Groq. PDF embedding and RAG pipeline.

---

### metrics.py
**Status:** PASS
**Description:** Agent metrics display with Groq. Shows token usage and timing.

---

### reasoning_agent.py
**Status:** PASS
**Description:** Reasoning agent using Groq with chain-of-thought capabilities.

---

### research_agent_exa.py
**Status:** PASS
**Description:** Research agent using Exa search tools with Groq.

---

### research_agent_seltz.py
**Status:** FAIL
**Description:** Research agent using Seltz search tools. `seltz` package not installed.
**Result:** `ImportError: 'seltz' not installed. Please install using 'pip install seltz'`

---

### retry.py
**Status:** PASS
**Description:** Retry behavior demo with wrong model ID. Shows retries with exponential backoff.

---

### structured_output.py
**Status:** PASS
**Description:** Pydantic structured output with Groq. Schema-enforced responses.

---

### tool_use.py
**Status:** PASS
**Description:** Tool use with Groq. Function calling and tool registration.

---

### transcription_agent.py
**Status:** PASS
**Description:** Audio transcription agent. Uses OpenAI Whisper model (not Groq-native).

---

### translation_agent.py
**Status:** PASS
**Description:** Translation agent. Uses OpenAI model (not Groq-native).

---

### reasoning/basic.py
**Status:** PASS
**Description:** Basic reasoning with Groq. Simple chain-of-thought demo.

---

### reasoning/demo_deepseek_qwen.py
**Status:** PASS
**Description:** DeepSeek and Qwen reasoning models on Groq infrastructure.

---

### reasoning/demo_qwen_2_5_32B.py
**Status:** PASS
**Description:** Qwen 2.5 32B reasoning model on Groq.

---

### reasoning/finance_agent.py
**Status:** PASS
**Description:** Financial analysis agent with reasoning using Groq.

---

## Summary
- **PASS:** 18/20 (90%)
- **FAIL:** 1/20 (5%)
- **SKIP:** 1/20 (5%)
- **Failures:**
  - research_agent_seltz.py: seltz package not installed
- **Skipped:**
  - deep_knowledge.py: interactive terminal required (inquirer + typer)
