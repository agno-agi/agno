# Test log

## 2026-10-08

### session_store.py

**Status:** FAIL

**Description:** Launched the real two-process verification with claude-agent-sdk 0.2.148 using the shared demo environment and this worktree on PYTHONPATH. Both processes use fresh config directories.

**Result:** Process A reached Claude but returned `Not logged in`. Authentication for an empty config directory is not configured. Cross-process transcript resume remains unverified; this is not a passing integration run.

---

### Transcript and adapter unit tests

**Status:** PASS

**Description:** 70 agent tests passed, including SDK store conformance through one bound store per project, SQLite/AsyncSQLite persistence, key rewriting, retries, tools, and resume fallback. The optional summary contract is not implemented.

**Result:** Unit coverage passes; real SDK verification is separate.

---
