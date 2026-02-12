# Test Log: modes

> Updated: 2026-02-11

## coordinate/

### 01_basic.py

**Status:** PASS

**Description:** Basic coordinate mode — Researcher + Writer team. Leader analyzes request, selects members, crafts tasks, synthesizes responses.

**Result:** Ran successfully. Team delegated to Researcher for facts on LLM training, then Writer to polish. Final response covered pre-training, fine-tuning, and RLHF clearly.

---

### 02_with_tools.py

**Status:** FAIL

**Description:** Coordinate mode with DuckDuckGo and HackerNews tools. Team delegates to tool-equipped members based on question type.

**Result:** DuckDuckGo SSL error: `CERTIFICATE_VERIFY_FAILED: self-signed certificate in certificate chain`. Network/proxy issue, not a code defect. HackerNews tools likely work independently.

---

### 03_structured_output.py

**Status:** PASS

**Description:** Coordinate mode with `output_schema=CompanyBrief` (Pydantic model). Market Analyst + Risk Analyst → structured JSON output.

**Result:** Ran successfully. Tesla analysis returned well-structured CompanyBrief with company_name, industry, strengths (5 items), risks (6 items), and outlook. Pydantic validation passed.

---

## route/

### 01_basic.py

**Status:** PASS

**Description:** Language-based routing — routes English/Spanish/French queries to matching language agent. Demonstrates `mode=TeamMode.route`.

**Result:** All three queries routed correctly. English → English Agent ("Paris"), Spanish → Spanish Agent ("Paris"), French → French Agent ("Paris").

---

### 02_specialist_router.py

**Status:** PASS

**Description:** Domain specialist routing — Math/Code/Science specialists. Routes merge sort question to appropriate expert.

**Result:** Question routed to Math Specialist who provided detailed O(n log n) analysis with Master Theorem proof.

---

### 03_with_fallback.py

**Status:** PASS

**Description:** Route mode with fallback — SQL/Python specialists + General Assistant. Routes unknown topics to fallback agent.

**Result:** SQL question routed correctly to SQL Expert. General question ("code review practices") routed to General Assistant as fallback. Both responses were appropriate.

---

## broadcast/

### 01_basic.py

**Status:** PASS

**Description:** Basic broadcast — Optimist/Pessimist/Realist all receive same query, leader synthesizes perspectives on B2C→B2B pivot.

**Result:** All three agents responded with distinct perspectives. Leader synthesized balanced summary.

---

### 02_debate.py

**Status:** PASS

**Description:** Structured debate — Proponent vs Opponent on remote work. Leader acts as moderator synthesizing arguments.

**Result:** Both debaters provided structured arguments. Moderator summarized key points, areas of agreement, and assessment.

---

### 03_research_sweep.py

**Status:** FAIL

**Description:** Parallel research sweep with DuckDuckGo + HackerNews tools + Trend Analyst.

**Result:** Same DuckDuckGo SSL error as coordinate/02_with_tools.py. Network/proxy issue, not a code defect.

---

## tasks/

### 01_basic.py

**Status:** PASS

**Description:** Basic tasks mode — Planner → Writer → Editor pipeline. Leader decomposes goal into sequential tasks.

**Result:** Content pipeline executed correctly: outline created, draft written, then polished. Final blog post on microservices vs monolith produced.

---

### 02_parallel.py

**Status:** PASS

**Description:** Parallel task execution — Frontend/Backend/DevOps reviewers run concurrently on architecture review.

**Result:** All three reviews completed. Leader synthesized unified architecture assessment of SaaS app.

---

### 03_dependencies.py

**Status:** PASS

**Description:** Task dependency chains — Data Collection → Analysis → Report Writing. Dependencies enforce execution order.

**Result:** Pipeline executed in order. Final executive report on renewable energy market produced with proper dependency resolution.

---
