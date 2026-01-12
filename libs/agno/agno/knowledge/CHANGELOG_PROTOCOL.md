# Knowledge Protocol Changes Summary

This document summarizes the changes made to introduce the Knowledge Protocol system.

## Overview

We introduced a `KnowledgeProtocol` that allows custom knowledge implementations to work with Agno agents. The key design change is that **each knowledge type defines its own tools** rather than being forced into a single `search()` interface.

## New Protocol

The `KnowledgeProtocol` (in `protocol.py`) defines a minimal interface:

### Required Methods

| Method | Purpose |
|--------|---------|
| `build_context(**kwargs) -> str` | Returns instructions for the agent's system prompt |
| `get_tools(**kwargs) -> List[Callable]` | Returns tools the agent can call |
| `aget_tools(**kwargs) -> List[Callable]` | Async version of get_tools |

### Optional Methods

| Method | Purpose |
|--------|---------|
| `retrieve(query, **kwargs) -> List[Document]` | Default retrieval for `add_knowledge_to_context` |
| `aretrieve(query, **kwargs) -> List[Document]` | Async version of retrieve |

## Implementation Changes

### Knowledge Class (`knowledge.py`)

Added protocol methods:

- **`build_context()`** - Returns instructions about the `search_knowledge_base` tool and available filters
- **`get_tools()`** - Returns the search tool, configured based on `enable_agentic_filters`
- **`aget_tools()`** - Async version
- **`retrieve()`** / **`aretrieve()`** - Delegates to existing `search()` / `asearch()` methods

Refactored tool creation into helper methods:
- `_create_search_tool()` - Creates basic search tool
- `_create_search_tool_with_filters()` - Creates search tool with filter parameter

### FileSystemKnowledge Class (`filesystem.py`)

New implementation providing directory-based file search:

- **`build_context()`** - Explains the three available tools
- **`get_tools()`** - Returns `grep_file`, `list_files`, `get_file` tools
- **`retrieve()`** - Uses grep as default retrieval mechanism

### Agent Class (`agent.py`)

Changed to delegate to protocol methods:

**Before:**
```python
# Hardcoded tool creation
if self.search_knowledge:
    tool = self._get_search_knowledge_base_function(...)
    agent_tools.append(tool)

# Hardcoded system prompt logic
if self.enable_agentic_knowledge_filters:
    valid_filters = self.knowledge.get_valid_filters()
    # ... build filter instructions ...
```

**After:**
```python
# Delegate to protocol
if self.knowledge and self.search_knowledge:
    tools = self.knowledge.get_tools(
        run_response=run_response,
        enable_agentic_filters=self.enable_agentic_knowledge_filters,
        ...
    )
    agent_tools.extend(tools)

# System prompt from protocol
if self.knowledge:
    context = self.knowledge.build_context(
        enable_agentic_filters=self.enable_agentic_knowledge_filters
    )
    additional_information.append(context)
```

**Retrieval changes:**
```python
# Before: Accessed knowledge.search() directly
relevant_docs = self.knowledge.search(query=query, ...)

# After: Uses protocol retrieve() with graceful fallback
retrieve_fn = getattr(self.knowledge, "retrieve", None)
if callable(retrieve_fn):
    relevant_docs = retrieve_fn(query=query, max_results=num_documents)
```

### Team Class (`team.py`)

Same changes as Agent class for consistency.

### OS Module (`os/app.py`, `os/routers/*/schema.py`)

Changed to use `getattr()` for optional attributes:

```python
# Before
if agent.knowledge and agent.knowledge.contents_db:
    ...

# After
contents_db = getattr(agent.knowledge, "contents_db", None)
if contents_db:
    ...
```

## Files Changed

| File | Type of Change |
|------|----------------|
| `knowledge/protocol.py` | New file - protocol definition |
| `knowledge/filesystem.py` | New file - filesystem implementation |
| `knowledge/knowledge.py` | Added protocol methods |
| `knowledge/__init__.py` | Export new classes |
| `agent/agent.py` | Delegate to protocol methods |
| `team/team.py` | Delegate to protocol methods |
| `os/app.py` | Use getattr for optional attributes |
| `os/routers/agents/schema.py` | Use getattr for optional attributes |
| `os/routers/teams/schema.py` | Use getattr for optional attributes |

## Removed Code

- `Agent._get_search_knowledge_base_function()` - Replaced by `knowledge.get_tools()`
- `Agent._search_knowledge_base_with_agentic_filters_function()` - Replaced by `knowledge.get_tools()`
- Hardcoded filter instructions in `get_system_message()` - Replaced by `knowledge.build_context()`

## Breaking Changes

None. The `Knowledge` class maintains backward compatibility by implementing all protocol methods.

## Benefits

1. **Flexibility** - Each knowledge type can expose different tools
2. **Encapsulation** - Tool creation logic lives in the knowledge class, not the agent
3. **Extensibility** - Easy to add new knowledge types without modifying agent code
4. **Type Safety** - Protocol provides clear interface contract
