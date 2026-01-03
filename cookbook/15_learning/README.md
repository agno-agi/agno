# LearningMachine Cookbooks

Build agents that remember, adapt, and improve over time.

---

## What is LearningMachine?

`LearningMachine` is a unified learning system that gives agents persistent memory across three dimensions:

```
LearningMachine
├── User Profile        → "Alice is a data scientist who prefers concise answers"
├── Session Context     → "We're building a REST API, completed steps 1-3"
└── Learned Knowledge   → "For ETF comparisons, always check expense ratio AND tracking error"
```

| Learning Type | What It Captures | Scope | Retrieval |
|:--------------|:-----------------|:------|:----------|
| **User Profile** | Preferences, facts, context | Per user | `user_id` lookup |
| **Session Context** | Summary, goals, progress | Per session | `session_id` lookup |
| **Learned Knowledge** | Insights, patterns, best practices | Shared | Semantic search |

**The Goal:** An agent on interaction 1000 is fundamentally better than it was on interaction 1.

---

## Cookbooks

### Tier 1: Getting Started

*Foundation — from zero to all three learning types*

| # | File | What You'll Learn |
|:--|:-----|:------------------|
| 01 | `01_user_profile.py` | Simplest setup — `learning=True` enables automatic user memory |
| 02 | `02_user_profile_agentic.py` | Agent decides when to save via `update_user_memory` tool |
| 03 | `03_session_context.py` | Session summaries for conversation continuity |
| 04 | `04_session_context_planning.py` | Planning mode with goal/plan/progress tracking |
| 05 | `05_learned_knowledge.py` | Shared insights with semantic search |

### Tier 2: Control & Modes

*Understanding how to control learning behavior*

| # | File | What You'll Learn |
|:--|:-----|:------------------|
| 06 | `06_learning_modes.py` | BACKGROUND vs AGENTIC vs PROPOSE comparison |
| 07 | `07_propose_mode.py` | Human-in-the-loop — agent proposes, user confirms |

### Tier 3: Agent Archetypes

*Real agents you can adapt for your use case*

| # | File | Agent Type | Key Pattern |
|:--|:-----|:-----------|:------------|
| 08 | `08_support_agent.py` | Customer Support | Issue memory, resolution patterns |
| 09 | `09_research_agent.py` | Research Assistant | Web search + learns research patterns |
| 10 | `10_coding_assistant.py` | Coding Helper | Code style, project patterns |
| 11 | `11_personal_assistant.py` | Personal AI | Deep preference learning |
| 12 | `12_team_knowledge.py` | Team Brain | Shared learnings, individual profiles |

### Tier 4: Production Patterns

*Building for real users*

| # | File | What You'll Learn |
|:--|:-----|:------------------|
| 13 | `13_multi_user.py` | User isolation — no memory leakage between users |
| 14 | `14_gpu_poor_learning.py` | Cheap models for extraction, expensive for responses |
| 15 | `15_custom_schema.py` | Your own profile/context data structures |
| 16 | `16_debugging.py` | Inspect stored data, troubleshoot issues |

### Tier 5: Advanced

*Maximum intelligence*

| # | File | What You'll Learn |
|:--|:-----|:------------------|
| 17 | `17_custom_store.py` | Build your own learning type |
| 18 | `18_continuous_learning.py` | Agent improves with every interaction |
| 19 | `19_plan_and_learn.py` | PaL pattern — plan, execute, learn from outcomes |
| 20 | `20_full_production.py` | Complete production agent with all patterns |

---

## Learning Paths

### "I just want it to work"
```
01_user_profile.py → 05_learned_knowledge.py → 09_research_agent.py
```

### "I want to understand the system"
```
01 → 02 → 03 → 04 → 05 → 06 → 07
```

### "I'm building a specific agent type"
```
01 → 05 → Pick from 08-12 (closest to your use case)
```

### "I'm going to production"
```
01 → 05 → 13 → 14 → 16 → 20
```

### "I want maximum agent intelligence"
```
01 → 05 → 06 → 17 → 18 → 19
```

---

## Quick Start

### 1. Start PostgreSQL with pgvector

```bash
docker run -d \
  --name pgvector \
  -e POSTGRES_USER=ai \
  -e POSTGRES_PASSWORD=ai \
  -e POSTGRES_DB=ai \
  -p 5532:5432 \
  pgvector/pgvector:pg17
```

### 2. Install dependencies

```bash
pip install agno psycopg[binary] pgvector openai
```

### 3. Set your API key

```bash
export OPENAI_API_KEY=your-key-here
```

### 4. Run your first cookbook

```bash
python 01_user_profile.py
```

---

## The Simplest Agent with Learning

```python
from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    db=PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai"),
    learning=True,  # That's it!
)

# Agent now remembers users across sessions
agent.print_response("I'm Alice, a data scientist at Netflix", user_id="alice")
agent.print_response("What do you know about me?", user_id="alice")  # Remembers!
```

---

## Three Levels of Control

### Level 1: Dead Simple

```python
agent = Agent(
    model=model,
    db=db,
    learning=True,  # Enables UserProfile in BACKGROUND mode
)
```

### Level 2: Pick What You Want

```python
agent = Agent(
    model=model,
    db=db,
    learning=LearningMachine(
        db=db,
        model=model,
        knowledge=my_kb,           # Enables LearnedKnowledge
        user_profile=True,         # Enabled by default
        session_context=True,      # Opt-in
    ),
)
```

### Level 3: Full Control

```python
agent = Agent(
    model=model,
    db=db,
    learning=LearningMachine(
        db=db,
        model=model,
        knowledge=my_kb,
        user_profile=UserProfileConfig(
            mode=LearningMode.AGENTIC,
            enable_tool=True,
        ),
        session_context=SessionContextConfig(
            enable_planning=True,
        ),
        learned_knowledge=LearnedKnowledgeConfig(
            mode=LearningMode.PROPOSE,
        ),
    ),
)
```

---

## Learning Modes

| Mode | How It Works | Best For |
|:-----|:-------------|:---------|
| **BACKGROUND** | Automatic extraction after each response | User profiles, session summaries |
| **AGENTIC** | Agent decides via tools when to save | Learnings, agent-controlled memory |
| **PROPOSE** | Agent proposes, user confirms before saving | High-value insights, quality control |

---

## Key Concepts

| Concept | What It Does |
|:--------|:-------------|
| **LearningMachine** | Coordinates all learning stores — the main entry point |
| **UserProfileStore** | Per-user memory that persists across sessions |
| **SessionContextStore** | Per-session state, optionally with planning |
| **LearnedKnowledgeStore** | Shared insights searchable via semantic similarity |
| **`build_context()`** | Get memory to inject into system prompt |
| **`process()`** | Extract and save learnings after conversation |
| **`get_tools()`** | Get learning tools for the agent |

---

## Data Scoping

Each store has a clear lookup key. `agent_id` and `team_id` are stored for audit only, never for filtering:

| Store | Lookup Key | Scope |
|:------|:-----------|:------|
| UserProfileStore | `user_id` | Per user (shared across agents) |
| SessionContextStore | `session_id` | Per session |
| LearnedKnowledgeStore | Semantic search | Shared (all agents see all learnings) |

For team isolation, use separate knowledge bases — not store-level filtering.

---

## File Structure

```
cookbooks/
├── 01_user_profile.py              # Simplest setup
├── 02_user_profile_agentic.py      # Agent-controlled memory
├── 03_session_context.py           # Session summaries
├── 04_session_context_planning.py  # Goal/plan/progress tracking
├── 05_learned_knowledge.py         # Shared insights
├── 06_learning_modes.py            # Mode comparison
├── 07_propose_mode.py              # Human-in-the-loop
├── 08_support_agent.py             # Customer support archetype
├── 09_research_agent.py            # Research assistant archetype
├── 10_coding_assistant.py          # Coding helper archetype
├── 11_personal_assistant.py        # Personal AI archetype
├── 12_team_knowledge.py            # Team brain archetype
├── 13_multi_user.py                # User isolation
├── 14_gpu_poor_learning.py         # Cost optimization
├── 15_custom_schema.py             # Custom data structures
├── 16_debugging.py                 # Inspection and troubleshooting
├── 17_custom_store.py              # Build your own learning type
├── 18_continuous_learning.py       # Self-improving agent
├── 19_plan_and_learn.py            # PaL pattern
├── 20_full_production.py           # Complete production agent
└── README.md
```

---

## Learn More

- [Agno Documentation](https://docs.agno.com)

---

Built with 💜 by the Agno team
