# Memory Part 2: The Learning Machine

Learning Machine is a unified learning system that gives agents the ability to remember, adapt, and improve. It coordinates multiple learning stores that work together:

```
Learning Stores
├── User Profile         — Long-term memory about users, accumulated over time
├── Session Context      — State, summary, goal, plan, progress for the current session
├── Learned Knowledge    — Reusable insights and patterns
├── Entity Memory        — Facts, events and relationships about entities
└── Not yet implemented
    ├── Decision Logs        — Why decisions were made
    ├── Behavioral Feedback  — What worked, what didn't
    └── Self-Improvement     — Continuously improving instructions
```

**The Goal:** An agent on interaction 1000 is fundamentally better than it was on interaction 1.

**The Advantage:** Instead of building memory, knowledge, and feedback systems separately, developers configure one system that handles all learning with consistent patterns for storage, retrieval, and lifecycle.

Learning Stores can be configured to run in:
- Background mode: Automatically extract from conversations without interrupting the agent.
- Agentic mode: Agent calls tools directly to save information to the learning store.
- Propose mode: Agent proposes in chat, user approves before saving.
- Human-in-the-loop mode: Explicit human approval required using user control flows.

## What You'll Build

This cookbook contains **35 examples** across 9 categories:

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
└── production/                # Production-ready examples (3 examples)
```

**Progressive complexity**: Start with `basics/`, master one learning store, combine them, then build production agents.

## Built-in Learning Stores

### 1. User Profile Store

User Profile Store captures long-term memory about users. Persists forever. Accumulates over time. Can be run in background mode or agentic mode.

**Two types of data can be captured:**
- **Profile fields** (structured): name, preferred_name, custom fields you define.
- **Memories** (unstructured): observations that don't fit fields.

Quick example:

```python
from agno.agent import Agent
from agno.learn import LearningMachine, UserProfileConfig

agent = Agent(
    db=db,
    model=model,
    learning=LearningMachine(
        # Automatically extract user profile information in parallel
        user_profile=UserProfileConfig(
            mode=LearningMode.BACKGROUND,
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

Session Context Store captures state and summary for the current session. Updated (not accumulated) on each extraction. Can be run in background mode, agentic mode, or propose mode.

**Three types of data can be captured:**
- **Summary** (text): A brief summary of the current session.
- **Goal** (text): The goal of the current session.
- **Plan** (list of text): The plan for the current session.
- **Progress** (list of text): The progress of the current session.

**Key behavior**: Builds on previous context. Even if message history is truncated, the context persists.

Quick example:

```python
from agno.agent import Agent
from agno.learn import LearningMachine, SessionContextConfig

agent = Agent(
    db=db,
    model=model,
    learning=LearningMachine(
        # Track goal, plan, progress.
        # Only recommended for certain types of agents. Will add lots of latency.
        session_context=SessionContextConfig(
            enable_planning=True,
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

### 4. Learned Knowledge Store

Learned Knowledge Store captures reusable insights, patterns, and rules that apply across users and sessions. Stored in a vector database for semantic search. Can be run in agentic mode or propose mode. Best used for self-improving agents, research agents, or any agent that should get smarter over time.

```python
from agno.learn import LearningMachine, LearnedKnowledgeConfig, LearningMode
from agno.knowledge import Knowledge
from agno.vectordb.pgvector import PgVector

# Vector DB for semantic search
knowledge_base = Knowledge(
    vector_db=PgVector(
        db_url=db_url,
        table_name="agent_learnings",
    ),
)

agent = Agent(
    db=db,
    model=model,
    learning=LearningMachine(
        # Knowledge base for storing learnings
        knowledge=knowledge_base,
        learned_knowledge=LearnedKnowledgeConfig(
            # Agent decides when to save.
            mode=LearningMode.AGENTIC,
        ),
    ),
)

# Agent discovers an insight and saves it
agent.run("When comparing cloud providers, always check egress costs first")

# Later, different user, agent searches and applies prior learnings
agent.run("Help me compare AWS vs GCP")
# Agent searches knowledge base, finds the egress insight, applies it
```

### 3. Entity Memory Store

Entity Memory Store captures knowledge about external entities: companies, projects, people, products, systems. Can be run in background mode or agentic mode.

```python
from agno.learn import LearningMachine, EntityMemoryConfig

agent = Agent(
    db=db,
    model=model,
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

**Three types of entity data:**
- **Facts** (semantic memory): Timeless truths — "Uses PostgreSQL"
- **Events** (episodic memory): Time-bound occurrences — "Launched v2 on Jan 15"
- **Relationships** (graph edges): Connections — "Bob is CTO of Acme"

**When to use**: CRM-style agents, research agents, any agent that tracks external things. Best used for agents that need to know about external entities.


## Getting Started

### 1. Clone the repo

```bash
git clone https://github.com/agno-agi/agno.git
cd agno
```

### 2. Create a virtual environment and install dependencies

> `uv` must be installed.

```bash
./cookbook/15_learning/venv_setup.sh
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

### 5. Run Cookbook Examples Individually

```bash
python cookbook/15_learning/basics/01_hello_learning.py
```

### 6. Run the Agent OS

Agno provides a web interface for interacting with agents. Start the server:

```bash
python cookbook/15_learning/run.py
```

Then visit [os.agno.com](https://os.agno.com/?utm_source=github&utm_medium=cookbook&utm_campaign=gemini&utm_content=cookbook-gemini-flash&utm_term=gemini-flash) and add `http://localhost:7777` as an endpoint.

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
├── basics/                             # Start here
│   ├── 01_hello_learning.py            # Minimal working example
│   ├── 02_user_profile_quick.py        # User memory in 30 lines
│   ├── 03_session_context_quick.py     # Session state in 30 lines
│   ├── 04_entity_memory_quick.py       # Entity tracking in 30 lines
│   └── 05_learned_knowledge_quick.py   # Knowledge capture in 30 lines
│
├── user_profile/                       # User memory deep dive
│   ├── 01_background_extraction.py     # Automatic extraction
│   ├── 02_agentic_mode.py              # Agent-driven updates
│   ├── 03_custom_schema.py             # Extend with typed fields
│   ├── 04_memory_vs_fields.py          # When to use which
│   └── 05_memory_operations.py         # Add/update/delete flow
│
├── session_context/                    # Session state deep dive
│   ├── 01_summary_mode.py              # Basic summarization
│   ├── 02_planning_mode.py             # Goal → Plan → Progress
│   ├── 03_context_continuity.py        # Building on previous
│   └── 04_long_conversations.py        # Handling truncation
│
├── entity_memory/                      # Entity knowledge deep dive
│   ├── 01_facts_and_events.py          # Semantic vs episodic
│   ├── 02_entity_relationships.py      # Graph edges
│   ├── 03_namespace_sharing.py         # Sharing boundaries
│   ├── 04_background_extraction.py     # Auto-extract entities
│   └── 05_entity_search.py             # Finding entities
│
├── learned_knowledge/                  # Reusable insights deep dive
│   ├── 01_agentic_mode.py              # Agent saves directly
│   ├── 02_propose_mode.py              # Human approval
│   ├── 03_background_extraction.py     # Auto-extract
│   ├── 04_search_and_apply.py          # Using prior learnings
│   └── 05_namespace_scoping.py         # Private vs shared
│
├── combined/                           # Multiple types together
│   ├── 01_user_plus_session.py         # Profile + session
│   ├── 02_user_plus_entities.py        # Profile + entities
│   ├── 03_full_learning_machine.py     # All four types
│   └── 04_learning_machine_builder.py  # Factory patterns
│
├── patterns/                           # Real-world agents
│   ├── support_agent.py                # Customer support
│   ├── research_agent.py               # Self-improving researcher
│   ├── coding_assistant.py             # Developer helper
│   ├── personal_assistant.py           # Long-term personal AI
│   ├── sales_agent.py                  # CRM-style tracking
│   ├── team_knowledge_agent.py         # Shared team learnings
│   └── onboarding_agent.py             # New user onboarding
│
├── advanced/                           # Power user features
│   ├── 01_multi_user.py                # Multiple users
│   ├── 02_curator_maintenance.py       # Pruning + dedup
│   ├── 03_extraction_timing.py         # Before/parallel/after
│   ├── 04_custom_store.py              # Implement your own
│   ├── 05_async_patterns.py            # Full async
│   └── 06_debugging.py                 # Debug mode
│
└── production/                         # Production-ready
    ├── gpu_poor_learning.py            # System-level learning
    ├── plan_and_learn.py               # PaL with LearningMachine
    └── full_production_agent.py        # Complete setup
```

## Best Practices

### 1. Start simple

Don't enable all four learning types at once. Start with `user_profile=True`, then add others as needed.

### 2. Use the right mode

- **BACKGROUND** for things you always want to capture (user info, session state)
- **AGENTIC** for things the agent should decide (insights, learnings)
- **PROPOSE** when you want human oversight

### 3. Namespace thoughtfully

- `"user"` for personal/private data
- `"global"` for shared knowledge
- Custom namespaces for teams or projects

### 4. Maintain your memories

Run the Curator periodically to prune old data and deduplicate.

### 5. Custom schemas for production

Extend the base schemas with typed fields for your domain. The LLM will understand and use them.

```python
from dataclasses import dataclass, field
from typing import Optional
from agno.learn.schemas import UserProfile

@dataclass
class MyUserProfile(UserProfile):
    """Extended user profile with custom fields."""

    company: Optional[str] = field(
        default=None,
        metadata={"description": "Company or organization"}
    )
    role: Optional[str] = field(
        default=None,
        metadata={"description": "Job title or role"}
    )
    timezone: Optional[str] = field(
        default=None,
        metadata={"description": "User's timezone"}
    )
    expertise_level: Optional[str] = field(
        default=None,
        metadata={"description": "beginner | intermediate | expert"}
    )

# Use your custom schema
learning = LearningMachine(
    db=db,
    model=model,
    user_profile=UserProfileConfig(
        schema=MyUserProfile,
    ),
)
```

The LLM sees field descriptions and updates them appropriately.

## Learn More

- [Agno Documentation](https://docs.agno.com)
- [LearningMachine Reference](https://docs.agno.com/learn)

