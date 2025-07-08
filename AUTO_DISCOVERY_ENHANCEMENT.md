# AgentOS Auto-Discovery Enhancement

## Overview

The `AgentOS` class has been enhanced to support automatic discovery of managers from attached agents, teams, and workflows. This enhancement allows for a more streamlined setup process while maintaining the flexibility to explicitly specify managers when needed.

## Key Features

### 1. Auto-Discovery When No Managers Are Provided

When no `managers` parameter is passed to the `AgentOS` constructor, the system automatically scans all attached agents, teams, and workflows to discover components that correspond to managers:

- **Session Manager**: Discovered from database connections (`memory.db` for agents/teams, `storage` for workflows)
- **Knowledge Manager**: Discovered from `knowledge` attributes
- **Memory Manager**: Discovered from `memory` attributes with database connections
- **Metrics Manager**: Discovered from database connections
- **Eval Manager**: Discovered from database connections

### 2. Explicit Manager Override

When managers are explicitly passed to the constructor, they override the auto-discovery process entirely. This ensures that users have full control when needed.

### 3. Unique Component Detection

The system uses unique identifiers to avoid creating duplicate managers for the same underlying components (e.g., same database connection, same knowledge base).

### 4. Descriptive Manager Names

Auto-discovered managers are given descriptive names that indicate their source:
- `Session Manager (Agent: Memory Agent)`
- `Knowledge Manager (Agent: Knowledge Agent)`
- `Memory Manager (Team: Test Team)`
- `Eval Manager (Workflow: Test Workflow)`

## Usage Examples

### Auto-Discovery Mode

```python
from agno.agent import Agent
from agno.memory.memory import Memory
from agno.db.postgres.postgres import PostgresDb
from agno.os import AgentOS

# Setup database and memory
db = PostgresDb(db_url="postgresql://...")
memory = Memory(db=db)

# Create agent with memory
agent = Agent(
    name="My Agent",
    memory=memory,
    enable_user_memories=True,
)

# AgentOS will auto-discover managers
agent_os = AgentOS(
    name="My App",
    agents=[agent],
    # No managers parameter - auto-discovery enabled
)

# Managers are automatically discovered and available
print(f"Discovered {len(agent_os.managers)} managers")
```

### Explicit Manager Mode

```python
from agno.os.managers import SessionManager, MemoryManager

# Explicitly specify managers
agent_os = AgentOS(
    name="My App",
    agents=[agent],
    managers=[
        SessionManager(db=db, name="Custom Session Manager"),
        MemoryManager(memory=memory, name="Custom Memory Manager"),
    ],
    # Auto-discovery is bypassed
)
```

## Component Discovery Rules

### Agents
- **Storage**: Uses `agent.memory.db` (not `agent.storage`)
- **Knowledge**: Uses `agent.knowledge`
- **Memory**: Uses `agent.memory` (if it has a `db` attribute)

### Teams
- **Storage**: Uses `team.memory.db` (not `team.storage`)
- **Knowledge**: Uses `team.knowledge`
- **Memory**: Uses `team.memory` (if it has a `db` attribute)

### Workflows
- **Storage**: Uses `workflow.storage`
- **Knowledge**: Uses `workflow.knowledge`
- **Memory**: Uses `workflow.memory` (if it has a `db` attribute)

## Manager Types Supported

1. **SessionManager**: Manages agent/team/workflow sessions
2. **KnowledgeManager**: Manages knowledge bases and document retrieval
3. **MemoryManager**: Manages user memories and session summaries
4. **MetricsManager**: Manages performance metrics and analytics
5. **EvalManager**: Manages evaluation runs and results

## Benefits

1. **Simplified Setup**: No need to manually create managers for common use cases
2. **Reduced Boilerplate**: Automatic discovery eliminates repetitive manager creation code
3. **Flexibility**: Explicit managers still override auto-discovery when needed
4. **Consistency**: Ensures all available components are properly exposed via managers
5. **Debugging**: Clear logging shows which managers were auto-discovered

## Migration Guide

### Before Enhancement
```python
# Had to manually create managers
agent_os = AgentOS(
    name="My App",
    agents=[agent],
    managers=[
        SessionManager(db=db),
        MemoryManager(memory=memory),
        KnowledgeManager(knowledge=knowledge),
    ],
)
```

### After Enhancement
```python
# Auto-discovery handles manager creation
agent_os = AgentOS(
    name="My App",
    agents=[agent],
    # Managers auto-discovered from agent components
)
```

## Testing

Run the test script to see the enhancement in action:

```bash
python test_auto_discovery.py
```

This will demonstrate:
- Auto-discovery with different component types
- Unique component detection
- Explicit manager override
- Descriptive naming

## Implementation Details

The enhancement is implemented in the `_auto_discover_managers()` method of the `AgentOS` class. This method:

1. Scans all agents, teams, and workflows
2. Identifies components that correspond to managers
3. Uses unique identifiers to avoid duplicates
4. Creates appropriate manager instances with descriptive names
5. Logs the discovery process for transparency

The method is called automatically when no managers are provided to the constructor, ensuring backward compatibility with existing code. 