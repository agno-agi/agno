# Memory V2

Memory V2 provides persistent user memory that allows agents and teams to learn about users across conversations.

## Key Concepts

### Memory Layers

Memory V2 stores four types of information:

| Layer | Description | Example |
|-------|-------------|---------|
| **Profile** | User identity info | name, company, role, location |
| **Knowledge** | Personal facts | interests, hobbies, tech stack |
| **Policies** | Behavior rules | "be concise", "no emojis", "include code examples" |
| **Feedback** | Response quality | what explanations worked well or poorly |

### Two Modes of Operation

**1. Automatic Learning (`update_memory_on_run=True`)**

The agent passively extracts information from conversations:

```python
agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    db=SqliteDb(db_file="memory.db"),
    update_memory_on_run=True,
)
```

**2. Agentic Memory (`enable_agentic_memory_v2=True`)**

The agent gets explicit tools to save/delete memory:

```python
agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    db=SqliteDb(db_file="memory.db"),
    enable_agentic_memory_v2=True,
)
```

With this mode, users can say things like:
- "Remember that I prefer Python over JavaScript"
- "Forget my workplace details"
- "Update my role - I'm now a Staff Engineer"

## Examples

| Example | Description |
|---------|-------------|
| `01_basic.py` | Agentic memory with save/delete tools |
| `02_update_on_run.py` | Automatic extraction without explicit tools |
| `03_agentic_memory.py` | Explicit memory management via natural language |
| `04_advanced_customization.py` | Custom extraction instructions |
| `05_async_memory.py` | Async support with concurrent users |
| `06_agents_share_memory.py` | Multiple agents sharing memory |
| `07_multi_user.py` | Single agent with per-user memory |

## Viewing Stored Memory

```python
# Get user memory
memory = agent.get_user_memory_v2(user_id)
if memory:
    print(memory.to_dict())
```

## Custom Extraction Instructions

```python
from agno.memory_v2 import MemoryCompiler

memory = MemoryCompiler(
    model=OpenAIChat(id="gpt-4o-mini"),
    db=db,
    capture_instructions="""
    Focus on:
    - Programming languages and frameworks
    - Communication preferences
    - Project context
    """,
)

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    db=db,
    memory_compiler=memory,
    update_memory_on_run=True,
)
```

