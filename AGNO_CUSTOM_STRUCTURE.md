# agno_custom Structure

**Extraction Source:** `/Users/glaston.jiue/Desktop/Banavo/Agent_OS/banavo-agent-os/agno_custom/`

**Current Location:** `/Users/glaston.jiue/Desktop/Banavo/Agent_OS/agno/agno_custom/`

**Status:** Extracted for Agno V2.6.5 migration (V3 fresh start)

**Branch:** v2-upgrade_v3

---

## Directory Layout

```
agno_custom/
├── __init__.py                 (Module entry point)
├── __pycache__/               (Python cache, ignored in git)
│
├── agent/                      (Agent extensions)
│   ├── __init__.py
│   └── agent.py               (Custom Agent class)
│
├── events/                     (Event handling)
│   ├── __init__.py
│   └── [event modules]
│
├── memory/                     (Memory management)
│   ├── __init__.py
│   └── memory.py              (Custom Memory class)
│
├── models/                     (LLM model wrappers)
│   ├── __init__.py
│   ├── base.py                (MessageData class)
│   └── openai/                (OpenAI model customizations)
│       ├── __init__.py
│       ├── chat.py            (OpenAIChat model)
│       ├── gpt5_responses.py   (GPT-5 reasoning)
│       └── [other models]
│
├── run/                        (Run and response handling)
│   ├── __init__.py
│   ├── response.py            (RunResponse)
│   ├── team.py                (TeamRunResponse)
│   └── [other run modules]
│
├── team/                       (Team orchestration)
│   ├── __init__.py
│   └── team.py                (Custom Team class)
│
├── tools/                      (Tool system)
│   ├── __init__.py
│   ├── function.py
│   ├── toolkit.py
│   └── [tool modules]
│
└── utils/                      (Utilities)
    ├── __init__.py
    ├── custom_message_logger.py
    ├── events.py
    ├── functions.py
    └── string.py
```

---

## Module Purposes

### `agent/` - Agent Extensions
Custom Agent class with Banava features
- Multi-tenant support
- Neo4j KG integration
- Tool confirmation/approval

### `models/` - Model Customizations
LLM model configuration and response handling
- **base.py:** MessageData for streaming
- **openai/chat.py:** OpenAIChat wrapper
- **openai/gpt5_responses.py:** GPT-5 reasoning support

### `team/` - Team Orchestration
Custom Team with multi-agent coordination
- write_to_storage() error handling
- Attribute checks for optional fields

### `memory/` - Memory Management
Agent memory and session persistence
- User memory management
- Session summaries

### `run/` - Run & Response Handling
Run and response definitions
- RunResponse and RunEvent
- TeamRunResponse handling

### `tools/` - Tool System
Tool definition and execution
- function.py: Function-based tools
- toolkit.py: Tool grouping

### `utils/` - Utility Functions
Helper functions and logging
- Message formatting
- Event dispatching
- String utilities

---

## File Counts

- **Total Python files:** 29
- **Core modules:** 9
- **Model variations:** 5
- **Utilities:** 4
- **__init__.py files:** 9

---

## Extraction Verification

✅ **29 Python files copied successfully**
✅ **All subdirectories present**
✅ **Ready for V2 API migration (Phase 1)**

---

## Next Steps (Phase 1)

1. Merge Agno V2.6.5 base code
2. Update agno_custom for V2 APIs
3. Validate imports work
4. Document breaking changes

---

**Status: Phase 0 - Task 0.2 Complete**
