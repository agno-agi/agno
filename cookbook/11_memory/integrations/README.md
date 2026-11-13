# Memory Integrations

Examples for connecting Agno agents to external memory services.

## Files

- [`mem0_integration.py`](./mem0_integration.py): Uses Mem0 as an external memory service.
- [`membase_integration.py`](./membase_integration.py): Uses Membase memory, citing the Memory each fact came from.
- [`memori_integration.py`](./memori_integration.py): Uses Memori for conversation memory.
- [`mnemoverse_integration.py`](./mnemoverse_integration.py): Uses Mnemoverse as an external memory service and rates the recalled memories after the run.
- [`zep_integration.py`](./zep_integration.py): Uses Zep tools for memory context retrieval.
- [`memanto_integration.py`](./memanto_integration.py): Uses MemantoTools for persistent semantic memory.
- [`inspeximus_integration.py`](./inspeximus_integration.py): Uses inspeximus for corrections that stay corrected.

## Run

```bash
.venvs/demo/bin/python cookbook/11_memory/integrations/<file>.py
```
