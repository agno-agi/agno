# Memory Part 2: The Learning Machine

Learning Machine is a unified learning system that gives agents the ability to remember, adapt, and improve. It coordinates multiple learning stores that work together:

```
Learning Stores
├── User Profile         — Long-term memory about users, accumulated over time
├── Session Context      — State, summary, goal, plan, progress for the current session
├── Learned Knowledge    — Reusable insights and patterns (requires vector DB)
├── Entity Memory        — Facts, events and relationships about entities
└── Not yet implemented
    ├── Decision Logs        — Why decisions were made
    ├── Behavioral Feedback  — What worked, what didn't
    └── Self-Improvement     — Continuously improving instructions
```

**The Goal:** An agent on interaction 1000 is fundamentally better than it was on interaction 1.

**The Advantage:** Instead of building memory, knowledge, and feedback systems separately, developers configure one system that handles all learning with consistent patterns for storage, retrieval, and lifecycle.

## Learning Modes

Learning Stores can be configured to run in different modes:

| Mode | Description | Best For |
|------|-------------|----------|
| **BACKGROUND** | Automatic extraction after each response | User profile, session context |
| **AGENTIC** | Agent decides when to save via tools | Learned knowledge, entity memory |
| **PROPOSE** | Agent proposes, human confirms before saving | Learned knowledge with oversight |
| **HITL** | Human-in-the-loop (reserved for future use) | — |

## What You'll Build

This cookbook contains **43 examples** across 9 categories:

```
cookbook/15_learning/
├── basics/                    # Start here (5 examples)
├── user_profile/              # User memory deep dive (5 examples)
├── session_context/           # Session state deep dive (4 examples)
├── entity_memory/             # Entity knowledge deep dive (5 examples)
├── learned_knowledge/         # Reusable insights deep dive (5 examples)
├── combined/                  # Multiple learning types (4 examples)
├── patterns/                  # Real-world agents (7 examples)
├── advanced/                  # Power user features (6 examples)
└── production/                # Production-ready examples (2 examples)
```

**Progressive complexity**: Start with `basics/`, master one learning store, combine them, then build production agents.

## Quick Comparison

| Store | Scope | Persistence | Use Case |
|-------|-------|-------------|----------|
| **User Profile** | Per user | Forever (accumulates) | "Remember Alice prefers dark mode" |
| **Session Context** | Per session | Session lifetime (replaces) | "We're debugging a React issue" |
| **Learned Knowledge** | Configurable | Forever (searchable) | "Always check egress costs first" |
| **Entity Memory** | Per entity | Forever (accumulates) | "Acme Corp uses PostgreSQL" |

## Built-in Learning Stores

### 1. User Profile Store

Captures long-term memory about users. Persists forever. Accumulates over time.

**Supported modes:** BACKGROUND, AGENTIC

**Two types of data:**
- **Profile fields** (structured): `name`, `preferred_name`, custom fields you define
- **Memories** (unstructured): observations that don't fit fields

```python
from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.learn import LearningMachine, UserProfileConfig

agent = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
    db=PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai"),
    learning=LearningMachine(
        user_profile=UserProfileConfig(
            mode=LearningMode.BACKGROUND, # Auto-extract from conversations
        ),
  ),
)

# Session 1
agent.run("I'm Alice, I work at Netflix", user_id="alice")

# Session 2
agent.run("What do you know about me?", user_id="alice")
# → "You're Alice, you work at Netflix"
```

### 2. Session Context Store

Captures state and summary for the current session. Updated (not accumulated) on each extraction.

**Supported modes:** BACKGROUND only

**Four types of data:**
- **Summary**: A brief summary of the current session
- **Goal**: The goal of the current session (requires `enable_planning=True`)
- **Plan**: Steps to achieve the goal (requires `enable_planning=True`)
- **Progress**: Completed steps (requires `enable_planning=True`)

**Key behavior**: Builds on previous context. Even if message history is truncated, the context persists.

```python
from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.learn import LearningMachine, SessionContextConfig

agent = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
    db=PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai"),
    learning=LearningMachine(
        session_context=SessionContextConfig(
            enable_planning=True, # Track goal, plan, progress (adds latency)
        ),
  ),
)

# Long conversation with many messages...
# Session context automatically tracks:
# - Summary: "Debugging a React performance issue"
# - Goal: "Fix the slow render on the dashboard"
# - Plan: ["Profile components", "Find bottleneck", "Optimize"]
# - Progress: ["Profile components ✓"]
```

> **⚠️ Note:** Planning mode adds latency. Only use for task-oriented agents where tracking goal/plan/progress is valuable.

### 3. Learned Knowledge Store

Captures reusable insights, patterns, and rules that apply across users and sessions.

**Supported modes:** AGENTIC, PROPOSE, BACKGROUND

**Requires a Knowledge base** (vector database) for semantic search.

**When to use**: Self-improving agents, research agents, any agent that should get smarter over time.

```python
from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.db.postgres import PostgresDb
from agno.learn import LearningMachine, LearnedKnowledgeConfig, LearningMode
from agno.knowledge import Knowledge
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.vectordb.pgvector import PgVector, SearchType

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)

# Vector DB for semantic search of learnings
knowledge_base = Knowledge(
    vector_db=PgVector(
        db_url=db_url,
        table_name="agent_learnings",
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)

agent = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
    db=db,
    learning=LearningMachine(
        learned_knowledge=LearnedKnowledgeConfig(
            knowledge=knowledge_base,
            mode=LearningMode.AGENTIC,  # Agent decides when to save
        ),
    ),
)

# Agent discovers an insight and saves it
agent.run("When comparing cloud providers, always check egress costs first")

# Later, different user, agent searches and applies prior learnings
agent.run("Help me compare AWS vs GCP")
# Agent searches knowledge base, finds the egress insight, applies it
```

### 4. Entity Memory Store

Captures knowledge about external entities: companies, projects, people, products, systems.

**Supported modes:** BACKGROUND, AGENTIC

**Three types of entity data:**
- **Facts** (semantic memory): Timeless truths — "Uses PostgreSQL"
- **Events** (episodic memory): Time-bound occurrences — "Launched v2 on Jan 15"
- **Relationships** (graph edges): Connections — "Bob is CTO of Acme"

**When to use**: CRM-style agents, research agents, any agent tracking external entities.

```python
from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.db.postgres import PostgresDb
from agno.learn import LearningMachine, EntityMemoryConfig

agent = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
    db=PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai"),
    learning=LearningMachine(
        entity_memory=EntityMemoryConfig(
            namespace="global",  # Shared across all users
            enable_agent_tools=True,  # Agent can create/update entities
        ),
    ),
)

# Agent learns about entities from conversations
agent.run("Acme Corp just migrated to PostgreSQL and hired Bob as CTO")

# Later, agent can recall and use this knowledge
agent.run("What database does Acme use?")
# → "Acme Corp uses PostgreSQL"
```

## Getting Started

### 1. Clone the repo

```bash
git clone https://github.com/agno-agi/agno.git
cd agno
```

### 2. Create a virtual environment and install dependencies

Using the setup script (requires `uv`):

```bash
./cookbook/15_learning/venv_setup.sh
```

Or manually:
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r cookbook/15_learning/requirements.txt
```

### 3. Export environment variables

```bash
# Required for accessing OpenAI models
export OPENAI_API_KEY=your-openai-api-key

# Required for research agents using parallel search services
export PARALLEL_API_KEY=your-parallel-api-key
```

### 4. Run Postgres with PgVector

Postgres stores agent sessions, memory, knowledge, and state. Install [Docker Desktop](https://docs.docker.com/desktop/install/mac-install/) and run:

```bash
./cookbook/15_learning/run_pgvector.sh
```

Or run directly:
```bash
docker run -d \
  -e POSTGRES_DB=ai \
  -e POSTGRES_USER=ai \
  -e POSTGRES_PASSWORD=ai \
  -e PGDATA=/var/lib/postgresql \
  -v pgvolume:/var/lib/postgresql \
  -p 5532:5432 \
  --name pgvector \
  agnohq/pgvector:18
```

### 5. Run Cookbook Examples Individually

```bash
# Start with the basics
python cookbook/15_learning/basics/01_hello_learning.py

# Or run any specific example
python cookbook/15_learning/user_profile/02_agentic_mode.py
python cookbook/15_learning/patterns/research_agent.py
```

### 6. Run the Agent OS

Agno provides a web interface for interacting with agents. Start the server:

```bash
python cookbook/15_learning/run.py
```

Then visit [os.agno.com](https://os.agno.com) and add `http://localhost:7777` as an endpoint.
## File Structure

```
cookbook/15_learning/
│
├── README.md                           # You are here
├── db.py                               # Shared database config
├── requirements.txt                    # Dependencies
├── run.py                              # AgentOS entrypoint
├── config.yaml                         # AgentOS config
│
├── basics/                             # Start here (5 examples)
│   ├── 01_hello_learning.py            # Minimal working example
│   ├── 02_user_profile_quick.py        # User memory in 30 lines
│   ├── 03_session_context_quick.py     # Session state in 30 lines
│   ├── 04_entity_memory_quick.py       # Entity tracking in 30 lines
│   └── 05_learned_knowledge_quick.py   # Knowledge capture in 30 lines
│
├── user_profile/                       # User memory deep dive (5 examples)
│   ├── 01_background_extraction.py     # Automatic extraction
│   ├── 02_agentic_mode.py              # Agent-driven updates
│   ├── 03_custom_schema.py             # Extend with typed fields
│   ├── 04_memory_vs_fields.py          # When to use which
│   └── 05_memory_operations.py         # Add/update/delete flow
│
├── session_context/                    # Session state deep dive (4 examples)
│   ├── 01_summary_mode.py              # Basic summarization
│   ├── 02_planning_mode.py             # Goal → Plan → Progress
│   ├── 03_context_continuity.py        # Building on previous
│   └── 04_long_conversations.py        # Handling truncation
│
├── entity_memory/                      # Entity knowledge deep dive (5 examples)
│   ├── 01_facts_and_events.py          # Semantic vs episodic
│   ├── 02_entity_relationships.py      # Graph edges
│   ├── 03_namespace_sharing.py         # Sharing boundaries
│   ├── 04_background_extraction.py     # Auto-extract entities
│   └── 05_entity_search.py             # Finding entities
│
├── learned_knowledge/                  # Reusable insights deep dive (5 examples)
│   ├── 01_agentic_mode.py              # Agent saves directly
│   ├── 02_propose_mode.py              # Human approval
│   ├── 03_background_extraction.py     # Auto-extract
│   ├── 04_search_and_apply.py          # Using prior learnings
│   └── 05_namespace_scoping.py         # Private vs shared
│
├── combined/                           # Multiple types together (4 examples)
│   ├── 01_user_plus_session.py         # Profile + session
│   ├── 02_user_plus_entities.py        # Profile + entities
│   ├── 03_full_learning_machine.py     # All four types
│   └── 04_learning_machine_builder.py  # Factory patterns
│
├── patterns/                           # Real-world agents (7 examples)
│   ├── support_agent.py                # Customer support
│   ├── research_agent.py               # Self-improving researcher
│   ├── coding_assistant.py             # Developer helper
│   ├── personal_assistant.py           # Long-term personal AI
│   ├── sales_agent.py                  # CRM-style tracking
│   ├── team_knowledge_agent.py         # Shared team learnings
│   └── onboarding_agent.py             # New user onboarding
│
├── advanced/                           # Power user features (6 examples)
│   ├── 01_multi_user.py                # Multiple users
│   ├── 02_curator_maintenance.py       # Pruning + dedup
│   ├── 03_extraction_timing.py         # Before/parallel/after
│   ├── 04_custom_store.py              # Implement your own
│   ├── 05_async_patterns.py            # Full async
│   └── 06_debugging.py                 # Debug mode
│
└── production/                         # Production-ready (2 examples)
    ├── gpu_poor_learning.py            # System-level learning
    └── plan_and_learn.py               # PaL with LearningMachine
```

## Best Practices

### 1. Start Simple

Don't enable all four learning types at once. Start with `user_profile=True`, then add others as needed.

```python
# Simple: just enable with defaults
learning = LearningMachine(
    db=db,
    model=model,
    user_profile=True,  # Uses default UserProfileConfig
)

# Advanced: customize with config
learning = LearningMachine(
    db=db,
    model=model,
    user_profile=UserProfileConfig(
        mode=LearningMode.AGENTIC,
        enable_agent_tools=True,
    ),
)
```

### 2. Use the Right Mode

| Store | Recommended Mode | Why |
|-------|------------------|-----|
| User Profile | BACKGROUND | Always capture user info automatically |
| Session Context | BACKGROUND | Always track session state (only mode supported) |
| Entity Memory | BACKGROUND or AGENTIC | BACKGROUND for passive extraction, AGENTIC for agent control |
| Learned Knowledge | AGENTIC or PROPOSE | Agent should decide what's worth saving |

### 3. Namespace Thoughtfully

- `"user"` — Personal/private data (requires `user_id`)
- `"global"` — Shared knowledge (default)
- Custom string — Team or project isolation (e.g., `"engineering"`, `"sales_west"`)

```python
# Private entity memory per user
entity_memory=EntityMemoryConfig(
    namespace="user",  # Each user sees only their entities
)

# Shared learnings across a team
learned_knowledge=LearnedKnowledgeConfig(
    namespace="engineering",  # Only engineering team sees these
)
```

### 4. Maintain Your Memories

Use the Curator to prune old data and deduplicate:

```python
# Prune memories older than 90 days, keep max 100
removed = learning.curator.prune(
    user_id="alice",
    max_age_days=90,
    max_count=100,
)

# Remove duplicate memories
deduped = learning.curator.deduplicate(user_id="alice")
```

### 5. Custom Schemas for Production

Extend the base schemas with typed fields for your domain. The LLM sees field descriptions and updates them appropriately.

```python
from dataclasses import dataclass, field
from typing import Optional
from agno.learn.schemas import UserProfile

@dataclass
class CustomerProfile(UserProfile):
    """Extended user profile for customer support."""

    company: Optional[str] = field(
        default=None,
        metadata={"description": "Company or organization"}
    )
    plan_tier: Optional[str] = field(
        default=None,
        metadata={"description": "Subscription tier: free | pro | enterprise"}
    )
    timezone: Optional[str] = field(
        default=None,
        metadata={"description": "User's timezone (e.g., America/New_York)"}
    )
    expertise_level: Optional[str] = field(
        default=None,
        metadata={"description": "Technical level: beginner | intermediate | expert"}
    )

# Use custom schema
learning = LearningMachine(
    db=db,
    model=model,
    user_profile=UserProfileConfig(
        schema=CustomerProfile,
    ),
)
```

## Learn More

- [Agno Documentation](https://docs.agno.com)
- [Learning Machine Reference](https://docs.agno.com/learn)

Built with 💜 by the Agno team
