# Test Log - Context Compaction

## Overview

Cookbook examples demonstrating context compaction for long-running conversations.

## Tests

### 01_quickstart.py

**Status:** PASS

**Description:** Basic context compaction demonstration.

**Result:** 8 compactions, 4639 tokens saved across 5 turns. Multi-turn conversation successfully compacted while preserving context continuity.

---

### 02_custom_model.py

**Status:** PASS

**Description:** Using a separate model for compaction summaries.

**Result:** Configuration verified. Agent uses gpt-4.1 for responses, gpt-4.1-mini for compaction summaries.

---

### 03_with_tools.py

**Status:** PASS

**Description:** Context compaction with tool-heavy workflows.

**Result:** 2 compactions, 956 tokens saved. Tool results (WebSearchTools) properly included in compaction.

---

### 04_with_session.py

**Status:** PASS

**Description:** Session persistence with compaction state.

**Result:** 4 compactions, 2483 tokens saved. User preferences (favorite color: blue, role: data scientist) preserved across session.

---

### 05_force_compaction.py

**Status:** PASS

**Description:** Force compaction with low message limit (4 messages).

**Result:** 10+ compactions, 4639+ tokens saved. Compaction triggered reliably after each turn.

---

### 06_preference_survival.py

**Status:** PASS

**Description:** Test that user preferences survive compaction.

**Result:** 4/5 preferences preserved. Name (Marcus), pytest, structlog, type hints all survived compaction.

---

### 07_comprehensive_test.py

**Status:** PENDING

**Description:** Comprehensive test suite for compaction.

---

### 08_streaming_test.py

**Status:** PASS

**Description:** Streaming responses with compaction.

**Result:** 2/2 tests passed. Both sync and async streaming work correctly with compaction. User names preserved in both cases.

---

### 09_multi_model_test.py

**Status:** PASS

**Description:** Multi-model compaction configurations.

**Result:** 4/4 tests passed. All model combinations work:
- OpenAI agent + OpenAI compactor
- OpenAI agent + Claude compactor  
- Claude agent + GPT compactor
- Gemini agent + OpenAI compactor

User context (name, research area) preserved in all cases.

---
