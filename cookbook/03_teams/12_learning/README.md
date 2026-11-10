# Team Learning

Examples demonstrating team learning capabilities in Agno. Teams can automatically capture user profiles, memories, entity information, session context, learned knowledge, and decision logs across conversations.

## Prerequisites

- PostgreSQL running (`./cookbook/scripts/run_pgvector.sh`)
- `OPENAI_API_KEY` set

## Files

| File | Description |
|------|-------------|
| `01_team_always_learn.py` | Basic `learning=True` mode -- team automatically captures user profile and memories |
| `02_team_configured_learning.py` | Configured LearningMachine with independent store modes (ALWAYS, AGENTIC) |
| `03_team_entity_memory.py` | Entity memory for tracking people, projects, and relationships |
| `04_team_session_planning.py` | Session context with planning mode for multi-step goal tracking |
| `05_team_learned_knowledge.py` | Shared knowledge base using vector DB for institutional knowledge |
| `06_team_decision_log.py` | Decision logging for auditing and traceability |

## Running

```bash
.venvs/demo/bin/python cookbook/03_teams/12_learning/01_team_always_learn.py
```
