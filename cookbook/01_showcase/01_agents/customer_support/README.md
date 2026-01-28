# Customer Support Agent

A support agent that learns from successful resolutions and applies them to future tickets using Learning Machine.

## What You'll Learn

| Concept | Description |
|:--------|:------------|
| **Cross-Ticket Learning** | Agent saves successful solutions, finds them for similar issues |
| **Learning Machine** | Unified learning system with entity memory and learned knowledge |
| **Knowledge Search** | RAG pattern with automatic KB search |
| **Human-in-the-Loop** | Pausing for clarification on ambiguous queries |

## Quick Start

### 1. Set API Keys

```bash
export OPENAI_API_KEY=your-openai-api-key
```

### 2. Start PostgreSQL

```bash
./cookbook/scripts/run_pgvector.sh
```

### 3. Load Knowledge Base

```bash
.venvs/demo/bin/python cookbook/01_showcase/01_agents/customer_support/scripts/load_knowledge.py
```

### 4. Run an Example

```bash
.venvs/demo/bin/python cookbook/01_showcase/01_agents/customer_support/examples/learning_demo.py
```

## Examples

| File | What You'll Learn |
|:-----|:------------------|
| `examples/simple_query.py` | Basic KB-powered query |
| `examples/learning_demo.py` | Learning transfer between tickets |
| `examples/hitl_demo.py` | Human-in-the-loop clarification |
| `examples/evaluate.py` | Multi-query evaluation |

## Architecture

```
customer_support/
├── agent.py              # Support agent with Learning Machine
├── examples/
│   ├── simple_query.py
│   ├── learning_demo.py
│   ├── evaluate.py
│   └── hitl_demo.py
├── knowledge/            # KB documents
└── scripts/              # Setup utilities
```

## Key Concepts

### Cross-Ticket Learning

The agent learns from confirmed solutions and transfers that knowledge:

```
Ticket 1: Customer reports login issue
  → Agent suggests clearing cache
  → Customer confirms: "That worked!"
  → Agent saves learning

Ticket 2: Different customer, similar issue
  → Agent finds prior solution
  → Responds: "This has worked before..."
```

### Agent Configuration

The agent uses a minimal configuration following the gold standard pattern:

```python
from agno.agent import Agent
from agno.learn import (
    EntityMemoryConfig,
    LearnedKnowledgeConfig,
    LearningMachine,
    LearningMode,
    SessionContextConfig,
)

agent = Agent(
    model=OpenAIResponses(id="gpt-4.1"),
    db=db,
    instructions=(
        "You are a helpful support agent. "
        "Check if similar issues have been solved before. "
        "Save successful solutions for future reference."
    ),
    learning=LearningMachine(
        knowledge=knowledge,
        session_context=SessionContextConfig(enable_planning=True),
        entity_memory=EntityMemoryConfig(
            mode=LearningMode.ALWAYS,
            namespace="support",
        ),
        learned_knowledge=LearnedKnowledgeConfig(mode=LearningMode.AGENTIC),
    ),
    user_id=customer_id,
    session_id=ticket_id,
    search_knowledge=True,
    markdown=True,
)
```

### Knowledge Base

| Document | Content |
|:---------|:--------|
| `ticket_triage.md` | Priority classification workflow |
| `escalation_guidelines.md` | When to escalate and to whom |
| `response_templates.md` | Empathy statements and response structures |
| `sla_guidelines.md` | Response time targets by priority |

## Troubleshooting

### PostgreSQL Connection Failed

```bash
./cookbook/scripts/run_pgvector.sh
```

### Knowledge Base Empty

```bash
.venvs/demo/bin/python cookbook/01_showcase/01_agents/customer_support/scripts/load_knowledge.py
```

## Dependencies

- `agno` - Core framework
- `openai` - GPT model and embeddings
- `psycopg[binary]` - PostgreSQL driver
- `pgvector` - Vector extension

## See Also

- [Learning Machine Cookbook](../../../08_learning/) - Deep dive into learning patterns
- [Learning Machine Patterns](../../../08_learning/07_patterns/support_agent.py) - Gold standard pattern
