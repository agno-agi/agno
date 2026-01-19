# Internal Knowledge Agent

A RAG-powered knowledge agent that provides intelligent access to internal company documentation. Enables employees to ask questions and get accurate answers with source citations from company knowledge bases.

## Quick Start

### 1. Prerequisites

```bash
# Set OpenAI API key (for embeddings and GPT-5.2)
export OPENAI_API_KEY=your-openai-api-key

# Start PostgreSQL with PgVector
./cookbook/scripts/run_pgvector.sh
```

### 2. Load Knowledge Base

```bash
# Load sample company documents
.venvs/demo/bin/python cookbook/01_showcase/01_agents/knowledge_agent/scripts/load_knowledge.py
```

### 3. Run Examples

```bash
# Basic Q&A
.venvs/demo/bin/python cookbook/01_showcase/01_agents/knowledge_agent/examples/01_basic_query.py

# Multi-turn conversation
.venvs/demo/bin/python cookbook/01_showcase/01_agents/knowledge_agent/examples/02_conversation.py

# Edge cases and uncertainty
.venvs/demo/bin/python cookbook/01_showcase/01_agents/knowledge_agent/examples/03_edge_cases.py
```

## Key Concepts

### RAG (Retrieval-Augmented Generation)

The agent uses RAG to answer questions:

1. **Question Received** - User asks a question
2. **Search Knowledge** - Vector search finds relevant documents
3. **Retrieve Context** - Top-k most relevant chunks retrieved
4. **Synthesize Answer** - LLM generates answer from context
5. **Cite Sources** - Answer includes document references

### Hybrid Search

The knowledge base uses hybrid search combining:

| Search Type | Description |
|-------------|-------------|
| **Semantic** | Vector similarity for conceptual matches |
| **Keyword** | BM25 for exact term matches |
| **Combined** | Best of both for comprehensive results |

### Sample Knowledge Base

The tutorial includes sample documents:

| Document | Content | Use Case |
|----------|---------|----------|
| `employee_handbook.md` | PTO, benefits, policies | Policy questions |
| `engineering_wiki.md` | Setup, coding standards | Technical questions |
| `onboarding_checklist.md` | First week tasks | New hire questions |
| `product_guide.md` | Platform features, API | Product questions |

## Architecture

```
User Question
    |
    v
[Knowledge Agent (GPT-5.2)]
    |
    +---> Search Knowledge Base
    |         |
    |         v
    |     [PgVector (Hybrid Search)]
    |         |
    |         +---> Semantic search
    |         +---> Keyword search
    |         |
    |         v
    |     Top-k relevant chunks
    |
    +---> ReasoningTools ---> think/analyze
    |
    +---> Conversation History (5 turns)
    |
    v
Answer with Source Citations
```

## Agent Configuration

```python
from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.pgvector import PgVector, SearchType

# Knowledge base with hybrid search
knowledge = Knowledge(
    vector_db=PgVector(
        table_name="company_knowledge",
        db_url=DB_URL,
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
    max_results=10,
)

# Agent with RAG
agent = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
    knowledge=knowledge,
    search_knowledge=True,
    add_history_to_context=True,
    num_history_runs=5,
)
```

## Adding Your Own Documents

### Supported Formats

- Markdown (.md)
- PDF (.pdf)
- Text (.txt)
- URLs (web pages)

### Loading Documents

```python
from agent import company_knowledge

# Load from file
company_knowledge.load(path="path/to/document.pdf")

# Load from URL
company_knowledge.load(url="https://docs.example.com/guide")

# Load multiple files
company_knowledge.load(path="path/to/docs/", recursive=True)
```

## Handling Uncertainty

The agent is designed to handle edge cases gracefully:

| Scenario | Behavior |
|----------|----------|
| Not in docs | States "I don't have information about X" |
| Ambiguous | Asks for clarification or lists options |
| Partial match | Provides what's known, notes limitations |
| Conflicting sources | Notes discrepancy, cites both sources |

## Dependencies

- `agno` - Core framework
- `openai` - GPT-5.2 model and embeddings
- `psycopg[binary]` - PostgreSQL driver
- `pgvector` - Vector extension

## API Credentials

To use this agent, you need an OpenAI API key:

1. Go to [platform.openai.com](https://platform.openai.com)
2. Create an account or sign in
3. Generate an API key
4. Set `OPENAI_API_KEY` environment variable
