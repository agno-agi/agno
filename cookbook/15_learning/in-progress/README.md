# Learning Machine Cookbook

A comprehensive guide to building agents that learn, remember, and improve.

## Overview

LearningMachine is a unified learning system that enables agents to learn from every interaction. It coordinates multiple **learning stores**, each handling a different type of knowledge:

| Store | What It Captures | Scope | Use Case |
|-------|------------------|-------|----------|
| **User Profile** | Preferences, memories, style | Per user | Personalization |
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
model = OpenAIResponses(id="gpt-5.2")

# The simplest learning agent
agent = Agent(
    model=model,
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

### 📁 basics/
Quick-start examples (~30 lines each):
- `01_hello_learning.py` - Minimal working example
- `02_user_profile_quick.py` - User memory basics
- `03_session_context_quick.py` - Session state basics
- `04_entity_memory_quick.py` - Entity tracking basics
- `05_learned_knowledge_quick.py` - Knowledge capture basics

### 📁 user_profile/
Deep dive into user memory:
- `01_background_extraction.py` - Automatic profile extraction
- `02_agentic_mode.py` - Agent-controlled memory
- `03_custom_schema.py` - Extend profiles with custom fields
- `04_memory_vs_fields.py` - When to use each
- `05_memory_operations.py` - Add, update, delete lifecycle

### 📁 session_context/
Deep dive into session tracking:
- `01_summary_mode.py` - Basic conversation summaries
- `02_planning_mode.py` - Goal → Plan → Progress tracking
- `03_context_continuity.py` - Building on previous context
- `04_long_conversations.py` - Handling context limits

### 📁 entity_memory/
Deep dive into entity knowledge:
- `01_facts_and_events.py` - Semantic vs episodic memory
- `02_entity_relationships.py` - Graph edges between entities
- `03_namespace_sharing.py` - Private vs shared entities
- `04_background_extraction.py` - Auto-extract entities
- `05_entity_search.py` - Query the entity database

### 📁 learned_knowledge/
Deep dive into knowledge capture:
- `01_agentic_mode.py` - Agent decides what to save
- `02_propose_mode.py` - Human approval workflow
- `03_background_extraction.py` - Auto-extract insights
- `04_search_and_apply.py` - Use learnings in responses
- `05_namespace_scoping.py` - Sharing boundaries

### 📁 combined/
Multiple stores working together:
- `01_user_plus_session.py` - Profile + session context
- `02_user_plus_entities.py` - Profile + entity memory
- `03_full_learning_machine.py` - All stores enabled
- `04_learning_machine_builder.py` - Configuration patterns

### 📁 patterns/
Real-world agent implementations:
- `support_agent.py` - Customer support with memory
- `research_agent.py` - Research with knowledge capture
- `coding_assistant.py` - Developer assistant
- `personal_assistant.py` - Personal memory and tasks
- `sales_agent.py` - CRM-aware sales assistant
- `team_knowledge_agent.py` - Shared team knowledge
- `onboarding_agent.py` - New hire assistant

### 📁 advanced/
Power user features:
- `01_multi_user.py` - Multi-user data scoping
- `02_curator_maintenance.py` - Prune and deduplicate
- `03_extraction_timing.py` - Before vs after extraction
- `04_custom_store.py` - Build your own store
- `05_async_patterns.py` - Async operations
- `06_debugging.py` - Troubleshooting techniques

### 📁 production/
Production-ready patterns:
- `gpu_poor_learning.py` - Cost-optimized learning
- `plan_and_learn.py` - Strategic task execution

## Learning Modes

```python
from agno.learn import LearningMode

# BACKGROUND (default for user_profile, session_context)
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

## Namespace Scoping

```python
# Private per user
LearnedKnowledgeConfig(namespace="user")

# Shared with everyone
LearnedKnowledgeConfig(namespace="global")  # default

# Team isolation
LearnedKnowledgeConfig(namespace="engineering")
LearnedKnowledgeConfig(namespace="sales")
```

## Three DX Levels

```python
# Level 1: Dead Simple
agent = Agent(model=model, db=db, learning=True)

# Level 2: Pick What You Want
agent = Agent(
    model=model,
    db=db,
    learning=LearningMachine(
        db=db,
        model=model,
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
        db=db,
        model=model,
        user_profile=UserProfileConfig(
            mode=LearningMode.AGENTIC,
            enable_agent_tools=True,
        ),
        session_context=SessionContextConfig(
            enable_planning=True,
        ),
    ),
)
```

## Running the Examples

```bash
# Ensure PostgreSQL is running
docker compose up -d

# Run any example
python cookbook/15_learning/basics/01_hello_learning.py

# Run with AgentOS
python cookbook/15_learning/run.py
# Then visit https://os.agno.com and add http://localhost:7777
```

## Key Concepts

### The Goal
An agent on interaction 1000 is fundamentally better than it was on interaction 1.

### The Advantage
Instead of configuring memory, knowledge, and feedback separately, configure one system that handles all learning with consistent patterns.

### The Protocol
All stores implement `LearningStore`:
- `recall()` - Retrieve learnings
- `process()` - Extract and save learnings
- `build_context()` - Format for system prompt
- `get_tools()` - Agent tools

## Next Steps

1. Start with `basics/01_hello_learning.py`
2. Pick the store that matches your use case
3. Read the deep-dive for that store
4. Check `patterns/` for real-world examples
5. See `advanced/` for production optimizations
