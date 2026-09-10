# Test Log

Not run yet. Repository instructions require waiting for explicit user approval
before running the cookbook or automated tests.

### with_postgres.py

**Status:** NOT RUN

**Description:** AgentOS supplies PostgreSQL storage to an agent using filesystem=True.

**Result:** Runnable server example authored; startup, chat, and browser behavior
have not been verified. Execution deferred until the user requests testing.

---

### with_local_files.py

**Status:** NOT RUN

**Description:** AgentOS serves an agent with durable files on disk and sessions in SQLite.

**Result:** Runnable server example authored; startup, chat, and browser behavior
have not been verified. Execution deferred until the user requests testing.

---

### with_custom_namespace.py

**Status:** NOT RUN

**Description:** AgentOS serves an explicitly configured filesystem namespace with storage limits.

**Result:** Runnable server example authored; startup, chat, and browser behavior
have not been verified. Execution deferred until the user requests testing.

---

### with_shared_files.py

**Status:** NOT RUN

**Description:** AgentOS serves Researcher and Editor with access to the same durable files.

**Result:** Runnable server example authored; startup, chat, and browser behavior
have not been verified. Execution deferred until the user requests testing.

---

### with_user_isolation.py

**Status:** NOT RUN

**Description:** AgentOS uses JWT identity to isolate managed files per user.

**Result:** Runnable server example authored; startup, chat, and browser behavior
have not been verified. Execution deferred until the user requests testing.

---

### with_knowledge_and_notes.py

**Status:** NOT RUN

**Description:** AgentOS serves one agent with read-only documentation and separate writable notes.

**Result:** Runnable server example authored; startup, chat, and browser behavior
have not been verified. Execution deferred until the user requests testing.

---

### with_existing_knowledge.py

**Status:** NOT RUN

**Description:** AgentOS exposes an existing Knowledge instance through PageFileSystem.

**Result:** Runnable server example authored; startup, chat, and browser behavior
have not been verified. Execution deferred until the user requests testing.

---

### with_knowledge.py

**Status:** NOT RUN

**Description:** Uses `PageFileSystem(db=..., namespace=...)` directly through
`Agent(filesystem=pages)`, with automatic tools and AgentOS registration/setup.
Preserves the existing namespace and vector table. Sync remains explicit.

**Result:** Execution deferred until the user requests testing.

---

### knowledge_filesystem.py

**Status:** NOT RUN

**Description:** Uses `PageFileSystem(db=..., namespace=...)` directly through
`Agent(filesystem=...)`. AgentOS discovers and prepares its Knowledge store;
the agent receives read-only tools automatically. Source sync stays explicit.

**Result:** Execution deferred until the user requests testing. Database setup,
source sync, agent tool calls, and HTTP behavior have not been verified at runtime.

---
