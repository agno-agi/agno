# CLAUDE.md - Memory Cookbook

Instructions for Claude Code when testing the memory cookbooks.

---

## Overview

This folder contains **memory management** examples - how agents remember user information, share memories, and use memory tools.

**Total Examples:** 21

---

## Quick Reference

**Test Environment:**
```bash
.venvs/demo/bin/python
./cookbook/scripts/run_pgvector.sh  # For database-backed memory
```

**Run a cookbook:**
```bash
.venvs/demo/bin/python cookbook/09_memory/01_agent_with_memory.py
```

---

## Folder Structure

| File/Folder | Description |
|:------------|:------------|
| `01_agent_with_memory.py` | Basic memory manager |
| `02_agentic_memory.py` | Agentic memory updates |
| `03_agents_share_memory.py` | Shared memory between agents |
| `04_custom_memory_manager.py` | Custom memory implementation |
| `05_multi_user_multi_session_chat.py` | Multi-tenant memory |
| `06_multi_user_multi_session_chat_concurrent.py` | Concurrent access |
| `07_share_memory_and_history_between_agents.py` | Memory + history sharing |
| `08_memory_tools.py` | Memory as tools |
| `memory_manager/` | MemoryManager patterns |
| `optimize_memories/` | Memory optimization strategies |

---

## Key Patterns

### Basic Memory
Agent remembers facts about users across sessions.

### Agentic Memory
Agent decides when to save memories based on context.

### Shared Memory
Multiple agents access the same memory store.

### Memory Tools
Explicit tools for memory operations.

---

## Testing Order

1. `01_agent_with_memory.py` - Basic pattern
2. `02_agentic_memory.py` - Automatic updates
3. `03_agents_share_memory.py` - Multi-agent

---

## API Keys Required

- `OPENAI_API_KEY` - Most examples

---

## Dependencies

- PostgreSQL with PgVector for persistent memory
- SQLite available for local testing
