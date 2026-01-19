# Agents 2.0: The Learning Machine

A comprehensive guide to building agents that learn, adapt, and improve.

## Overview

LearningMachine is a unified learning system that enables agents to learn from every interaction. It coordinates multiple **learning stores**, each handling a different type of knowledge:

| Store | What It Captures | Scope | Use Case |
|-------|------------------|-------|----------|
| **User Profile** | Structured fields (name, preferences) | Per user | Personalization |
| **User Memory** | Unstructured observations about users | Per user | Context, preferences |
| **Session Context** | Goal, plan, progress, summary | Per session | Task continuity |
| **Entity Memory** | Facts, events, relationships | Configurable | CRM, knowledge graph |
| **Learned Knowledge** | Insights, patterns, best practices | Configurable | Collective intelligence |

## Quick Start

```python
from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIResponses

# Setup
db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

# The simplest learning agent
agent = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
    db=db,
    learning=True,  # That's it!
)

# Use it
agent.print_response(
    "I'm Alex, I prefer concise answers.",
    user_id="alex@example.com",
    session_id="session_1",
)
```

## Cookbook Structure

```
cookbook/08_learning/
├── 01_basics/              # Start here - essential examples
│   ├── 1a_user_profile_always.py
│   ├── 1b_user_profile_agentic.py
│   ├── 2a_user_memory_always.py
│   ├── 2b_user_memory_agentic.py
│   ├── 3a_session_context_summary.py
│   ├── 3b_session_context_planning.py
│   ├── 4_learned_knowledge.py
│   ├── 5a_entity_memory_always.py
│   └── 5b_entity_memory_agentic.py
│
├── 02_user_profile/        # Deep dives into user profiles
│   ├── 01_always_extraction.py
│   ├── 02_agentic_mode.py
│   └── 03_custom_schema.py
│
├── 03_session_context/     # Deep dives into session tracking
│   ├── 01_summary_mode.py
│   └── 02_planning_mode.py
│
├── 04_entity_memory/       # Deep dives into entity memory
│   ├── 01_facts_and_events.py
│   └── 02_entity_relationships.py
│
├── 05_learned_knowledge/   # Deep dives into learned knowledge
│   ├── 01_agentic_mode.py
│   └── 02_propose_mode.py
│
└── 07_patterns/            # Real-world patterns
    ├── personal_assistant.py
    └── support_agent.py
```

## Running the Cookbooks

### 1. Clone the repo

```bash
git clone https://github.com/agno-agi/agno.git
cd agno
```

### 2. Create a virtual environment and install dependencies

Using the setup script (requires `uv`):

```bash
./cookbook/08_learning/setup_venv.sh
```

Or manually:
```bash
python -m venv .venv
source .venv/bin/activate
uv pip install -r cookbook/08_learning/requirements.txt
```

### 3. Export environment variables

```bash
# Required for accessing OpenAI models
export OPENAI_API_KEY=your-openai-api-key
```

### 4. Run Postgres with PgVector

Postgres stores agent sessions, memory, knowledge, and state. Install [Docker Desktop](https://docs.docker.com/desktop/install/mac-install/) and run:

```bash
./cookbook/scripts/run_pgvector.sh
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

### 5. Run Cookbooks

```bash
# Start with the basics
python cookbook/08_learning/01_basics/1a_user_profile_always.py

# Or run any specific example
python cookbook/08_learning/02_user_profile/03_custom_schema.py
python cookbook/08_learning/07_patterns/personal_assistant.py
```

---

## Key Concepts

### The Goal
An agent on interaction 1000 is fundamentally better than it was on interaction 1.

### The Advantage
Instead of building memory, knowledge, and feedback systems separately, configure one system that handles all learning with consistent patterns.

### Three DX Levels

```python
# Level 1: Dead Simple
agent = Agent(model=model, db=db, learning=True)

# Level 2: Pick What You Want
agent = Agent(
    model=model,
    db=db,
    learning=LearningMachine(
        user_profile=True,
        session_context=True,
        entity_memory=False,
        learned_knowledge=False,
    ),
)

# Level 3: Full Control
agent = Agent(
    model=model,
    db=db,
    learning=LearningMachine(
        user_profile=UserProfileConfig(
            mode=LearningMode.AGENTIC,
        ),
        session_context=SessionContextConfig(
            enable_planning=True,
        ),
    ),
)
```

### Learning Modes

Each Learning Store can be configured to run in different modes:

```python
from agno.learn import LearningMode

# ALWAYS (default for user_profile, session_context)
# - Automatic extraction after conversations
# - No agent tools needed
# - Extra LLM call per interaction

# AGENTIC (default for learned_knowledge)
# - Agent decides when to save via tools
# - More control, less noise
# - No extra LLM calls

# PROPOSE
# - Agent proposes, user confirms
# - Human-in-the-loop quality control
# - Good for high-stakes knowledge
```

### Built-in Learning Stores

#### 1. User Profile Store

Captures structured profile fields about users. Persists forever. Updated as new info is learned.

**Supported modes:** ALWAYS, AGENTIC

**Data stored:** `name`, `preferred_name`, and any custom fields you define.

See also: **Memories Store** for unstructured observations that don't fit fields.

```python
from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.learn import LearningMachine, UserProfileConfig

agent = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
    db=PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai"),
    learning=LearningMachine(
        user_profile=UserProfileConfig(
            mode=LearningMode.ALWAYS,
        ),
    ),
)

# Session 1
agent.run("I'm Alice, I work at Netflix", user_id="alice")

# Session 2
agent.run("What do you know about me?", user_id="alice")
# -> "You're Alice, you work at Netflix"
```

#### 2. User Memory Store

Captures unstructured observations about users that don't fit into structured profile fields.

**Supported modes:** ALWAYS, AGENTIC

**When to use:** For context like "prefers detailed explanations", "works on ML projects" - observations that are useful but not structured.

```python
from agno.learn import LearningMachine, UserMemoryConfig, LearningMode

agent = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
    db=PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai"),
    learning=LearningMachine(
        user_memory=UserMemoryConfig(
            mode=LearningMode.ALWAYS,
        ),
    ),
)

# Session 1
agent.run("I prefer code examples over explanations", user_id="alice")

# Session 2 - memory persists
agent.run("Explain async/await", user_id="alice")
# Agent knows Alice prefers code examples and adapts response
```

#### 3. Session Context Store

Captures state and summary for the current session.

**Supported modes:** ALWAYS only

**Data stored:**
- **Summary**: A brief summary of the current session
- **Goal**: The goal of the current session (requires `enable_planning=True`)
- **Plan**: Steps to achieve the goal (requires `enable_planning=True`)
- **Progress**: Completed steps (requires `enable_planning=True`)

```python
from agno.learn import LearningMachine, SessionContextConfig

agent = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
    db=PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai"),
    learning=LearningMachine(
        session_context=SessionContextConfig(
            enable_planning=True,
        ),
    ),
)

# Session context automatically tracks goal, plan, progress
```

#### 4. Learned Knowledge Store

Captures reusable insights, patterns, and rules that apply across users and sessions.

**Supported modes:** AGENTIC, PROPOSE, ALWAYS

**Requires a Knowledge base** (vector database) for semantic search.

```python
from agno.knowledge import Knowledge
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.learn import LearningMachine, LearnedKnowledgeConfig, LearningMode
from agno.vectordb.pgvector import PgVector, SearchType

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

knowledge = Knowledge(
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
        knowledge=knowledge,
        learned_knowledge=LearnedKnowledgeConfig(
            mode=LearningMode.AGENTIC,
        ),
    ),
)
```

#### 5. Entity Memory Store

Captures knowledge about external entities: companies, projects, people, products, systems.

**Supported modes:** ALWAYS, AGENTIC

**Three types of entity data:**
- **Facts** (semantic memory): Timeless truths - "Uses PostgreSQL"
- **Events** (episodic memory): Time-bound occurrences - "Launched v2 on Jan 15"
- **Relationships** (graph edges): Connections - "Bob is CTO of Acme"

```python
from agno.learn import LearningMachine, EntityMemoryConfig

agent = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
    db=PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai"),
    learning=LearningMachine(
        entity_memory=EntityMemoryConfig(
            namespace="global",
        ),
    ),
)

# Agent learns about entities from conversations
agent.run("Acme Corp just migrated to PostgreSQL and hired Bob as CTO")

# Later, agent can recall and use this knowledge
agent.run("What database does Acme use?")
# -> "Acme Corp uses PostgreSQL"
```

### Custom Schemas

Extend the base schemas with typed fields for your domain:

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

# Use custom schema
learning = LearningMachine(
    user_profile=UserProfileConfig(
        schema=CustomerProfile,
    ),
)
```

## Learn More

- [Agno Documentation](https://docs.agno.com)

Built with 💜 by the Agno team
