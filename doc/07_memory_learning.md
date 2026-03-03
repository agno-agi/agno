# Memory & Learning System

Agno provides two distinct systems for agent memory:

| System | Purpose |
|--------|---------|
| `MemoryManager` | Store and recall specific facts across sessions |
| `LearningMachine` | Continuously learn from interactions (6 learning types) |

---

## MemoryManager

**File:** `libs/agno/agno/memory/manager.py` (61KB)

`MemoryManager` lets agents persist and recall facts about users across multiple sessions. Memories are extracted from conversations by an LLM and stored in the database.

### Basic setup

```python
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.memory import MemoryManager
from agno.db.postgres import PostgresDb

memory = MemoryManager(
    model=OpenAIChat(id="gpt-4o-mini"),  # model used to extract memories
    db=PostgresDb(
        table_name="user_memories",
        db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
    ),
)

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    memory=memory,
    enable_agentic_memory=True,   # agent updates memories during conversation
    user_id="alice",              # memories are scoped to this user
)

agent.print_response("My name is Alice and I prefer formal communication.")
agent.print_response("I live in Berlin.")

# In a later session (new process):
agent2 = Agent(
    model=OpenAIChat(id="gpt-4o"),
    memory=memory,
    user_id="alice",              # same user_id loads Alice's memories
)
agent2.print_response("Where do I live?")
# Agent recalls: "Berlin"
```

### Memory features

- **Automatic extraction** — LLM reads conversation and extracts memorable facts
- **Semantic search** — memories are retrieved by relevance to the current query
- **Token-aware** — only the most relevant memories are injected (stays within context limit)
- **Cross-session** — memories persist between separate agent runs
- **User-scoped** — each `user_id` has isolated memory

### Memory operations

```python
# Add a memory manually
memory.add_memory(user_id="alice", content="Alice is allergic to shellfish.")

# Search memories
results = memory.search(user_id="alice", query="dietary restrictions")

# Clear all memories for a user
memory.clear(user_id="alice")
```

### Memory optimization strategies

For long-lived agents with many memories:

```python
from agno.memory.strategy import SummarizeStrategy

memory = MemoryManager(
    db=db,
    optimization_strategy=SummarizeStrategy(
        model=OpenAIChat(id="gpt-4o-mini"),
        max_memories=50,    # summarise when > 50 memories exist
    ),
)
```

---

## LearningMachine

**Directory:** `libs/agno/agno/learn/`
**File:** `libs/agno/agno/learn/machine.py` (40KB)

The `LearningMachine` is a higher-level system for **continuous agent improvement**. It tracks 6 types of learning and stores them in dedicated persistent stores.

### 6 learning types

| Type | What it captures | Example |
|------|-----------------|---------|
| `UserProfile` | Who the user is — preferences, characteristics, role | "Alice is a senior engineer who prefers concise answers" |
| `Memory` | Explicit facts to remember | "Project deadline is March 15" |
| `EntityMemory` | Facts about specific entities (people, companies, products) | "Acme Corp has 500 employees, CTO is Bob" |
| `SessionContext` | Important context from the current session | "We are discussing the Q1 marketing budget" |
| `LearnedKnowledge` | New knowledge to add to the knowledge base | Domain knowledge discovered during conversation |
| `DecisionLog` | Track and learn from decisions made | "Chose Option A because of X, Y, Z" |

### Basic setup

```python
from agno.learn import LearningMachine
from agno.learn.config import (
    UserProfileConfig,
    MemoryConfig,
    EntityMemoryConfig,
    SessionContextConfig,
    LearnedKnowledgeConfig,
    DecisionLogConfig,
)
from agno.db.postgres import PostgresDb
from agno.agent import Agent
from agno.models.openai import OpenAIChat

DB_URL = "postgresql+psycopg://ai:ai@localhost:5532/ai"

learning_machine = LearningMachine(
    model=OpenAIChat(id="gpt-4o-mini"),
    # Enable the learning types you need:
    user_profile=UserProfileConfig(
        db=PostgresDb(table_name="user_profiles", db_url=DB_URL),
    ),
    memory=MemoryConfig(
        db=PostgresDb(table_name="agent_memories", db_url=DB_URL),
    ),
    entity_memory=EntityMemoryConfig(
        db=PostgresDb(table_name="entity_memories", db_url=DB_URL),
    ),
    decision_log=DecisionLogConfig(
        db=PostgresDb(table_name="decision_logs", db_url=DB_URL),
    ),
)

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    learning_machine=learning_machine,
    user_id="alice",
)
```

### UserProfile — learn who the user is

```python
from agno.learn.config import UserProfileConfig

user_profile_config = UserProfileConfig(
    db=PostgresDb(table_name="user_profiles", db_url=DB_URL),
    capture_instructions="Track user's role, expertise level, preferences, and communication style.",
)
```

The agent builds a growing profile of each user. In subsequent sessions, it injects the profile into the system prompt to personalise responses.

### EntityMemory — learn about entities

```python
from agno.learn.config import EntityMemoryConfig

entity_config = EntityMemoryConfig(
    db=PostgresDb(table_name="entity_memories", db_url=DB_URL),
    entity_types=["company", "person", "product"],
)
```

When the agent mentions a company or person, it extracts and stores facts about them. Future conversations about the same entity benefit from this accumulated knowledge.

### DecisionLog — learn from decisions

```python
from agno.learn.config import DecisionLogConfig

decision_config = DecisionLogConfig(
    db=PostgresDb(table_name="decisions", db_url=DB_URL),
    capture_rationale=True,  # log the reasoning behind each decision
)
```

Tracks what decisions were made and why. Useful for agents that advise on recurring decisions (procurement, hiring, architecture choices).

### SessionContext — capture session-level context

```python
from agno.learn.config import SessionContextConfig

session_config = SessionContextConfig(
    db=PostgresDb(table_name="session_context", db_url=DB_URL),
)
```

Captures important context from each session (e.g., "working on Q1 budget review") to improve continuity in follow-up sessions.

### LearnedKnowledge — add to knowledge base

```python
from agno.learn.config import LearnedKnowledgeConfig

knowledge_config = LearnedKnowledgeConfig(
    db=PostgresDb(table_name="learned_knowledge", db_url=DB_URL),
    knowledge_base=my_knowledge,  # will add newly learned facts here
)
```

When the agent discovers domain knowledge in conversation, it adds it to the knowledge base so future queries benefit from it.

---

## Full example: agent that learns over time

```python
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.learn import LearningMachine
from agno.learn.config import UserProfileConfig, MemoryConfig, EntityMemoryConfig
from agno.db.postgres import PostgresDb

DB_URL = "postgresql+psycopg://ai:ai@localhost:5532/ai"

lm = LearningMachine(
    model=OpenAIChat(id="gpt-4o-mini"),
    user_profile=UserProfileConfig(
        db=PostgresDb(table_name="profiles", db_url=DB_URL),
    ),
    memory=MemoryConfig(
        db=PostgresDb(table_name="memories", db_url=DB_URL),
    ),
    entity_memory=EntityMemoryConfig(
        db=PostgresDb(table_name="entities", db_url=DB_URL),
    ),
)

advisor = Agent(
    name="Investment Advisor",
    model=OpenAIChat(id="gpt-4o"),
    learning_machine=lm,
    user_id="alice",
    instructions=[
        "You are a personalised investment advisor.",
        "Use what you know about the user to tailor your advice.",
    ],
)

# Session 1
advisor.print_response("I'm 35, have $50k to invest, moderate risk tolerance.")
# LearningMachine stores: age=35, capital=$50k, risk=moderate

# Session 2 (later, new process)
advisor.print_response("Should I invest more in equities now?")
# Agent recalls profile: "Alice, 35, moderate risk, $50k" — advises accordingly
```

---

## MemoryManager vs LearningMachine

| | MemoryManager | LearningMachine |
|--|--------------|-----------------|
| **Scope** | Simple facts per user | 6 structured learning types |
| **Storage** | Single table | One table per learning type |
| **Granularity** | Key-value memories | Typed schemas (UserProfile, Entity, etc.) |
| **Use case** | "Remember what I said" | Continuous agent improvement |
| **Complexity** | Low | Medium-high |

**Start with `MemoryManager`** if you want agents to remember things users tell them.
**Use `LearningMachine`** if you want agents to actively improve their model of users, entities, and decisions over time.

---

## Session history (conversation memory)

Separate from both systems above — session history is the short-term chat history within and across sessions:

```python
agent = Agent(
    model=...,
    db=PostgresDb(table_name="sessions", db_url=DB_URL),
    add_history_to_messages=True,    # inject past messages into context
    num_history_runs=10,             # how many past runs to include
    create_session_summary=True,     # auto-summarise long sessions
)
```

This is cheaper than injecting full history — summaries keep context compact.
