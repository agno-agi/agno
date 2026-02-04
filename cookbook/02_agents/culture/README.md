# Shared, Collective Learning for Agents (aka Agentic Culture)

When humans learn a new skill or quality that will be useful in the future, we process, store and communicate it with each other via cultural artifacts. The consolidation of this shared knowledge, is the foundation of what we call culture.

With Agno, you can now give your Agents shared collective knowledge, that persists beyond individual memory, using our `Culture` service. This allows your Agents to learn from each other and build on each other's ideas over time.

## How Culture Works

`Culture` provides a shared space for Agents to think, write, and build on each other's ideas.

Unlike Memory, which stores user-specific information ("Sarah prefers email"), `Culture` stores universal knowledge that benefits all interactions ("Always provide actionable solutions with clear next steps").

Using `Culture`, your Agents will be able to transmit relevant learnings to each other and across time - similarly to how we transmit knowledge across generations.

> "Culture is how intelligence compounds"

## Agentic Culture

This is **v0.1** with the current goal of helping Agents stay consistent in tone, reasoning, and behavior. The eventual goal is to transform isolated agents into a living, evolving system of intelligence. These examples show how to:

- Create cultural knowledge using an Agent (or manually).
- Using cultural knowledge with Agents.
- Letting Agents automatically update and evolve shared culture over time.

Each recipe builds on the previous one, so you can run them in sequence.

---

## Examples in this folder

| File | Description |
|------|--------------|
| [01_create_cultural_knowledge.py](01_create_cultural_knowledge.py) | Create cultural knowledge using a model. |
| [02_use_cultural_knowledge_in_agent.py](02_use_cultural_knowledge_in_agent.py) | Use cultural knowledge inside Agents. |
| [03_automatic_cultural_management.py](03_automatic_cultural_management.py) | Let Agents autonomously update culture based on interactions. |
| [04_manually_add_culture.py](04_manually_add_culture.py) | Manually add cultural knowledge to your Agents. |
| [05_test_agent_with_cultural_knowledge.py](05_test_agent_with_cultural_knowledge.py) | Test and explore Agents with cultural knowledge enabled. |

---

## Quick Setup

1. Create and activate a virtual environment:
```shell
uv venv --python 3.12
source .venv/bin/activate
```

2. Install dependencies:
```shell
uv pip install agno anthropic sqlalchemy
```

3. Set your Anthropic API key: `export ANTHROPIC_API_KEY="sk-ant-..."`

4. Run any recipe
```shell
python cookbook/culture/01_create_cultural_knowledge.py
```

A local SQLite database (tmp/demo.db) will store and persist shared cultural knowledge across runs.

---

## File Overviews

#### 01_create_cultural_knowledge.py
Create cultural knowledge using the `CultureManager` and a model.
- Demonstrates how to feed insights or guiding principles to the system
- Persists cultural knowledge (e.g., *Operational Thinking*) into a shared SQLite DB
- Run this first to seed the knowledge base

Command: `python cookbook/culture/01_create_cultural_knowledge.py`

---

#### 02_use_cultural_knowledge_in_agent.py
Use existing cultural knowledge inside an Agent.
- Shows how to initialize an Agent with `add_culture_to_context=True`
- The Agent automatically loads shared culture and applies it during reasoning
- Demonstrates how cultural knowledge changes the tone and structure of responses


Command: `python cookbook/culture/02_use_cultural_knowledge_in_agent.py`

---

#### 03_automatic_cultural_management.py
Let your Agent autonomously update cultural knowledge.
- Enables `update_cultural_knowledge=True`
- After each run, the Agent reflects on its response and updates the shared culture
- Great for experiments where agents evolve their own principles over time

Command: `python cookbook/culture/03_automatic_cultural_management.py`

---

#### 04_manually_add_culture.py
Manually seed cultural knowledge without using a model.
- Adds reusable best practices directly via the `CulturalKnowledge` dataclass
- Useful for organization-wide rules, tone guides, or safety policies
- Combines manual seeding with running an Agent that benefits from it

Command: `python cookbook/culture/04_manually_add_culture.py`

---

#### 05_test_agent_with_cultural_knowledge.py
Freestyle test file — interact with an Agent that has culture enabled.
- Use this file to test arbitrary prompts and observe cultural influence
- The Agent both *reads* and (optionally) *updates* shared cultural knowledge

Command: `python cookbook/culture/05_test_agent_with_cultural_knowledge.py`

---

## Future Features to Explore

- Integrate culture into your multi-agent teams (Teams API)
- Use `CultureManager` programmatically to sync or version cultural knowledge
- Store culture in a centralized backend (Postgres, Redis, or your own store)
- Experiment with multiple Agents that evolve shared norms together

---
