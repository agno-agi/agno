# Test Log — tracing/

### 01_basic_agent_tracing.py

**Status:** PASS

**Description:** Basic agent with SqliteDb and `tracing=True` on AgentOS. Simplest tracing example.

**Result:** Imports OK. AgentOS constructed with tracing enabled.

---

### 02_basic_team_tracing.py

**Status:** PASS

**Description:** Team with tracing enabled at AgentOS level (propagates to all agents). Shows that `tracing=True` on AgentOS auto-enables tracing for members.

**Result:** Imports OK. Team and agent constructed. AgentOS app built successfully.

---

### 03_agent_with_knowledge_tracing.py

**Status:** PASS

**Description:** Agent with Knowledge (PgVector hybrid search) and tracing. Uses PostgresDb for knowledge contents and SqliteDb for sessions.

**Result:** Imports OK. Knowledge, agent, and AgentOS constructed. PgVector and embedder initialized.

---

### 04_agent_with_reasoning_tools_tracing.py

**Status:** PASS

**Description:** Agent using ReasoningTools with tracing to observe reasoning chains. Stream events enabled.

**Result:** Imports OK. Agent with ReasoningTools constructed successfully.

---

### 05_basic_workflow_tracing.py

**Status:** PASS

**Description:** Workflow with linear steps (Research -> Summarize -> Conditional Fact Check -> Write) and tracing enabled. Uses `Condition` evaluator.

**Result:** Imports OK. Workflow with conditional step constructed. AgentOS app built.

---

### 06_tracing_with_multi_db_scenario.py

**Status:** FAIL

**Description:** Multi-agent setup with separate DBs per agent and a dedicated traces DB. Uses `setup_tracing()` with batch processing config.

**Result:** `AttributeError: type object 'Agent' has no attribute '_run'`. The `openinference-instrumentation-agno` package tries to monkey-patch `Agent._run`, but v2.5 moved this to a submodule. Third-party instrumentor needs updating.

---

### 07_tracing_with_multi_db_and_tracing_flag.py

**Status:** PASS

**Description:** Same multi-DB scenario as 06 but uses `tracing=True` flag instead of manual `setup_tracing()`. Avoids the instrumentor issue.

**Result:** Imports OK. AgentOS constructed with tracing flag and dedicated DB.

---

### dbs/basic_agent_with_sqlite.py

**Status:** PASS

**Description:** Tracing with SqliteDb backend.

**Result:** Imports OK. AgentOS constructed.

---

### dbs/basic_agent_with_postgresdb.py

**Status:** PASS

**Description:** Tracing with PostgresDb backend.

**Result:** Imports OK. AgentOS constructed with PG connection.

---

### dbs/basic_agent_with_mongodb.py

**Status:** SKIP

**Description:** Tracing with MongoDb backend. Requires `pymongo` package and running MongoDB instance.

**Result:** ImportError: `pymongo` not installed.

---
