# Agno vs HUF — Detailed Comparison

> Generated: 2026-03-02
> Purpose: Identify learning opportunities, gaps, and collaboration potential between Agno (open-source Python AI framework) and HUF (Frappe-based AI agent platform)

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [What Each System Is](#2-what-each-system-is)
3. [Side-by-Side Feature Matrix](#3-side-by-side-feature-matrix)
4. [In Agno, Not in HUF — Learning Opportunities](#4-in-agno-not-in-huf--learning-opportunities)
5. [In HUF, Not in Agno — HUF Advantages](#5-in-huf-not-in-agno--huf-advantages)
6. [In Both — Common Ground](#6-in-both--common-ground)
7. [Deep Dives by Category](#7-deep-dives-by-category)
8. [Collaboration & Sharing Opportunities](#8-collaboration--sharing-opportunities)
9. [Recommended Priorities for HUF](#9-recommended-priorities-for-huf)

---

## 1. Executive Summary

| Dimension | Agno | HUF |
|-----------|------|-----|
| **Type** | Python framework / SDK | Frappe application |
| **Target user** | Python developers | Frappe/ERPNext developers & non-coders |
| **Deployment** | Self-hosted FastAPI (AgentOS) | Frappe bench (ERPNext stack) |
| **UI** | Minimal (connects to os.agno.com) | Full Frappe Desk + React frontend |
| **Model providers** | 43+ direct | 100+ via LiteLLM |
| **Tools** | 130+ Python toolkits | CRUD-first + custom functions |
| **Multi-agent** | Teams with 4 modes + Workflows | Basic — no native team concept |
| **RAG/Knowledge** | 18+ VectorDBs, 20+ readers | SQLite FTS5 only |
| **Memory** | MemoryManager + LearningMachine | Conversation history only |
| **MCP** | Client + Server (both directions) | Client only |
| **Evaluation** | Built-in 4-type eval framework | None |
| **Guardrails** | PII, prompt injection, moderation | None |
| **Approvals** | Built-in human-in-the-loop | None |
| **Observability** | Full OTEL + metrics | Basic run logs |
| **Scheduling** | Native scheduler | Via Frappe Scheduler |
| **Learning** | LearningMachine (6 types) | None |
| **Licensing** | Open-source (Mozilla Public License) | Open-source |

**Bottom line:**
- **Agno** is a power-developer framework with enormous breadth (43 model providers, 130 tools, 18 vector DBs). Its strength is composability and coverage at the Python SDK level.
- **HUF** is a no-code/low-code Frappe application tightly integrated with the ERPNext/Frappe ecosystem. Its strength is the native DocType integration, Frappe permissions model, and business workflow context.
- They are **complementary, not competing** — Agno solves the "build an AI system in Python" problem; HUF solves the "give AI agents access to your Frappe business data" problem.

---

## 2. What Each System Is

### Agno

Agno is a **Python framework** (installable via `pip install agno`) for building production AI systems. It provides:
- A library of composable classes (`Agent`, `Team`, `Workflow`)
- Direct integrations with 43+ LLMs, 130+ tools, 18+ vector DBs
- A deployment platform (`AgentOS`) built on FastAPI
- An MCP server so any MCP client (Claude Desktop, etc.) can talk to Agno agents

**Mental model**: Agno is to AI agents what FastAPI is to web APIs — a Python-centric, developer-first toolkit.

### HUF

HUF is a **Frappe application** that adds AI agent capabilities to the Frappe/ERPNext framework. It provides:
- DocType-based configuration (no code for basic agents)
- Native Frappe CRUD tools (read/write/create/delete any DocType)
- Agent triggers on document events (after_insert, on_submit, etc.)
- Scheduled agents via Frappe Scheduler
- Real-time chat via Frappe's socket infrastructure
- Full Frappe permission model for AI actions
- Visual flow builder (React Flow-based, in development)

**Mental model**: HUF is to Frappe what LangChain integrations are to LangChain — it makes the Frappe ecosystem AI-capable via a native, idiomatic integration.

---

## 3. Side-by-Side Feature Matrix

### Core Architecture

| Feature | Agno | HUF |
|---------|------|-----|
| Primary language | Python | Python (Frappe) + TypeScript |
| Configuration style | Code (Python classes) | No-code (Frappe DocTypes) |
| Agent definition | `Agent(model=..., tools=...)` | `Agent` DocType with linked tools |
| Agent runtime | Python process / FastAPI | Frappe worker / background job |
| Async support | Yes (native async/await) | Partial (background jobs via RQ) |
| Sync support | Yes | Yes |
| Session isolation | Per-user, per-session | Per-user via session_id |
| Multi-tenancy | Yes (AgentOS RBAC) | Via Frappe permission model |

### Models & Providers

| Feature | Agno | HUF |
|---------|------|-----|
| Number of providers | 43+ direct implementations | 100+ via LiteLLM |
| Provider configuration | Python code | `AI Provider` DocType |
| API key storage | Environment / config | Frappe encrypted `Password` field |
| Model normalization | Provider-specific modules | Automatic via LiteLLM |
| Local models (Ollama, etc.) | Yes (direct) | Yes (via LiteLLM) |
| Reasoning models (o1, R1) | Yes (dedicated system) | Partial (via LiteLLM) |
| Model switching per agent | Yes | Yes (per-Agent DocType config) |

### Tools & Integrations

| Feature | Agno | HUF |
|---------|------|-----|
| Number of pre-built tools | 130+ | 20+ built-in types |
| Web search | 10+ providers | Via custom HTTP/GET tools |
| Database tools | DuckDB, SQL, Postgres, etc. | Frappe CRUD (native) |
| Cloud platform tools | AWS, GCP, Azure, GitHub | Via HTTP tools only |
| Communication tools | Slack, Discord, Telegram, etc. | None built-in |
| Code execution | E2B, Docker, local shell | None |
| File/document reading | 20+ formats for RAG | OCR via custom tool |
| Image generation | DALL-E, Luma, FAL, Replicate | Via custom function |
| Tool creation | `@tool` decorator | `Agent Tool Function` DocType |
| Tool discovery | App hooks (`huf_tools`) | `huf_tools` hook system |
| MCP tools | Full client + multi-server | Client only |
| Parallel tool execution | `ParallelTools` | None |
| Tool approval/confirmation | Built-in approval system | None |
| Tool hooks | `before_tool_call`, `after_tool_call` | None |

### Multi-Agent & Teams

| Feature | Agno | HUF |
|---------|------|-----|
| Multi-agent concept | `Team` class (first-class) | None (single agent only) |
| Team execution modes | Route, Coordinate, Broadcast, Tasks | N/A |
| Nested teams | Yes (teams of teams) | N/A |
| Agent routing | LLM-based automatic | N/A |
| Parallel agent execution | Yes | N/A |
| Shared team context | Yes (session state) | N/A |
| Agent-to-Agent protocol | A2A over HTTP | `Run Agent` tool type |

### Workflows

| Feature | Agno | HUF |
|---------|------|-----|
| Workflow engine | DAG-based `Workflow` class | Flow Engine (JSON graph) |
| Visual builder | No (code-only) | Yes (React Flow-based) |
| Node types | `Step`, `Parallel`, `Loop`, `Router` | `trigger.*`, `agent.run`, `router.llm`, `human.approval`, `end` |
| Conditional logic | `Condition` class + CEL | Expression-based edges + CEL |
| Parallel steps | `Parallel` class | Planned |
| Loop support | `Loop` class (for/while) | Not yet |
| Human approval gate | `@pause` decorator | `human.approval` node |
| Sub-workflows | Yes | Not yet |
| Persistence | Session-based | `FlowRun` DocType |
| Remote execution | `RemoteWorkflow` | Not yet |
| Agentic mode | No | Yes (orchestrator-in-the-loop) |
| Workflow triggers | Via OS schedules | Doc events, webhooks, manual |

### RAG & Knowledge

| Feature | Agno | HUF |
|---------|------|-----|
| Knowledge system | Comprehensive `Knowledge` class | `Knowledge Source` DocType |
| Vector databases | 18+ backends | SQLite FTS5 only |
| Semantic search | Yes (via vector DB) | No (keyword BM25 only) |
| Hybrid search | Yes | No |
| Document readers | 20+ formats (PDF, DOCX, Excel, PPT, etc.) | Text, PDF (via OCR), URL |
| Cloud storage loaders | S3, GCS, Azure, SharePoint, GitHub | None |
| Chunking strategies | 8 strategies | Fixed-size only |
| Embedder providers | 18+ | None (FTS5 keyword only) |
| Rerankers | Extensible system | None |
| Metadata filtering | `FilterExpr` system | None |
| Agentic RAG | Yes (agent queries knowledge) | Optional mode via tool |
| Mandatory injection | Agent injects chunks into prompt | Yes (`Mandatory` mode) |
| Knowledge rebuild | Yes | Yes |

### Memory

| Feature | Agno | HUF |
|---------|------|-----|
| Conversation history | Yes | Yes |
| Cross-session memory | Yes (`MemoryManager`) | No |
| Semantic memory search | Yes | No |
| Memory optimization | Summarize strategy | None |
| LearningMachine | Yes (6 learning types) | None |
| User profile learning | Yes | No |
| Entity memory | Yes | No |
| Decision logging | Yes | No |
| Preference tracking | Yes | No |

### MCP (Model Context Protocol)

| Feature | Agno | HUF |
|---------|------|-----|
| MCP client | Yes | Yes (`MCPServer` DocType) |
| MCP server (expose agents) | Yes (via AgentOS) | No |
| Transport: stdio | Yes | No (HTTP/SSE only) |
| Transport: SSE | Yes | Yes |
| Transport: Streamable HTTP | Yes | Yes |
| Multiple MCP servers | Yes (`MultiMCPTools`) | Yes (multiple `Agent MCP Server`) |
| Tool namespacing | Yes | Yes |
| Tool filtering | Yes (include/exclude lists) | No |
| Auth types | Header-based | None, API key, Bearer, custom |
| UI for MCP management | No | Yes (React component) |

### Human-in-the-Loop

| Feature | Agno | HUF |
|---------|------|-----|
| Tool approval | Yes (per tool) | None |
| Run approval | Yes | None |
| Workflow checkpoints | Yes (`@pause`) | Yes (`human.approval` node) |
| Approval queue | Yes (via Agent OS API) | None |
| Approval UI | Via os.agno.com | None |
| Conditional approval | Yes | None |

### Guardrails & Safety

| Feature | Agno | HUF |
|---------|------|-----|
| PII detection | Yes | None |
| Prompt injection detection | Yes | None |
| OpenAI moderation | Yes | None |
| Custom guardrails | Yes (base class) | None |
| SSRF protection (HTTP tools) | Partial | Yes (`validate_url`) |

### Hooks & Extensibility

| Feature | Agno | HUF |
|---------|------|-----|
| Before-run hooks | Yes | Via custom trigger logic |
| After-run hooks | Yes | Via tool `function_path` |
| Before-tool hooks | Yes | None |
| After-tool hooks | Yes | None |
| Stream hooks | Yes | None |
| Error hooks | Yes | None |
| App hooks (plugin system) | `agno_tools` | `huf_tools` |

### Evaluation

| Feature | Agno | HUF |
|---------|------|-----|
| Accuracy evaluation | Yes | None |
| Performance evaluation | Yes | None |
| Reliability evaluation | Yes | None |
| Agent-as-judge | Yes | None |
| Built-in eval runner | Yes | None |
| Benchmark integration | Yes | None |

### Observability & Monitoring

| Feature | Agno | HUF |
|---------|------|-----|
| Token usage tracking | Yes (per run, per session) | Yes (per `Agent Run`) |
| Cost tracking | Yes | Yes |
| Execution tracing | Full OTEL | `Agent Run` DocType |
| Tool call logs | Yes | `Agent Tool Call` DocType |
| Latency metrics | Yes | No |
| Langfuse integration | Yes | No |
| Arize Phoenix | Yes | No |
| AgentOps | Yes | No |
| LangSmith | Yes | No |
| Custom OTEL exporters | Yes | No |
| Visual dashboards | os.agno.com | Frappe Desk |

### UI & Frontend

| Feature | Agno | HUF |
|---------|------|-----|
| Built-in web UI | os.agno.com (external) | Frappe Desk + React app |
| Chat interface | Via interfaces | `Agent Chat` DocType |
| Flow builder (visual) | No | Yes (React Flow) |
| Agent management UI | Via os.agno.com | Frappe Desk |
| Knowledge management UI | No | Frappe Desk |
| MCP server UI | No | Yes |
| Console/debugger | No | `Agent Console` singleton |
| Real-time updates | WebSocket | Frappe socket.io |
| Streaming chat | SSE | SSE (`/huf/stream/<agent>`) |

### Deployment & Infrastructure

| Feature | Agno | HUF |
|---------|------|-----|
| Deployment model | FastAPI on any host | Frappe bench (gunicorn) |
| Docker support | Yes (docker-compose) | Yes (docker-compose) |
| Kubernetes ready | Yes (stateless FastAPI) | Via Frappe bench |
| Horizontal scaling | Yes (stateless) | Frappe worker pool |
| Background jobs | Built-in scheduler | Frappe RQ workers |
| Database | PostgreSQL recommended | MariaDB (Frappe native) |
| Caching | Redis optional | Redis (Frappe native) |
| Webhook triggers | Via Agent OS | `Agent Trigger` → Webhook type |
| Scheduled execution | Native scheduler | Frappe Scheduler |

### Document/Business Logic Integration

| Feature | Agno | HUF |
|---------|------|-----|
| DocType CRUD | No | Yes (native, all operations) |
| Document event triggers | No | Yes (after_insert, on_submit, etc.) |
| Permission system | RBAC (own system) | Frappe permission model |
| Business logic access | Via custom tools | Native Python function path |
| ERP/CRM integration | Via API tools | Native (it IS the ERP) |
| Report generation | No | Yes (`Get Report Result` tool) |
| File attachments | Via tools | Yes (`Attach File to Document`) |

---

## 4. In Agno, Not in HUF — Learning Opportunities

These are capabilities Agno has that HUF lacks. These represent the strongest learning and improvement opportunities for HUF.

### 🔴 High Priority — Significant HUF Gaps

#### 4.1 Semantic Knowledge Search (Vector RAG)
**Agno approach**: 18+ vector databases with semantic embedding search, hybrid search, reranking, metadata filtering.

**HUF today**: SQLite FTS5 (keyword-only BM25). No semantic search. No vector embeddings.

**Why it matters**: Keyword search misses semantically related content. "purchase order value" won't find chunks containing "total cost of procurement." For business knowledge bases, semantic search is essential.

**Learning from Agno**:
- Add optional vector DB backend (start with pgvector, already in Frappe's stack)
- Support OpenAI/Cohere/local embeddings
- Hybrid search (BM25 + vector)
- Metadata filtering on `Knowledge Input`

#### 4.2 Multi-Agent Teams
**Agno approach**: `Team` class with route/coordinate/broadcast/tasks modes. LLM-based agent routing. Nested teams.

**HUF today**: Only single agents. The `Run Agent` tool type is the only inter-agent mechanism.

**Why it matters**: Complex tasks benefit enormously from specialization. A "Sales Analysis Team" with a Researcher, Analyst, and Writer will outperform a single agent.

**Learning from Agno**:
- Add `Agent Team` DocType with member agents
- Implement route/coordinate modes
- Team-level shared context
- Team runs linked to `Agent Run` records

#### 4.3 Human-in-the-Loop Approvals
**Agno approach**: Per-tool approval, per-run approval, `@pause` in workflows. REST API for approval queue management.

**HUF today**: No approval mechanism. Agents can execute any tool without confirmation.

**Why it matters**: For business-critical operations (sending emails, creating financial records, deleting data), human approval is a compliance and safety requirement.

**Learning from Agno**:
- Add `Agent Approval` DocType for pending approvals
- Add approval configuration to `Agent Tool Function`
- Frappe notification when approval required
- Approve/reject from Frappe Desk

#### 4.4 Guardrails
**Agno approach**: PII detection, prompt injection, OpenAI moderation. Pluggable base class.

**HUF today**: No guardrail system. SSRF protection exists for HTTP but nothing for content.

**Why it matters**: Business data contains PII. Agents processing customer records must not leak personal data. Prompt injection is a real attack vector.

**Learning from Agno**:
- Add `Agent Guardrail` DocType
- Integrate OpenAI moderation API for content moderation
- Build simple PII scanner (regex-based initially)
- Add guardrail execution before/after agent runs

#### 4.5 Evaluation Framework
**Agno approach**: AccuracyEval, PerformanceEval, ReliabilityEval, AgentAsJudgeEval.

**HUF today**: No evaluation system. No way to test agent quality.

**Why it matters**: Production AI agents need quality baselines. "Is my agent getting better or worse after a change?"

**Learning from Agno**:
- Add `Agent Test Case` DocType (expected output, assertions)
- Add `Agent Eval Run` to track evaluation results
- Start with simple string matching, evolve to LLM-as-judge
- Track eval metrics over time for regression detection

#### 4.6 Cross-Session Persistent Memory
**Agno approach**: `MemoryManager` with semantic search, optimization strategies, cross-session persistence.

**HUF today**: Conversation history only. Memory resets between independent sessions.

**Why it matters**: Agents that remember user preferences across sessions are dramatically more useful. "Remember I prefer formal email tone" should persist.

**Learning from Agno**:
- Add `Agent Memory` DocType (user-scoped facts)
- LLM extracts memorable facts from conversations
- Inject relevant memories into system prompt
- Memory management UI in Frappe Desk

#### 4.7 Execution Hooks
**Agno approach**: `before_run`, `after_run`, `before_tool_call`, `after_tool_call`, `on_stream`, `on_error`.

**HUF today**: No hook system. Only the `Agent Trigger` for doc events.

**Why it matters**: Hooks enable middleware patterns — logging, modification, validation, metrics collection without changing agent code.

**Learning from Agno**:
- Add hook registration via `huf_hooks` app hook
- Implement at least `before_run`/`after_run` initially
- Enable use cases: custom token accounting, audit logs, A/B testing

### 🟡 Medium Priority — Notable Gaps

#### 4.8 Parallel Tool Execution
**Agno**: `ParallelTools` class runs multiple tools concurrently.

**HUF today**: Tools execute sequentially.

**Impact**: When an agent needs to search 5 sources, sequential execution wastes time. Parallel execution makes responses 3-5x faster.

#### 4.9 Streaming Intermediate Steps
**Agno**: `stream_intermediate_steps=True` streams tool call details in real-time.

**HUF today**: SSE streams final response only. Tool calls not visible in real-time.

**Impact**: Users see a black box while tools run. Streaming tool calls builds trust and shows progress.

#### 4.10 Reasoning System
**Agno**: Dedicated reasoning module for o1, Claude extended thinking, DeepSeek R1, etc. Shows step-by-step reasoning.

**HUF today**: Uses reasoning models via LiteLLM but no structured reasoning extraction or display.

**Impact**: Reasoning visibility improves trust and debugging.

#### 4.11 Session Summaries
**Agno**: `SessionSummaryManager` auto-generates summaries when sessions get long.

**HUF today**: Sends full history to model (token-inefficient for long conversations).

**Impact**: Long conversations hit context limits. Summaries keep cost low and context relevant.

#### 4.12 Structured Output (Pydantic)
**Agno**: `output_schema=PydanticModel` returns typed structured data.

**HUF today**: Agent responses are always text. No structured output support.

**Impact**: Enables agents that return structured data (e.g., "Extract invoice fields" returns `{vendor, amount, date}`).

#### 4.13 Context Compression
**Agno**: `CompressionManager` compresses old messages to save tokens.

**HUF today**: No compression. Full message history grows indefinitely.

**Impact**: Reduces token cost significantly for long-running agents.

#### 4.14 Tool-level Hooks (before_tool_call / after_tool_call)
**Agno**: Hooks fire before and after each tool execution.

**HUF today**: None.

**Impact**: Enables per-tool logging, validation, rate limiting, caching.

#### 4.15 LearningMachine
**Agno**: 6 learning types with persistent stores — user profile, entity memory, decision logs.

**HUF today**: None.

**Impact**: Agents that improve over time, learn user preferences, and adapt to entities they frequently interact with.

### 🟢 Lower Priority — Nice to Have

#### 4.16 Async Execution Engine
**Agno**: Full native async/await throughout.
**HUF**: Background job queuing via Frappe RQ. Not true async within a single run.

#### 4.17 Nested Workflow Support
**Agno**: Sub-workflows within workflows.
**HUF**: Not yet implemented.

#### 4.18 Multi-modal (Images/Audio/Video)
**Agno**: First-class `Image`, `Audio`, `Video` classes with unified multi-modal API.
**HUF**: OCR exists as a tool, but no unified multi-modal primitive.

#### 4.19 40+ Direct Model Implementations
**Agno**: Direct implementations, no LiteLLM overhead, provider-specific optimizations.
**HUF**: All via LiteLLM (good coverage, but one abstraction layer away from provider-specific features like extended thinking, etc.)

#### 4.20 Observability Integrations
**Agno**: Langfuse, Arize Phoenix, AgentOps, LangSmith out of the box.
**HUF**: None (only internal run logs).

#### 4.21 Agent-to-Agent (A2A) Protocol
**Agno**: Standardized A2A protocol for distributed agent networks.
**HUF**: `Run Agent` tool type — functional but not standardized.

#### 4.22 Remote Teams/Workflows
**Agno**: `RemoteTeam`, `RemoteWorkflow` — run teams/workflows across network.
**HUF**: Not applicable currently.

---

## 5. In HUF, Not in Agno — HUF Advantages

These are areas where HUF has capabilities Agno lacks or does not focus on.

### 5.1 Native Frappe/ERPNext Integration ★
**HUF**: First-class CRUD operations on any Frappe DocType. Create Sales Orders, update Customers, fetch Invoices — natively, with full Frappe permission enforcement.

**Agno**: Would require custom tools or HTTP API calls to Frappe.

**Why this matters**: For ERPNext users, this is the entire value proposition. HUF turns every DocType into a tool automatically.

### 5.2 Document Event Triggers ★
**HUF**: `Agent Trigger` with DocType + Event (after_insert, on_submit, on_cancel). Agents fire automatically on business events.

**Agno**: No concept of document lifecycle. Would require external webhook setup.

**Example**: "When a sales order is submitted, summarize it and notify the sales manager via email" — this is trivial in HUF.

### 5.3 No-Code Agent Configuration ★
**HUF**: Non-developers can create agents, add tools, configure triggers, all via Frappe Desk forms.

**Agno**: Requires Python code. Developers only.

**Why this matters**: HUF democratizes AI agent creation for business users.

### 5.4 Frappe Permission Model Integration
**HUF**: All tool operations run with the permissions of the triggering user. Frappe's read/write/create/delete permissions apply.

**Agno**: Own RBAC system in AgentOS, separate from any application permissions.

### 5.5 Visual Flow Builder
**HUF**: React Flow-based drag-and-drop flow builder (in development).

**Agno**: No visual builder. Workflows are code-only.

**Why this matters**: Business users can design automation workflows without coding.

### 5.6 Full Frappe Desk UI
**HUF**: Complete CRUD management UI via Frappe Desk for all agent objects (providers, models, agents, conversations, runs, knowledge, triggers).

**Agno**: No built-in CRUD UI. Relies on os.agno.com (hosted) or custom frontend.

### 5.7 Built-in Business Tools
**HUF**:
- `Get Report Result` — Execute any Frappe/ERPNext report
- `Get Value` / `Set Value` — Single field operations
- `Submit Document` / `Cancel Document` — Workflow state transitions
- `Get Amended Document` — Frappe amendment system
- `Attach File to Document` — Native file attachment

These are all Frappe-native concepts that Agno has no equivalent for.

### 5.8 Conversation Persistence via DocTypes
**HUF**: `Agent Conversation`, `Agent Message`, `Agent Run` are all full Frappe documents — searchable, linkable, reportable via Frappe's reporting framework.

**Agno**: Conversation history is stored in database tables, not surfaced as manageable documents.

### 5.9 Agent Run Feedback System
**HUF**: `Agent Run Feedback` DocType — thumbs up/down with comments, linked to provider/model for quality tracking.

**Agno**: No feedback collection mechanism.

### 5.10 LiteLLM as Default Backend
**HUF**: Uses LiteLLM for unified provider access. This means 100+ providers, automatic retry, cost tracking, and provider-specific optimizations — all with one dependency.

**Agno**: Has 43+ direct implementations (more control, provider-specific features) but more maintenance burden.

### 5.11 Agent Console for Quick Testing
**HUF**: `Agent Console` singleton DocType — a simple form to test any agent with a prompt and see the response. No coding needed.

**Agno**: Requires Python code to test agents.

### 5.12 Docker Quick-Try Environment
**HUF**: `docker/` with a complete pre-configured environment. First-time users get a running HUF in minutes.

**Agno**: Docker available for tests but less focused on quick onboarding.

---

## 6. In Both — Common Ground

Both systems share these capabilities, though implementation details differ.

| Feature | Agno Approach | HUF Approach |
|---------|---------------|--------------|
| **Multi-provider LLM** | 43+ direct implementations | LiteLLM (100+) |
| **Conversation history** | `db`-backed session | `Agent Conversation` DocType |
| **Tool system** | Python toolkits + `@tool` | `Agent Tool Function` DocType |
| **Plugin/app hooks** | `agno_tools` hook | `huf_tools` hook |
| **MCP client** | `MCPTools`, `MultiMCPTools` | `MCPServer` + `mcp_client.py` |
| **Scheduled agents** | Native scheduler | Frappe Scheduler |
| **Doc event triggers** | No (Agno) / Yes (HUF) | `AgentTrigger` |
| **Webhook triggers** | Agent OS endpoint | `AgentTrigger` → Webhook |
| **Streaming** | SSE + WebSocket | SSE (`/huf/stream/`) |
| **Knowledge/RAG** | `Knowledge` class | `KnowledgeSource` DocType |
| **Token cost tracking** | Yes | Yes |
| **Docker** | Yes | Yes |
| **Open source** | Yes (MPL-2.0) | Yes |
| **Background jobs** | Native scheduler | Frappe RQ workers |
| **Agent-runs-agent** | A2A / tool-based | `Run Agent` tool type |
| **Session storage** | 13+ backends | Frappe DocTypes (MariaDB) |
| **API endpoints** | FastAPI (AgentOS) | Frappe whitelist + website renderer |

---

## 7. Deep Dives by Category

### 7.1 RAG / Knowledge — The Biggest Gap

**Agno's advantage is enormous here.** The gap:

| Dimension | Agno | HUF |
|-----------|------|-----|
| Search type | Semantic (vector) + BM25 + Hybrid | BM25 only |
| Vector DB backends | 18 | 0 (SQLite FTS5) |
| Embedder providers | 18 | 0 |
| Chunking strategies | 8 | 1 (fixed-size) |
| Cloud loaders | S3, GCS, Azure, SharePoint, GitHub | None |
| Document readers | 20+ (PDF, DOCX, Excel, PPT, etc.) | Text, PDF (via OCR), URL |
| Metadata filtering | `FilterExpr` | None |
| Reranking | Yes | No |
| Agentic RAG | Yes | Optional (tool mode) |

**Recommended path for HUF:**
1. Add optional `pgvector` backend (already available via Frappe's PostgreSQL support)
2. Add OpenAI text-embedding-3-small as default embedder
3. Add hybrid search (BM25 + vector with RRF scoring)
4. Add Excel, DOCX readers for common business documents

### 7.2 Multi-Agent — HUF Has No Native Concept

**Agno**: `Team` is a first-class primitive with 4 execution modes (route, coordinate, broadcast, tasks). Teams of teams. LLM decides agent routing.

**HUF**: No team concept. The only agent-to-agent mechanism is the `Run Agent` tool type, which is synchronous and doesn't share context.

**The gap in practice:**
- Agno: `Team(members=[researcher, analyst, writer])` — done
- HUF: Would need to chain 3 separate agents via `Run Agent` tools, manually managing context

**Recommended path for HUF:**
1. Add `Agent Team` DocType with member agents and execution mode (route/coordinate/broadcast)
2. Add a shared session context passed to all team members
3. Track team runs under a parent `Agent Run` with child runs per member
4. This is high-value because Frappe users deal with multi-step business processes constantly

### 7.3 Tools — Breadth vs. Depth

| Dimension | Agno | HUF |
|-----------|------|-----|
| Pre-built tools | 130+ | ~20 tool types |
| Frappe-native tools | 0 | 17+ operations |
| Web/search tools | 15+ | Via HTTP only |
| Cloud integrations | AWS, GCP, Azure, GitHub | Via HTTP only |
| Code execution | Yes (E2B, Docker, shell) | None |
| Business tools | Shopify, Jira, Linear, Notion | Frappe DocTypes |
| Financial tools | YFinance, OpenBB, etc. | None |
| Communication | Slack, Discord, Telegram, WhatsApp | None |

**Observation**: Agno has breadth; HUF has depth in the Frappe domain. Both approaches make sense for their target users. HUF should focus on making Frappe-native tools excellent rather than replicating Agno's breadth.

### 7.4 Workflows — Different Philosophies

| Dimension | Agno | HUF |
|-----------|------|-----|
| Definition | Python code | JSON graph (DocType) |
| Visual builder | None | Yes (React Flow) |
| Node types | Code primitives | Declarative types |
| Loop support | Yes (`Loop` class) | Not yet |
| Parallel steps | Yes (`Parallel` class) | Not yet |
| Agentic mode | No | Yes |
| Human approval | `@pause` decorator | `human.approval` node |

**Observation**: HUF's visual flow builder is a significant advantage. Agno's `Workflow` is more powerful for developers but inaccessible to non-coders. HUF's agentic mode (orchestrator decides next step) is unique and not present in Agno.

**HUF should:**
- Complete loop and parallel step support
- Complete the visual builder
- The agentic mode is a differentiator — develop it further

### 7.5 MCP — Both Have Client Support

| Feature | Agno | HUF |
|---------|------|-----|
| Client | Yes | Yes |
| Server (expose agents as MCP) | Yes | No |
| Transport: stdio | Yes | No |
| Transport: SSE | Yes | Yes |
| Transport: HTTP | Yes | Yes |
| Multi-server | Yes | Yes |
| Tool filtering | Yes | No |
| UI for management | No | Yes |

**HUF opportunity**: Expose HUF agents as an MCP server. This would allow Claude Desktop, Cursor, and other MCP clients to directly access HUF agents and their Frappe knowledge. This is a high-value feature with low implementation cost (FastMCP makes it easy).

### 7.6 Security & Guardrails

**Agno**: PII detection, prompt injection, OpenAI moderation.
**HUF**: SSRF protection, Frappe permission model.

Both have security features, but in different areas:
- HUF is stronger on **data access security** (Frappe permissions)
- Agno is stronger on **content security** (guardrails)

**HUF opportunity**: Add basic content guardrails. At minimum:
1. Prompt injection detection (prevent users from jailbreaking agents)
2. PII detection for agents handling customer data
3. These could be implemented as `Agent Guardrail` DocTypes linked to agents

---

## 8. Collaboration & Sharing Opportunities

### 8.1 HUF as Agno Tool Provider (High Value)

Create an Agno tool that gives access to Frappe/HUF:

```python
# Potential: huf/agno_integration.py
from agno.tools import tool

@tool
def frappe_get_doc(doctype: str, name: str) -> dict:
    """Get a Frappe document by doctype and name."""
    ...

@tool
def frappe_get_list(doctype: str, filters: dict) -> list:
    """Get a list of Frappe documents with filters."""
    ...

class FrappeTools(Toolkit):
    """Toolkit for interacting with Frappe/ERPNext."""
    ...
```

This would let any Agno agent read/write Frappe data — bringing Agno's 43 model providers and 130 tools to bear on Frappe business data.

### 8.2 HUF as an MCP Server (Easy Win)

Expose all HUF agents as an MCP server using FastMCP (the same library Agno uses):

```python
# In huf/ai/mcp_server.py
from fastmcp import FastMCP

mcp = FastMCP("HUF Agents")

@mcp.tool()
def run_huf_agent(agent_name: str, prompt: str) -> str:
    """Run a HUF agent with a given prompt."""
    from huf.ai.agent_integration import run_agent_sync
    return run_agent_sync(agent_name, prompt)
```

This would make every HUF agent instantly accessible from Claude Desktop, Cursor IDE, and any MCP client — a huge distribution win.

### 8.3 Shared Knowledge Architecture

Agno's knowledge chunking strategies and embedders are production-ready and open-source. HUF could:
1. Import and use Agno's `RecursiveChunker`, `SemanticChunker` directly
2. Use Agno's `OpenAIEmbedder` as the HUF embedding backend
3. This would upgrade HUF's knowledge system from keyword to semantic search quickly

### 8.4 Shared Evaluation Patterns

Agno's `AccuracyEval` pattern could be adapted for HUF as `Agent Test Case` DocTypes. The evaluation logic itself (LLM-as-judge) is provider-agnostic and could be reused.

### 8.5 Agno's LearningMachine in HUF

Agno's `LearningMachine` concept maps well to HUF:
- `UserProfile` → per-Frappe-user preferences
- `EntityMemory` → facts about Frappe DocType records
- `DecisionLog` → track agent decisions on documents

This could be implemented as `Agent Memory` DocTypes in HUF, using Agno's architecture as the design blueprint.

### 8.6 HUF's No-Code Config for Agno

Agno agents require Python code. HUF's DocType-based configuration approach could be contributed to Agno as an optional "configuration layer":

- `agno_config` package that reads agent definitions from YAML/JSON/database
- No-code agent definition format
- This could be a significant contribution to the Agno ecosystem

### 8.7 Cross-Framework Agent Communication

HUF has `Run Agent` tool type (calls another HUF agent). Agno has A2A protocol. A bridge:

```
HUF Agent → [A2A call] → Agno Agent → [uses Agno's 130 tools] → returns result → HUF continues
```

This would give HUF agents access to all Agno's advanced capabilities (parallel search, specialized toolkits) without rebuilding them.

---

## 9. Recommended Priorities for HUF

Based on the comparison, here are the most impactful improvements HUF could make, ordered by value/effort ratio:

### 🔴 High Impact, Reasonable Effort

#### Priority 1: Vector Search for Knowledge Sources
- Add `pgvector` as alternative backend alongside SQLite FTS5
- Add OpenAI embeddings for semantic search
- Result: Dramatically better knowledge retrieval for business documents

#### Priority 2: Expose HUF Agents as MCP Server
- Use FastMCP (already used by Agno)
- Expose each HUF agent as an MCP tool
- Result: Claude Desktop, Cursor, and any MCP client can use HUF agents

#### Priority 3: Human-in-the-Loop Approvals for Tools
- Add approval configuration to `Agent Tool Function`
- Add `Agent Approval` DocType for pending approvals
- Result: Safe deployment of agents that create/modify financial records

#### Priority 4: Cross-Session Memory
- Add `Agent Memory` DocType for user-scoped facts
- LLM extracts memorable facts from conversations
- Inject relevant memories into system prompt
- Result: Agents that learn and remember users across sessions

### 🟡 Medium Impact, Moderate Effort

#### Priority 5: Multi-Agent Teams
- Add `Agent Team` DocType
- Implement route mode (leader routes to best member)
- Result: Specialized agents working together on complex business tasks

#### Priority 6: Content Guardrails
- Add prompt injection detection
- Add `Agent Guardrail` DocType
- Result: Production-safe deployment on public-facing agents

#### Priority 7: Agent Evaluation Framework
- Add `Agent Test Case` DocType
- LLM-as-judge evaluation on expected outputs
- Result: Regression testing when changing agent configurations

#### Priority 8: Streaming Intermediate Steps
- Stream tool call details in SSE
- Show tool name and progress in real-time chat
- Result: Better user experience, no "black box" feeling during long operations

### 🟢 Lower Priority, High Quality-of-Life

#### Priority 9: Structured Output (Pydantic schemas)
- Add `output_schema` to Agent DocType
- Return typed JSON from agents
- Useful for agents used programmatically (not chat)

#### Priority 10: Session Summaries
- Auto-summarize long conversations
- Keep context window manageable
- Reduce token costs for long sessions

#### Priority 11: Context Compression
- Compress old messages rather than dropping them
- Token-efficient long sessions

#### Priority 12: Agent Hooks (before_run / after_run)
- Allow apps to register hooks via `huf_hooks`
- Enables middleware patterns without modifying agent code

---

## Appendix: Technical Architecture Comparison

### Message Flow

**Agno:**
```
Client → FastAPI (AgentOS) → Agent._run() → Model API
                                         ↓
                          Tool execution ← Tool call response
                                         ↓
                          Memory update → Return to client
```

**HUF:**
```
Client → Frappe API (whitelist) → run_agent_sync() → LiteLLM → Model API
                                                    ↓
                               Tool execution ← Tool call response
                                                    ↓
                               ConversationManager → Agent Run → Return
```

### Storage Model

**Agno:**
- Sessions → Any of 13 databases
- Memories → Separate database table
- Vector knowledge → Any of 18 vector DBs
- All isolated per (user_id, session_id)

**HUF:**
- Sessions → `Agent Conversation` + `Agent Message` DocTypes (MariaDB)
- Memories → `Agent Conversation` only (no cross-session)
- Knowledge → SQLite FTS5 artifacts
- All linked via Frappe document model

### Extensibility Model

**Agno:**
```python
# Register custom tool
@tool
def my_tool(param: str) -> str: ...

agent = Agent(tools=[my_tool])

# Or as toolkit
class MyToolkit(Toolkit):
    def method(self): ...
```

**HUF:**
```python
# Register via hooks.py
huf_tools = ["my_app.tools.my_tool_definition"]

# Or via DocType form
# Agent Tool Function DocType → Custom Function type → function_path
```

Both are extensible; Agno is code-first, HUF is config-first.

---

*This document was generated by analyzing the Agno repository source code and comparing it against the HUF architecture documentation in AGENTS.md and CLAUDE.md.*
