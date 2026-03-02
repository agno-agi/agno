# Agno Framework — Comprehensive Overview

> Generated: 2026-03-02
> Based on source analysis of the `agno` repository at `libs/agno/agno/`

---

## Table of Contents

1. [What Is Agno?](#1-what-is-agno)
2. [Core Architecture](#2-core-architecture)
3. [Agent — The Core Primitive](#3-agent--the-core-primitive)
4. [Teams — Multi-Agent Coordination](#4-teams--multi-agent-coordination)
5. [Workflows — Orchestration Engine](#5-workflows--orchestration-engine)
6. [Tools — 130+ Integrations](#6-tools--130-integrations)
7. [Model Providers — 43+](#7-model-providers--43)
8. [Knowledge & RAG System](#8-knowledge--rag-system)
9. [Vector Databases — 18+ Backends](#9-vector-databases--18-backends)
10. [Storage & Databases — 13+ Backends](#10-storage--databases--13-backends)
11. [Memory & Learning System](#11-memory--learning-system)
12. [MCP (Model Context Protocol)](#12-mcp-model-context-protocol)
13. [Agent OS — The Deployment Platform](#13-agent-os--the-deployment-platform)
14. [Reasoning System](#14-reasoning-system)
15. [Evaluation Framework](#15-evaluation-framework)
16. [Guardrails & Safety](#16-guardrails--safety)
17. [Human-in-the-Loop & Approvals](#17-human-in-the-loop--approvals)
18. [Hooks System](#18-hooks-system)
19. [Streaming & Real-time](#19-streaming--real-time)
20. [Multi-modal Support](#20-multi-modal-support)
21. [Observability & Tracing](#21-observability--tracing)
22. [Session Management](#22-session-management)
23. [Scheduling](#23-scheduling)
24. [Skills System](#24-skills-system)
25. [Agent-to-Agent (A2A) Protocol](#25-agent-to-agent-a2a-protocol)
26. [Developer Experience](#26-developer-experience)
27. [Cookbook — 100+ Examples](#27-cookbook--100-examples)

---

## 1. What Is Agno?

**Agno** is a full-stack, open-source Python framework for building, deploying, and managing agentic software at scale. It is designed as a "model-agnostic" framework, meaning the same agent code works with any of the 43+ supported LLM providers.

**Core philosophy:**
- **Primitives over platforms**: Agents, Teams, and Workflows are composable Python classes, not black-box services.
- **Model-agnostic**: Swap models by changing one line of code.
- **Production-first**: Built-in session isolation, stateless execution, async support, and horizontal scalability.
- **Streaming-first**: Native SSE/WebSocket streaming throughout the stack.
- **Observability-first**: Every run is traced, metered, and loggable from day one.

**Three execution primitives:**
| Primitive | When to Use |
|-----------|------------|
| `Agent` | Single autonomous entity with tools, memory, knowledge |
| `Team` | Multiple agents coordinating on a shared goal |
| `Workflow` | Deterministic, graph-based multi-step orchestration |

**Repository layout:**
```
libs/agno/agno/          # Core framework (~32 modules)
cookbook/                # 100+ usage examples by topic
scripts/                 # Dev/build/test scripts
```

---

## 2. Core Architecture

Agno's architecture has three layers:

```
┌─────────────────────────────────────────────────────────┐
│                   Agent OS (FastAPI)                    │  ← Management plane
│  REST APIs │ WebSockets │ Auth │ MCP Server │ Tracing   │
├─────────────────────────────────────────────────────────┤
│           Agents │ Teams │ Workflows                    │  ← Execution layer
│  Tools │ Knowledge │ Memory │ Reasoning │ Guardrails    │
├─────────────────────────────────────────────────────────┤
│  Models (43+) │ VectorDBs (18+) │ Databases (13+)       │  ← Infrastructure layer
└─────────────────────────────────────────────────────────┘
```

**Key design decisions:**
- All public methods have both **sync and async** variants
- Agents are **not created in loops** — they are instantiated once and reused
- Full **dependency injection** for testing and composition
- **Pydantic** throughout for type safety
- **OpenTelemetry** for tracing and metrics

---

## 3. Agent — The Core Primitive

**File:** `libs/agno/agno/agent/agent.py` (1,679 lines)
**Execution engine:** `agent/_run.py` (258KB)

The `Agent` class is the primary building block. A minimal agent:

```python
from agno.agent import Agent
from agno.models.openai import OpenAIChat

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    instructions="You are a helpful assistant.",
)
agent.print_response("What is the capital of France?")
```

### Agent Configuration Parameters

| Parameter | Description |
|-----------|-------------|
| `model` | LLM model instance (43+ providers) |
| `tools` | List of tool instances/toolkits |
| `knowledge` | RAG knowledge base |
| `memory` | Memory manager for persistent memory |
| `db` | Storage backend for sessions/history |
| `instructions` | System prompt (string or callable) |
| `output_schema` | Pydantic model for structured output |
| `reasoning` | Enable step-by-step reasoning |
| `guardrails` | List of guardrail instances |
| `hooks` | Pre/post execution hooks |
| `approval` | Approval workflow configuration |
| `evals` | Evaluation framework configuration |
| `session_id` | Session identifier for persistence |
| `user_id` | User identifier for isolation |
| `show_tool_calls` | Show tool call details in output |
| `markdown` | Format output as markdown |
| `stream` | Enable streaming responses |
| `stream_intermediate_steps` | Stream tool call results |
| `max_retries` | Maximum retry attempts |

### Agent Execution Flow

```
User prompt → Message preparation → Context injection (knowledge/memory)
    → Model call → Tool execution loop → Response generation
    → Memory update → Session storage → Return
```

### Key Agent Capabilities

**Structured output** — Return typed Pydantic models:
```python
class MovieResult(BaseModel):
    title: str
    year: int
    rating: float

agent = Agent(model=..., output_schema=MovieResult)
result = agent.run("Best sci-fi movie of 2024?")
# result.content is a MovieResult instance
```

**Agentic updates** — Agent can update its own context:
- `agentic_memory_update=True` — Agent updates its own memory
- `agentic_knowledge_filter=True` — Agent filters its own knowledge
- `agentic_reasoning=True` — Agent uses reasoning model internally

**Session persistence:**
```python
agent = Agent(
    db=PostgresDb(table_name="agent_sessions", db_url="..."),
    session_id="user-123-chat",
    add_history_to_messages=True,
    num_history_runs=10,
)
```

**Streaming:**
```python
for chunk in agent.run("Tell me a story", stream=True):
    print(chunk.content, end="", flush=True)
```

---

## 4. Teams — Multi-Agent Coordination

**File:** `libs/agno/agno/team/team.py` (1,751 lines)
**Execution engine:** `team/_run.py` (258KB)

Teams coordinate multiple agents to solve complex tasks. A team has a leader model that routes tasks to member agents.

### Team Modes

| Mode | Description |
|------|-------------|
| `route` | Team leader routes each message to the most relevant member |
| `coordinate` | Team leader breaks down task and coordinates members |
| `broadcast` | All members receive and respond to each message |
| `tasks` | Team leader assigns structured tasks to members |

### Team Example

```python
from agno.team import Team

team = Team(
    name="Research Team",
    mode="coordinate",
    model=OpenAIChat(id="gpt-4o"),
    members=[
        Agent(name="Web Researcher", tools=[WebSearch()]),
        Agent(name="Data Analyst", tools=[PythonTools()]),
        Agent(name="Writer", instructions="Synthesize research into clear reports"),
    ],
    instructions="Coordinate members to produce high-quality research reports.",
)
```

### Nested Teams

Teams can include other teams as members, enabling hierarchical agent organizations:

```python
research_team = Team(members=[researcher, analyst])
writing_team = Team(members=[writer, editor])
master_team = Team(members=[research_team, writing_team])
```

### Team Features

- **Shared context**: Members share session state and team history
- **Dynamic routing**: LLM-based decision on which agent handles each subtask
- **Parallel execution**: Multiple members can work concurrently
- **Tool sharing**: Teams can define tools accessible to all members
- **Knowledge sharing**: Team-level knowledge base shared with all members
- **Memory manager**: Team-level persistent memory
- **Session summaries**: Automatic summarization of team conversations
- **Delegate to all**: Broadcast tasks to all members simultaneously
- **Remote teams**: Run teams across network boundaries

---

## 5. Workflows — Orchestration Engine

**File:** `libs/agno/agno/workflow/workflow.py` (7,518 lines)

Workflows provide deterministic, graph-based orchestration for complex multi-step processes where you need predictable execution paths rather than autonomous agent decisions.

### Workflow Primitives

| Component | Description |
|-----------|-------------|
| `Step` | Single execution unit (agent call, tool call, or custom logic) |
| `Steps` | Sequential execution of multiple steps |
| `Parallel` | Concurrent execution of multiple steps |
| `Loop` | Iterative execution (for/while loops) |
| `Router` | Conditional branching (switch/case) |
| `Condition` | Boolean decision logic (54KB implementation) |
| `CEL` | Common Expression Language for conditions |
| `@pause` | Decorator to create human checkpoint |

### Workflow Example

```python
from agno.workflow import Workflow, Steps, Parallel, Loop

class ContentPipeline(Workflow):
    researcher = Agent(name="Researcher", tools=[WebSearch()])
    writer = Agent(name="Writer")
    editor = Agent(name="Editor")

    def run(self, topic: str):
        # Parallel research
        research = yield Parallel(
            self.researcher.run(f"Research {topic} from tech sources"),
            self.researcher.run(f"Research {topic} from academic sources"),
        )
        # Sequential: write then edit
        draft = yield self.writer.run(f"Write about {topic} using: {research}")
        final = yield self.editor.run(f"Edit this draft: {draft}")
        return final
```

### Workflow Features

- **DAG execution**: Complex dependency graphs
- **State persistence**: Resume interrupted workflows
- **Error recovery**: Step-level retry and fallback
- **Timeout handling**: Per-step and per-workflow timeouts
- **CEL expressions**: Powerful conditional logic via Common Expression Language
- **Human checkpoints**: `@pause` decorator for human approval gates
- **Sub-workflows**: Nest workflows within workflows
- **Remote execution**: Execute workflows across network
- **WebSocket support**: Real-time status updates for long-running workflows

---

## 6. Tools — 130+ Integrations

**Directory:** `libs/agno/agno/tools/`

Agno provides 130+ pre-built tool integrations, organized into functional categories. Any Python function can be a tool via the `@tool` decorator.

### Web & Search
| Tool | Description |
|------|-------------|
| `WebSearchTools` | Generic web search |
| `TavilyTools` | Tavily AI search API |
| `ExaTools` | Exa semantic search |
| `SerperApiTools` | Google search via Serper |
| `SerpApiTools` | Google search via SerpAPI |
| `BraveSearchTools` | Brave Search API |
| `DuckDuckGoTools` | DuckDuckGo search |
| `SearxngTools` | Self-hosted Searxng |
| `JinaTools` | Jina AI reader/search |
| `BaiduSearchTools` | Baidu search |

### Web Scraping & Content Extraction
| Tool | Description |
|------|-------------|
| `WebsiteTools` | Fetch and parse websites |
| `FirecrawlTools` | Firecrawl scraping API |
| `Crawl4aiTools` | Crawl4AI async scraper |
| `BrowserbaseTools` | Headless browser via Browserbase |
| `BrightdataTools` | Brightdata proxy scraper |
| `OxylabsTools` | Oxylabs scraper |
| `SpiderTools` | Spider.cloud |
| `Newspaper4kTools` | Article extraction |
| `TrafilaturaTools` | Content extraction |
| `ScrapegraphTools` | ScapeGraph AI |
| `AgentQLTools` | AgentQL browser automation |

### Data Sources & Knowledge
| Tool | Description |
|------|-------------|
| `ArxivTools` | ArXiv paper search |
| `PubMedTools` | PubMed medical papers |
| `HackerNewsTools` | HackerNews articles/comments |
| `RedditTools` | Reddit posts/comments |
| `WikipediaTools` | Wikipedia search |
| `YoutubeTools` | YouTube video data/transcripts |
| `OpenWeatherTools` | Weather data |

### Financial & Business
| Tool | Description |
|------|-------------|
| `YFinanceTools` | Yahoo Finance (stocks, crypto, news) |
| `FinancialDatasetsTools` | Financial datasets API |
| `OpenBBTools` | OpenBB financial platform |
| `ShopifyTools` | Shopify store operations (80+ methods) |

### Database & SQL
| Tool | Description |
|------|-------------|
| `SqlTools` | Generic SQL execution |
| `PostgresTools` | PostgreSQL operations |
| `DuckDbTools` | DuckDB analytics |
| `Neo4jTools` | Neo4j graph database |
| `GoogleBigQueryTools` | Google BigQuery |
| `RedshiftTools` | AWS Redshift |
| `PandasTools` | DataFrame operations |
| `CsvTools` | CSV file manipulation |

### Cloud Platforms
| Tool | Description |
|------|-------------|
| `AwsLambdaTools` | AWS Lambda invocation |
| `AwsSesTools` | AWS SES email sending |
| `GoogleDriveTools` | Google Drive file operations |
| `GoogleSheetsTools` | Google Sheets read/write |
| `GoogleCalendarTools` | Google Calendar management |
| `GoogleMapsTools` | Google Maps/geocoding |
| `GmailTools` | Gmail read/send |
| `AzureBlobTools` | Azure Blob Storage |
| `GithubTools` | GitHub API (70KB — repos, PRs, issues, code) |
| `BitbucketTools` | Bitbucket API |

### Communication & Productivity
| Tool | Description |
|------|-------------|
| `SlackTools` | Slack messages/channels |
| `DiscordTools` | Discord bot operations |
| `TelegramTools` | Telegram messaging |
| `WhatsAppTools` | WhatsApp messaging |
| `EmailTools` | SMTP email |
| `ResendTools` | Resend email API |
| `TwilioTools` | SMS/voice via Twilio |

### Project Management & Collaboration
| Tool | Description |
|------|-------------|
| `JiraTools` | Jira issue tracking |
| `LinearTools` | Linear project management |
| `ClickUpTools` | ClickUp tasks |
| `TodoistTools` | Todoist task management |
| `TrelloTools` | Trello boards |
| `NotionTools` | Notion pages/databases |
| `ConfluenceTools` | Confluence wiki |
| `ZendeskTools` | Zendesk support |
| `CalComTools` | Cal.com scheduling |
| `WebexTools` | Webex meetings |
| `ZoomTools` | Zoom meetings |

### AI/Media Generation
| Tool | Description |
|------|-------------|
| `DalleTools` | DALL-E image generation |
| `LumaLabTools` | Luma AI video generation |
| `FalTools` | FAL.ai media models |
| `ReplicateTools` | Replicate model API |
| `ElevenLabsTools` | ElevenLabs text-to-speech |
| `CartesiaTools` | Cartesia TTS |
| `MlxTranscribeTools` | Audio transcription |
| `MoviePyTools` | Video editing |
| `OpenCVTools` | Computer vision |
| `UnsplashTools` | Stock photos |
| `GiphyTools` | GIF search |
| `SpotifyTools` | Spotify music |

### Code Execution & Development
| Tool | Description |
|------|-------------|
| `CodingTools` | Python code execution (28KB) |
| `E2BTools` | E2B cloud code sandbox |
| `DaytonaTools` | Daytona dev environment |
| `DockerTools` | Docker container management |
| `ShellTools` | Local shell command execution |
| `AirflowTools` | Apache Airflow DAG management |
| `ApifyTools` | Apify scraping platform |

### Social & Content
| Tool | Description |
|------|-------------|
| `XTools` | Twitter/X API |
| `LinkedInTools` | LinkedIn API |
| `BrandfetchTools` | Brand logo/colors |

### Special Purpose
| Tool | Description |
|------|-------------|
| `MCPTools` | Model Context Protocol client |
| `MultiMCPTools` | Multiple MCP servers |
| `MCPToolbox` | MCP Toolbox for Databases |
| `ParallelTools` | Parallel tool execution |
| `UserControlFlowTools` | Human interaction in agent loops |
| `UserFeedbackTools` | Collect user feedback |
| `ReasoningTools` | Built-in reasoning tools |
| `KnowledgeTools` | Agentic RAG query tools |
| `Mem0Tools` | Mem0 memory service |
| `ZepTools` | Zep memory service |
| `StreamlitComponents` | Streamlit UI components |

### Custom Tools

Any Python function becomes a tool:

```python
from agno.tools import tool

@tool
def get_stock_price(ticker: str) -> str:
    """Get the current stock price for a given ticker symbol."""
    # Implementation
    return f"Price of {ticker}: $150.00"

agent = Agent(tools=[get_stock_price])
```

---

## 7. Model Providers — 43+

**Directory:** `libs/agno/agno/models/`

Agno supports 43+ LLM providers with a unified interface.

### Major Providers

| Provider | Module | Models |
|----------|--------|--------|
| **OpenAI** | `models.openai` | GPT-4o, o1, o3, GPT-3.5 |
| **Anthropic** | `models.anthropic` | Claude 3.5, Claude 3 Opus/Sonnet/Haiku |
| **Google** | `models.google` | Gemini 1.5/2.0 Pro/Flash |
| **Google Vertex AI** | `models.vertexai` | Gemini via GCP |
| **AWS Bedrock** | `models.aws` | Claude, Llama, Titan via AWS |
| **Azure OpenAI** | `models.azure` | GPT-4 via Azure |
| **Azure AI Foundry** | `models.azure` | Azure AI Studio models |
| **Mistral** | `models.mistral` | Mistral Large/Medium/Small |
| **Groq** | `models.groq` | LLaMA, Mixtral (fast inference) |
| **Cohere** | `models.cohere` | Command R+ |
| **xAI (Grok)** | `models.xai` | Grok-1, Grok-2 |
| **DeepSeek** | `models.deepseek` | DeepSeek V2/V3, R1 |
| **Perplexity** | `models.perplexity` | Sonar models |
| **Cerebras** | `models.cerebras` | Llama via Cerebras |
| **Together AI** | `models.together` | Open-source models |
| **Fireworks** | `models.fireworks` | Fast inference |
| **Meta** | `models.meta` | LLaMA models |
| **NVIDIA** | `models.nvidia` | NVIDIA API |
| **IBM** | `models.ibm` | IBM WatsonX |

### Local/Self-Hosted
| Provider | Module | Notes |
|----------|--------|-------|
| **Ollama** | `models.ollama` | Local model runner |
| **LLaMA.cpp** | `models.llama_cpp` | Local inference |
| **LM Studio** | `models.lmstudio` | Local GUI-based |
| **vLLM** | `models.vllm` | High-throughput local |
| **HuggingFace** | `models.huggingface` | HF model hosting |

### Aggregators/Routers
| Provider | Module | Notes |
|----------|--------|-------|
| **OpenRouter** | `models.openrouter` | 200+ models |
| **LiteLLM** | `models.litellm` | 100+ providers via LiteLLM |
| **Portkey** | `models.portkey` | Enterprise router |
| **Requesty** | `models.requesty` | API abstraction |

### Specialized/Regional
| Provider | Module |
|----------|--------|
| **DashScope (Alibaba)** | `models.dashscope` |
| **Moonshot** | `models.moonshot` |
| **InternLM** | `models.internlm` |
| **SambaNova** | `models.sambanova` |
| **Databricks** | `models.langdb` |
| **Nebius** | `models.nebius` |
| **SiliconFlow** | `models.siliconflow` |
| **Deepinfra** | `models.deepinfra` |
| **CometAPI** | `models.cometapi` |
| **N1N** | `models.n1n` |
| **Nexus** | `models.nexus` |
| **Vercel AI** | `models.vercel` |
| **AimlAPI** | `models.aimlapi` |

### Model Base Class

All models share a unified interface:
- `response()` / `async_response()` — Single request-response
- `stream()` / `async_stream()` — Streaming responses
- Tool call handling
- Structured output support
- Token usage and cost tracking
- Retry logic

---

## 8. Knowledge & RAG System

**File:** `libs/agno/agno/knowledge/knowledge.py` (3,501 lines, 144KB)

Agno's knowledge system provides plug-and-play RAG (Retrieval-Augmented Generation) with multiple backends, readers, chunkers, and embedders.

### Architecture

```
Document Sources → Readers → Chunkers → Embedders → VectorDB → Retrieval → Context Injection
```

### Document Readers (20+)

| Reader | Handles |
|--------|---------|
| `PDFReader` | PDF files (local and remote) |
| `DocxReader` | Microsoft Word documents |
| `ExcelReader` | Excel spreadsheets |
| `CSVReader` | CSV data files |
| `PPTXReader` | PowerPoint presentations |
| `MarkdownReader` | Markdown documents |
| `TextReader` | Plain text files |
| `JSONReader` | JSON files |
| `WebsiteReader` | Web pages (HTML) |
| `WebSearchReader` | Web search results |
| `ArxivReader` | ArXiv papers (by ID or query) |
| `WikipediaReader` | Wikipedia articles |
| `YoutubeReader` | YouTube transcripts |
| `TavilyReader` | Tavily API content |
| `FirecrawlReader` | Firecrawl scraping |
| `S3Reader` | AWS S3 files |
| `ReaderFactory` | Auto-detect format |

### Cloud Storage Loaders

| Loader | Source |
|--------|--------|
| `S3Loader` | AWS S3 bucket |
| `GCSLoader` | Google Cloud Storage |
| `AzureBlobLoader` | Azure Blob Storage |
| `SharePointLoader` | Microsoft SharePoint |
| `GitHubLoader` | GitHub repositories |

### Chunking Strategies (8)

| Strategy | Description |
|----------|-------------|
| `RecursiveChunker` | Recursive text splitting (default) |
| `SemanticChunker` | LLM-aware semantic boundaries |
| `MarkdownChunker` | Respects markdown structure |
| `CodeChunker` | Code-aware chunking |
| `DocumentChunker` | Preserves document structure |
| `RowChunker` | Row-based (for CSV/tables) |
| `FixedChunker` | Fixed-size chunks |
| `AgenticChunker` | Agent-guided chunking decisions |

### Embedder Providers (18)

OpenAI, Cohere, Google, Mistral, Ollama, HuggingFace, Jina, SentenceTransformer, VoyageAI, AWS Bedrock, Azure, Together, Fireworks, and others.

### Rerankers

Extensible reranker system for re-ranking retrieved results by relevance before injection.

### Knowledge Features

- **Hybrid search**: Combine semantic (vector) + keyword (BM25) search
- **Metadata filtering**: `FilterExpr` system for faceted search
- **Agentic RAG**: Agent decides when/what to query from knowledge
- **Incremental updates**: Upsert chunks without full rebuild
- **Namespace isolation**: Multiple knowledge bases in one vector DB
- **Remote knowledge**: Access knowledge from remote Agno instances

### Knowledge Usage Example

```python
from agno.knowledge import Knowledge
from agno.vectordb.pgvector import PgVector
from agno.embedder.openai import OpenAIEmbedder

knowledge = Knowledge(
    sources=[
        PDFReader(path="./docs/"),
        WebsiteReader(urls=["https://example.com/docs"]),
    ],
    vector_db=PgVector(
        table_name="knowledge",
        db_url="postgresql://...",
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
    chunking_strategy=SemanticChunker(),
    num_documents=5,
)

agent = Agent(knowledge=knowledge, search_knowledge=True)
```

---

## 9. Vector Databases — 18+ Backends

**Directory:** `libs/agno/agno/vectordb/`

| VectorDB | Module | Notes |
|---------|--------|-------|
| **pgvector** | `vectordb.pgvector` | PostgreSQL extension (recommended production) |
| **Qdrant** | `vectordb.qdrant` | High-performance, on-prem/cloud |
| **Pinecone** | `vectordb.pineconedb` | Managed cloud |
| **Weaviate** | `vectordb.weaviate` | Open-source hybrid search |
| **Chroma** | `vectordb.chroma` | Embedded, great for dev |
| **Milvus** | `vectordb.milvus` | Open-source, scalable |
| **MongoDB** | `vectordb.mongodb` | MongoDB Atlas vector search |
| **LanceDB** | `vectordb.lancedb` | Embedded, columnar |
| **Cassandra** | `vectordb.cassandra` | Apache Cassandra |
| **Redis** | `vectordb.redis` | Redis vector search |
| **ClickHouse** | `vectordb.clickhouse` | Analytics-optimized |
| **Couchbase** | `vectordb.couchbase` | Couchbase vector search |
| **SingleStore** | `vectordb.singlestore` | Hybrid SQL + vector |
| **SurrealDB** | `vectordb.surrealdb` | Multi-model DB |
| **Upstash** | `vectordb.upstashdb` | Serverless Redis/vector |
| **LlamaIndex** | `vectordb.llamaindex` | LlamaIndex VectorStore adapter |
| **LangChain** | `vectordb.langchaindb` | LangChain VectorStore adapter |
| **LightRAG** | `vectordb.lightrag` | Graph + vector hybrid |

All backends share the same interface: `search()`, `insert()`, `upsert()`, `delete()`, `exists()`, `drop_table()`.

---

## 10. Storage & Databases — 13+ Backends

**Directory:** `libs/agno/agno/db/`

Used for storing agent sessions, conversation history, memories, and run state.

| Backend | Module | Use Case |
|---------|--------|---------|
| **PostgreSQL** | `db.postgres` | Production SQL (recommended) |
| **Async PostgreSQL** | `db.async_postgres` | High-throughput async |
| **MySQL** | `db.mysql` | MySQL/MariaDB |
| **SQLite** | `db.sqlite` | Development / single-node |
| **MongoDB** | `db.mongo` | Document store |
| **DynamoDB** | `db.dynamo` | AWS serverless |
| **Redis** | `db.redis` | Fast key-value |
| **Firestore** | `db.firestore` | Google Cloud NoSQL |
| **GCS JSON** | `db.gcs_json` | Simple JSON in GCS |
| **JSON** | `db.json` | File-based JSON |
| **In-Memory** | `db.in_memory` | Testing only |
| **SurrealDB** | `db.surrealdb` | Multi-model |
| **SingleStore** | `db.singlestore` | Distributed SQL |

The base `Database` class (63KB) provides rich query filtering, schema migrations, and CRUD operations for agent/team/workflow sessions.

---

## 11. Memory & Learning System

### Memory Manager

**File:** `libs/agno/agno/memory/manager.py` (61KB)

The `MemoryManager` provides persistent, cross-session memory for agents:

```python
from agno.memory import MemoryManager
from agno.db.postgres import PostgresDb

memory = MemoryManager(
    db=PostgresDb(table_name="memories", db_url="..."),
)

agent = Agent(memory=memory, enable_agentic_memory=True)
```

**Memory features:**
- Automatic memory extraction from conversations
- Semantic memory search
- Token-aware memory management (prune when context fills)
- Memory optimization strategies (summarize old memories)
- `UserMemory` schema with metadata
- Cross-session memory persistence

### Memory Optimization Strategies

| Strategy | Description |
|----------|-------------|
| `SummarizeStrategy` | Compress old memories via LLM summarization |
| Custom strategies | Pluggable base class |

### Learning System (LearningMachine)

**Directory:** `libs/agno/agno/learn/`

The `LearningMachine` is a sophisticated system for continuous agent improvement:

| Learning Type | Description |
|--------------|-------------|
| `UserProfile` | Learn user preferences and characteristics |
| `Memory` | Explicit facts to remember |
| `EntityMemory` | Facts about specific entities (people, companies) |
| `SessionContext` | Context from the current session |
| `LearnedKnowledge` | New knowledge to add to knowledge base |
| `DecisionLog` | Track and learn from decisions made |

Each learning type has its own persistent store and can be queried later to inform agent responses.

**Example:**
```python
from agno.learn import LearningMachine

learning_machine = LearningMachine(
    db=PostgresDb(...),
    enable_user_profile=True,
    enable_entity_memory=True,
    enable_decision_log=True,
)

agent = Agent(learning_machine=learning_machine)
```

---

## 12. MCP (Model Context Protocol)

**Files:** `libs/agno/agno/tools/mcp/`, `libs/agno/agno/os/mcp.py`

Agno has comprehensive MCP support in both directions:
- **As MCP Client**: Connect to external MCP servers to consume their tools
- **As MCP Server**: Expose Agno agents/teams/workflows as an MCP server

### MCP Client

**`MCPTools`** — Single server connection:
```python
from agno.tools.mcp import MCPTools

# stdio transport (local process)
async with MCPTools("npx -y @modelcontextprotocol/server-filesystem /path") as mcp:
    agent = Agent(tools=[mcp])
    await agent.arun("List files in /path")

# SSE transport (remote server)
async with MCPTools(url="https://mcp.example.com/sse") as mcp:
    agent = Agent(tools=[mcp])

# Streamable HTTP transport
async with MCPTools(url="https://mcp.example.com/mcp") as mcp:
    agent = Agent(tools=[mcp])
```

**`MultiMCPTools`** — Multiple servers simultaneously:
```python
from agno.tools.mcp import MultiMCPTools

async with MultiMCPTools(
    commands=[
        "npx -y @modelcontextprotocol/server-filesystem /path",
        "npx -y @modelcontextprotocol/server-github",
    ]
) as mcp:
    agent = Agent(tools=[mcp])
```

**`MCPToolbox`** — MCP Toolbox for Databases:
```python
from agno.tools.mcp_toolbox import MCPToolbox

toolbox = MCPToolbox(
    url="http://localhost:5000",
    toolset_name="my_toolset",
)
agent = Agent(tools=[toolbox])
```

### MCP Features
- **Transport types**: stdio, SSE, Streamable HTTP
- **Tool filtering**: Include or exclude specific tools by name
- **Dynamic headers**: Runtime auth header injection
- **Connection refresh**: Fresh connection per run option
- **Timeout configuration**: Per-server timeout settings
- **Tool namespacing**: Prefix tools to avoid name conflicts

### Agno as MCP Server

The `AgentOS` exposes an MCP server endpoint via `FastMCP`:
- Exposes agent run/stream as MCP tools
- Exposes memory and session management
- Any Claude Desktop or MCP client can connect to an Agno deployment
- Full authentication support

---

## 13. Agent OS — The Deployment Platform

**Directory:** `libs/agno/agno/os/`
**Main file:** `os/app.py` (56KB)

Agent OS is a full-featured **FastAPI-based control plane** for deploying and managing agents in production.

### REST API Endpoints

| Route | Description |
|-------|-------------|
| `GET /agents` | List all registered agents |
| `POST /agents/{id}/runs` | Execute an agent |
| `GET /agents/{id}/sessions` | List agent sessions |
| `GET /teams` | List all registered teams |
| `POST /teams/{id}/runs` | Execute a team |
| `GET /workflows` | List all workflows |
| `POST /workflows/{id}/runs` | Execute a workflow |
| `GET /sessions` | Query sessions |
| `GET /knowledge` | List knowledge bases |
| `POST /knowledge/{id}/search` | Search knowledge |
| `GET /memory` | Query memories |
| `POST /approvals/{id}/approve` | Approve pending runs |
| `POST /approvals/{id}/reject` | Reject pending runs |
| `GET /schedules` | List scheduled jobs |
| `GET /metrics` | Platform metrics |
| `GET /traces` | Execution traces |
| `GET /health` | Health check |
| `GET /registry` | Component registry |
| `POST /database/migrate` | Run migrations |

### WebSocket Support

Real-time streaming via WebSocket for all agent/team/workflow executions.

### Interfaces

| Interface | Description |
|-----------|-------------|
| `AGUI` | Web UI interface (connects to os.agno.com) |
| `A2A` | Agent-to-Agent protocol server |
| `Slack` | Slack bot integration |
| `WhatsApp` | WhatsApp bot integration |
| `Discord` | Discord bot integration |

### Authentication (RBAC)

**File:** `os/auth.py` (14KB)

- Role-based access control (RBAC)
- Symmetric and asymmetric key schemes
- Per-user and per-team permissions
- API key management

### Multi-tenancy

- Per-user session isolation
- Per-session data segregation
- User-scoped memory and history
- Team-level access control

### Starting Agent OS

```python
from agno.agent import Agent
from agno.os import AgentOS

app = AgentOS(
    agents=[my_agent],
    teams=[my_team],
    workflows=[my_workflow],
    auth=...,
)

# Run with uvicorn
# uvicorn main:app.api --host 0.0.0.0 --port 8000
```

---

## 14. Reasoning System

**Directory:** `libs/agno/agno/reasoning/`

Agno provides a dedicated reasoning system that enables step-by-step deliberative thinking before answering.

### Reasoning Implementations

| Model/Provider | Description |
|----------------|-------------|
| OpenAI o1/o3 | Native extended thinking |
| Anthropic Claude | Extended thinking mode |
| DeepSeek R1 | Chain-of-thought reasoning |
| Gemini with thinking | Google's thinking mode |
| Groq | Fast reasoning inference |
| Azure AI Foundry | Azure reasoning models |
| Ollama | Local reasoning models |
| VertexAI | GCP reasoning |
| Default | Generic chain-of-thought fallback |

### Usage

```python
agent = Agent(
    model=OpenAIChat(id="o1"),
    reasoning=True,
    show_reasoning=True,  # Show intermediate steps
)
```

---

## 15. Evaluation Framework

**Directory:** `libs/agno/agno/eval/`

Agno includes a built-in evaluation framework for testing and benchmarking agent quality.

### Evaluation Types

| Evaluator | Description |
|-----------|-------------|
| `AccuracyEval` | Semantic accuracy using LLM-as-judge |
| `AgentAsJudgeEval` | Use an agent to evaluate another agent |
| `PerformanceEval` | Latency, throughput, and resource usage |
| `ReliabilityEval` | Expected tool call patterns and error rates |

### Example

```python
from agno.eval import AccuracyEval

eval = AccuracyEval(
    agent=my_agent,
    questions=[
        {"question": "What is 2+2?", "expected": "4"},
    ],
)
results = eval.run()
print(results.accuracy_score)  # 0.0 - 1.0
```

---

## 16. Guardrails & Safety

**Directory:** `libs/agno/agno/guardrails/`

| Guardrail | Description |
|-----------|-------------|
| `OpenAIGuardrail` | OpenAI moderation API |
| `PIIGuardrail` | Detect and redact PII |
| `PromptInjectionGuardrail` | Detect prompt injection attacks |
| Custom | Extend `BaseGuardrail` |

Guardrails run before agent execution and can block, modify, or pass through requests.

```python
from agno.guardrails import PIIGuardrail, PromptInjectionGuardrail

agent = Agent(
    guardrails=[PIIGuardrail(), PromptInjectionGuardrail()],
)
```

---

## 17. Human-in-the-Loop & Approvals

**Directory:** `libs/agno/agno/approval/`

Agno supports human checkpoints where execution pauses for approval before proceeding.

### Approval Types

- **Tool-level approval**: Approve/reject specific tool calls
- **Run-level approval**: Approve the entire agent run
- **Workflow checkpoints**: `@pause` decorator in workflows

```python
from agno.approval import ApprovalRequired

agent = Agent(
    approval=ApprovalRequired(tools=["delete_file", "send_email"]),
)
```

### Approval API (via Agent OS)

Approvals are managed via the REST API:
```
GET  /approvals          — List pending approvals
POST /approvals/{id}/approve  — Approve
POST /approvals/{id}/reject   — Reject
```

---

## 18. Hooks System

**Directory:** `libs/agno/agno/hooks/`

Hooks allow custom logic injection at specific execution points.

### Hook Types

| Hook | Fires When |
|------|-----------|
| `before_run` | Before agent processes input |
| `after_run` | After agent returns response |
| `before_tool_call` | Before each tool execution |
| `after_tool_call` | After each tool returns |
| `on_stream` | For each streaming chunk |
| `on_error` | When an error occurs |

```python
from agno.hooks import hook

@hook(on="after_tool_call")
def log_tool_call(tool_name, args, result):
    print(f"Tool {tool_name} called with {args} → {result}")

agent = Agent(hooks=[log_tool_call])
```

---

## 19. Streaming & Real-time

Agno is designed for streaming-first execution.

### Streaming Modes

| Mode | Description |
|------|-------------|
| `stream=True` | Stream text tokens as they're generated |
| `stream_intermediate_steps=True` | Stream tool calls and results |
| WebSocket | Persistent connection for long-running agents |
| SSE | Server-Sent Events for HTTP streaming |

### Run Events

Each streaming chunk is a typed `RunEvent`:
- `RunEvent.run_response` — Text chunk
- `RunEvent.tool_call_started` — Tool beginning execution
- `RunEvent.tool_call_completed` — Tool finished
- `RunEvent.run_completed` — Agent finished
- `RunEvent.run_error` — Error occurred

```python
async for event in agent.arun("Tell me about Paris", stream=True):
    if event.event == RunEvent.run_response:
        print(event.content, end="")
```

---

## 20. Multi-modal Support

**File:** `libs/agno/agno/media.py`

Agno supports images, audio, and video as inputs/outputs.

| Media Type | Supported Formats |
|------------|-------------------|
| `Image` | Base64, URL, file path, remote URL |
| `Audio` | WAV, MP3, and other formats |
| `Video` | MP4 and common formats |
| `File` | Any file type |

```python
from agno.media import Image

agent = Agent(model=OpenAIChat(id="gpt-4o"))
agent.run(
    "Describe this image",
    images=[Image(url="https://example.com/photo.jpg")],
)
```

---

## 21. Observability & Tracing

**Directory:** `libs/agno/agno/tracing/`

### OpenTelemetry Integration

Full OTEL support with exporters for:
- Langfuse
- Arize Phoenix
- AgentOps
- LangSmith
- Any OTEL-compatible backend

### Metrics

**File:** `libs/agno/agno/metrics.py` (35KB)

Tracked per run and aggregated per session:
- **Token usage**: Input, output, cache, reasoning, audio tokens
- **Cost**: Per-token pricing by model
- **Latency**: Time-to-first-token, total generation time
- **Tool calls**: Per-tool invocation counts and timing
- **Session totals**: Aggregated metrics across all runs

### Session-level Dashboards

Connect to `os.agno.com` to see visual dashboards for:
- Agent runs and their metrics
- Team execution flows
- Knowledge base usage
- Memory stats
- Approval queues

---

## 22. Session Management

**Directory:** `libs/agno/agno/session/`

Agno maintains rich session state across multiple runs.

| Session Type | Description |
|-------------|-------------|
| `AgentSession` | Single agent's conversation history |
| `TeamSession` | Multi-agent team session |
| `WorkflowSession` | Workflow execution state |
| `SessionSummary` | Automatic summary of long sessions |

### Session Features

- **History**: Full message history with role/content
- **State**: Arbitrary key-value state dict
- **Caching**: Session-level cache for expensive operations
- **Summaries**: Automatic LLM-generated summaries for long sessions
- **Search**: Search historical sessions by content

---

## 23. Scheduling

**Directory:** `libs/agno/agno/scheduler/`

Agno supports scheduled agent/workflow execution.

| Component | Description |
|-----------|-------------|
| `ScheduleManager` | Manage scheduled jobs |
| `ScheduleExecutor` | Execute scheduled tasks |
| `SchedulePoller` | Poll for due tasks |
| `CronSchedule` | Cron-based scheduling |

Via Agent OS:
```
GET  /schedules          — List scheduled jobs
POST /schedules          — Create scheduled job
PUT  /schedules/{id}     — Update schedule
DELETE /schedules/{id}   — Delete schedule
```

---

## 24. Skills System

**Directory:** `libs/agno/agno/skills/`

Skills are pre-packaged instruction sets that give agents specific capabilities.

```python
from agno.skills import Skills, LocalSkills

skills = LocalSkills(
    path="./skills/",
    skills=["coding_assistant", "data_analyst"],
)

agent = Agent(skills=skills)
```

Skills are validated on load, ensuring proper format before being injected into agent instructions.

---

## 25. Agent-to-Agent (A2A) Protocol

**Directory:** `libs/agno/agno/client/a2a/`

Agno implements the **A2A (Agent-to-Agent)** protocol for distributed agent systems.

- Agents communicate via HTTP/WebSocket
- Standardized message format
- Cross-instance agent calls
- Discovery and registry support

```python
from agno.client.a2a import A2AClient

remote_agent = A2AClient(url="https://agents.example.com/my-agent")
result = await remote_agent.run("What is the weather today?")
```

---

## 26. Developer Experience

### Formatting & Linting
- **Ruff** for formatting and linting
- **MyPy** for type checking
- **Pre-commit hooks** for quality gates

### Virtual Environments
- `.venv/` — Development (tests, validation)
- `.venvs/demo/` — Cookbook examples (with all demo deps)

### Testing
- **Unit tests**: `libs/agno/tests/unit/`
- **Integration tests**: `libs/agno/tests/`
- **System tests**: Docker-based end-to-end
- **Cookbook test logs**: `TEST_LOG.md` per cookbook

### Scripts
```bash
./scripts/dev_setup.sh      # Dev environment
./scripts/demo_setup.sh     # Demo environment
./scripts/format.sh         # Run Ruff formatter
./scripts/validate.sh       # Run Ruff + MyPy
./scripts/test.sh           # Run tests
```

### Debugging
- `agent.print_response()` — Pretty-print response to terminal
- `show_tool_calls=True` — Show tool execution details
- `debug_mode=True` — Verbose execution logging
- `show_reasoning=True` — Show reasoning steps

---

## 27. Cookbook — 100+ Examples

Organized into 20+ topic directories:

| Directory | Topics |
|-----------|--------|
| `00_quickstart/` | First agent, first team, first workflow |
| `02_agents/` | 16 sub-topics: I/O, memory, hooks, reasoning, guardrails, etc. |
| `03_teams/` | 22 sub-topics: all team modes, distributed RAG, etc. |
| `04_workflows/` | 8 sub-topics: all execution patterns |
| `05_agent_os/` | 18 sub-topics: deployment, integrations, RBAC, scheduling, etc. |
| `06_storage/` | 14 storage backends with examples |
| `07_knowledge/` | 11 sub-topics: chunking, embedders, search types, etc. |
| `08_learning/` | 10 sub-topics — **the golden standard** |
| `09_evals/` | 4 evaluation types |
| `10_reasoning/` | 4 reasoning patterns |
| `11_memory/` | Memory manager and optimization |
| `90_models/` | 40+ provider examples |
| `91_tools/` | Tool patterns and MCP examples |
| `92_integrations/` | A2A, Discord, observability, RAG |

---

## Summary

Agno is a **comprehensive, production-grade agentic AI framework** with:

- **3 core primitives**: Agent, Team, Workflow — composable and interchangeable
- **43+ LLM providers** with unified interface
- **130+ pre-built tool integrations**
- **18+ vector database backends**
- **13+ storage backends**
- **8 chunking strategies** for RAG
- **Full MCP support** (client and server)
- **AgentOS**: Complete deployment platform with REST API, auth, tracing
- **Learning system**: 6 learning types for continuous agent improvement
- **Evaluation framework**: 4 evaluation approaches
- **Guardrails**: PII, prompt injection, moderation
- **Approvals**: Human-in-the-loop for sensitive operations
- **Streaming-first**: SSE, WebSocket, and async throughout
- **Enterprise-ready**: RBAC, audit logs, multi-tenancy, telemetry
