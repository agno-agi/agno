# Agent OS Cookbook Testing Log

Testing Agent OS examples in `cookbook/06_agent_os/`.

**Test Environment:**
- Python: `.venvs/demo/bin/python`
- Date: 2026-01-14

---

## Core

### basic.py

**Status:** NOT TESTED

**Description:** Minimal AgentOS setup.

---

### demo.py

**Status:** NOT TESTED

**Description:** Full demo with multiple agents.

---

## dbs/

### postgres_demo.py

**Status:** NOT TESTED

**Description:** PostgreSQL backend.

**Dependencies:** PgVector running

---

### sqlite_demo.py

**Status:** NOT TESTED

**Description:** SQLite backend (no external dependencies).

---

## interfaces/

### slack/basic.py

**Status:** NOT TESTED

**Description:** Basic Slack bot.

**Dependencies:** SLACK_BOT_TOKEN

---

## TESTING SUMMARY

**Summary:**
- Total examples: 189
- Tested: 0
- Passed: 0

**Notes:**
- Start with basic.py and sqlite_demo.py (no external deps)
- Database demos require running services
- Interface demos require API tokens
