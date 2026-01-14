# CLAUDE.md - Agent OS Cookbook

Instructions for Claude Code when testing the Agent OS cookbooks.

---

## Overview

This folder contains **Agent OS** examples - the runtime and API layer for deploying agents as services. Includes database backends, interfaces (Slack, WhatsApp, A2A), tracing, RBAC, and more.

**Total Examples:** 189
**Subfolders:** 16

---

## Quick Reference

**Test Environment:**
```bash
.venvs/demo/bin/python
./cookbook/scripts/run_pgvector.sh  # For database examples
```

**Run a cookbook:**
```bash
.venvs/demo/bin/python cookbook/05_agent_os/basic.py
```

---

## Folder Structure

| Folder | Count | Description |
|:-------|------:|:------------|
| `advanced_demo/` | 10 | Full-featured demos |
| `background_tasks/` | 6 | Background hooks/evals |
| `client/` | 11 | AgentOS client SDK |
| `client_a2a/` | 9 | Agent-to-agent protocol |
| `customize/` | 5 | Custom FastAPI, health, lifespan |
| `dbs/` | 23 | All database backends |
| `interfaces/` | 31 | Slack, WhatsApp, A2A, AGUI |
| `knowledge/` | 4 | Knowledge management |
| `mcp_demo/` | 8 | MCP server integration |
| `middleware/` | 6 | Custom middleware |
| `os_config/` | 3 | Configuration |
| `rbac/` | 8 | Role-based access control |
| `remote/` | 8 | Remote agent execution |
| `skills/` | 4 | Agent skills |
| `tracing/` | 22 | Tracing and observability |
| `workflow/` | 17 | Workflow integration |

---

## Notable Features

### Database Backends (dbs/)
- PostgreSQL, MySQL, SQLite (sync + async)
- MongoDB, Redis, DynamoDB
- Firestore, SurrealDB, SingleStore
- JSON file, GCS JSON

### Interfaces
- **Slack** - Bot integration with memory
- **WhatsApp** - Media support
- **A2A** - Agent-to-agent protocol
- **AGUI** - Custom UI protocol

### RBAC
Role-based access control for multi-tenant deployments.

### Tracing
Integration with various observability platforms.

---

## Testing Priorities

### High Priority
- `basic.py` - Minimal AgentOS setup
- `dbs/postgres_demo.py` - Production database
- `interfaces/slack/basic.py` - Slack integration

### Medium Priority
- `client/` - Client SDK examples
- `rbac/` - Access control
- `tracing/` - Observability

---

## API Keys Required

- `OPENAI_API_KEY` - Most examples
- `SLACK_BOT_TOKEN` - Slack examples
- `WHATSAPP_*` - WhatsApp examples
- Various for observability integrations
