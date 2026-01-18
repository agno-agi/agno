# CLAUDE.md - Database Cookbook

Instructions for Claude Code when testing the database cookbooks.

---

## Overview

This folder contains **database integration** examples - how to use different database backends for session storage, chat history, and persistence.

**Total Examples:** 63
**Organization:** By database type

---

## Quick Reference

**Test Environment:**
```bash
.venvs/demo/bin/python
./cookbook/scripts/run_pgvector.sh  # For PostgreSQL
```

**Run a cookbook:**
```bash
.venvs/demo/bin/python cookbook/06_storage/sqlite/sqlite_for_agent.py
```

---

## Folder Structure

| Folder | Description |
|:-------|:------------|
| `dynamodb/` | AWS DynamoDB |
| `firestore/` | Google Firestore |
| `gcs/` | Google Cloud Storage JSON |
| `in_memory/` | In-memory storage |
| `json_db/` | Local JSON files |
| `mongo/` | MongoDB (sync + async) |
| `mysql/` | MySQL (sync + async) |
| `postgres/` | PostgreSQL (sync + async) |
| `redis/` | Redis |
| `singlestore/` | SingleStore |
| `sqlite/` | SQLite (sync + async) |
| `surrealdb/` | SurrealDB |
| `examples/` | Multi-user, table selection |

---

## Database Coverage

Each database folder typically has:
- `*_for_agent.py` - Agent with database
- `*_for_team.py` - Team with database
- `*_for_workflow.py` - Workflow with database

Async variants in `async_*/` subfolders.

---

## Testing Priorities

### No External Dependencies
- `sqlite/` - Local file
- `json_db/` - Local JSON
- `in_memory/` - No persistence

### Common Production
- `postgres/` - Most common
- `redis/` - Caching layer
- `mongo/` - Document store

---

## Services Required

| Database | Setup |
|:---------|:------|
| PostgreSQL | `./cookbook/scripts/run_pgvector.sh` |
| Redis | `docker run -p 6379:6379 redis` |
| MongoDB | `docker run -p 27017:27017 mongo` |
| MySQL | `docker run -p 3306:3306 mysql` |
