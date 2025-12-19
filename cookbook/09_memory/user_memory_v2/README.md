# User Memory V2

Structured user memory system that enables agents to learn about users through conversations.

## Examples

### Basic Examples

| File | Description |
|------|-------------|
| `01_basic.py` | Minimal working example |
| `02_automatic_learning.py` | Agent automatically extracts user info |
| `03_agentic_memory.py` | Agent uses tools to manage memory |
| `04_persistence.py` | Memory persists across sessions |

### Real-World Multi-User Examples

| File | Description |
|------|-------------|
| `05_team_dev_assistant.py` | **Agentic mode.** 3 developers (Marcus, Priya, Jake) with different roles and preferences using a shared coding assistant across multiple sessions |
| `06_customer_support.py` | **Automatic mode.** 3 customers (Alice, Bob, Carol) interacting with support - shows automatic extraction of customer profiles and preferences |
| `07_learning_coach.py` | **Agentic mode.** 2 students (Emma, David) with different goals - career changer vs interview prep - with progress tracking over 4 weeks |

### Advanced Customization

| File | Description |
|------|-------------|
| `08_advanced_customization.py` | Per-layer controls, schema overrides, custom extraction prompts, nested categories |

## Quick Start

```python
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.memory import MemoryManagerV2
from agno.models.openai import OpenAIChat

db = SqliteDb(db_file="tmp/memory.db")
memory = MemoryManagerV2(db=db, model=OpenAIChat(id="gpt-4o-mini"))

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    memory_manager_v2=memory,
)

# Agent learns through conversations
agent.print_response("I'm Sarah, a data scientist.", user_id="sarah")

# Future conversations use learned context
agent.print_response("How do I clean data?", user_id="sarah")
```

## Two Modes

### Automatic Mode (Default)

Agent extracts user info in the background after each conversation.

```python
memory = MemoryManagerV2(
    db=db,
    model=OpenAIChat(id="gpt-4o-mini"),
    update_memory_on_run=True,  # Default
)
```

### Agentic Mode

Agent has tools to explicitly manage memory. Useful for "forget X" commands.

```python
memory = MemoryManagerV2(
    db=db,
    enable_agentic_memory=True,
)
```

### Both Modes (Recommended)

```python
memory = MemoryManagerV2(
    db=db,
    model=OpenAIChat(id="gpt-4o-mini"),
    update_memory_on_run=True,      # Auto catches implicit info
    enable_agentic_memory=True,     # Handles "forget X" commands
)
```

## Memory Layers

The system extracts and stores:

| Layer | Content | Example |
|-------|---------|---------|
| **Profile** | Identity, background | name, role, company |
| **Policies** | Preferences, rules | "be concise", language |
| **Knowledge** | Context, facts | project details |
| **Feedback** | What worked/didn't | praise, criticism |

## Context Injection

Learned memory is compiled into XML and injected into the system message:

```xml
<user_profile>
  name: Sarah
  role: data scientist
</user_profile>

<user_policies>
  response_style: concise
</user_policies>
```

## Configuration

```python
memory = MemoryManagerV2(
    db=db,
    model=OpenAIChat(id="gpt-4o-mini"),
    
    # Enable memory (controls both READ and WRITE for all layers)
    add_memory_to_context=True,
    
    # Automatic extraction (background)
    update_memory_on_run=True,
    
    # Agent tools (agentic mode)
    enable_agentic_memory=False,
)
```

## Advanced: Schema Overrides

Guide extraction with custom dataclass schemas:

```python
from dataclasses import dataclass

@dataclass
class EngineerProfile:
    name: str
    role: str
    company: str
    primary_languages: list[str]

memory = MemoryManagerV2(
    db=db,
    model=OpenAIChat(id="gpt-4o-mini"),
    update_memory_on_run=True,
    profile_schema=EngineerProfile,  # Guide profile extraction
)
```

## Advanced: Custom Extraction Prompts

Override the default extraction prompt for any layer:

```python
memory = MemoryManagerV2(
    db=db,
    model=OpenAIChat(id="gpt-4o-mini"),
    update_memory_on_run=True,
    policies_extraction_prompt="""
Only save EXPLICIT preferences stated with "I prefer", "always", or "never".
Do NOT infer preferences from behavior.
""",
)
```
