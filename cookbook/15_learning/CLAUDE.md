# CLAUDE.md - Learning Machine Testing

Instructions for Claude Code when testing the Learning Machine implementation.

---

## Quick Reference

**Test Environment:**
```bash
# Virtual environment with all dependencies
.venvs/demo/bin/python

# Database (must be running)
PostgreSQL with PgVector at localhost:5532
```

**Run a cookbook:**
```bash
.venvs/demo/bin/python cookbook/15_learning/01_basics/1a_user_profile_always.py
```

**Test results file:**
```
cookbook/15_learning/TESTING.md
```

---

## Testing Workflow

### 1. Before Testing

Ensure the database is running:
```bash
# If using Docker
./cookbook/scripts/run_pgvector.sh
```

### 2. Running Tests

Run individual cookbooks with the demo environment:
```bash
.venvs/demo/bin/python cookbook/15_learning/<folder>/<file>.py
```

Tail output for long tests:
```bash
.venvs/demo/bin/python cookbook/15_learning/01_basics/1a_user_profile_always.py 2>&1 | tail -100
```

### 3. Updating TESTING.md

After each test, update `cookbook/15_learning/TESTING.md` with:
- Test name and path
- Status: PASS or FAIL
- Brief description of what was tested
- Any notable observations or issues

Format:
```markdown
### filename.py

**Status:** PASS/FAIL

**Description:** What the test does and what was observed.

**Result:** Summary of success/failure.

---
```

---

## Code Locations

| Component | Location |
|-----------|----------|
| LearningMachine | `libs/agno/agno/learn/machine.py` |
| Config classes | `libs/agno/agno/learn/config.py` |
| Schema classes | `libs/agno/agno/learn/schemas.py` |
| Store Protocol | `libs/agno/agno/learn/stores/protocol.py` |
| UserProfileStore | `libs/agno/agno/learn/stores/user_profile.py` |
| UserMemoryStore | `libs/agno/agno/learn/stores/user_memory.py` |
| SessionContextStore | `libs/agno/agno/learn/stores/session_context.py` |
| EntityMemoryStore | `libs/agno/agno/learn/stores/entity_memory.py` |
| LearnedKnowledgeStore | `libs/agno/agno/learn/stores/learned_knowledge.py` |
| Agent integration | `libs/agno/agno/agent/agent.py` |

---

## Store Mode Support

| Store | ALWAYS | AGENTIC | PROPOSE | HITL |
|-------|--------|---------|---------|------|
| UserProfileStore | Yes | Yes | No | No |
| UserMemoryStore | Yes | Yes | No | No |
| SessionContextStore | Yes | No | No | No |
| EntityMemoryStore | Yes | Yes | No | No |
| LearnedKnowledgeStore | Yes | Yes | Yes | No |

---

## Cookbook Structure

```
cookbook/15_learning/
├── 01_basics/           # Basic tests for each store and mode
├── 02_user_profile/     # User profile specific tests
├── 03_session_context/  # Session context specific tests
├── 04_entity_memory/    # Entity memory specific tests
├── 05_learned_knowledge/ # Learned knowledge specific tests
├── 07_patterns/         # Combined pattern tests
├── TESTING.md           # Test results log
└── CLAUDE.md            # This file
```

---

## Key API Pattern

Access the learning machine from an agent:
```python
# Get the resolved LearningMachine instance
learning_machine = agent.get_learning_machine()

# Access individual stores
learning_machine.user_profile_store.print(user_id=user_id)
learning_machine.memories_store.print(user_id=user_id)
learning_machine.session_context_store.print(session_id=session_id)
learning_machine.entity_memory_store.search(query="...", limit=10)
learning_machine.learned_knowledge_store.print(query="...")
```

---

## Known Issues

1. **Design docs missing**: The `projects/learning-machine/` directory referenced in the main CLAUDE.md doesn't exist.

2. **HITL mode**: Not implemented in any store - warnings are logged but no actual human-in-the-loop functionality.

3. **PROPOSE mode**: Only supported in LearnedKnowledgeStore.

4. **Model in cookbooks**: Uses `gpt-5.2` which may not be available to all users.

---

## Debugging

Enable debug output:
```python
import os
os.environ["AGNO_DEBUG"] = "true"
```

Or in the store:
```python
store = UserProfileStore(config=..., debug_mode=True)
```
