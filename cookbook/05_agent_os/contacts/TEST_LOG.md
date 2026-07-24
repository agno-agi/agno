# Contacts Cookbook — Test Log

## 2026-07-24

### server.py

**Status:** PASS (build)

**Description:** News agency AgentOS with news-agent and publish-team exposed via RemoteAccess. App builds and serves.

**Result:** Build-verified; serves on port 7778.

---

### 01_joke_writer.py

**Status:** PASS (build)

**Description:** Joke writer with a local safety-check contact and remote news agent / publishing team contacts. App builds with the server offline (remote metadata degrades gracefully).

**Result:** Build-verified; live end-to-end pass pending.

---

### 02_contacts_local.py

**Status:** PASS (build)

**Description:** Assistant with local docs agent and research team contacts; no server needed.

**Result:** Build-verified; live end-to-end pass pending.

---

### 03_support_agent.py

**Status:** PASS (build)

**Description:** Customer support AgentOS (port 7779) contacting the remote coding agent on server.py, self-exposed via RemoteAccess so the coding agent can contact it back.

**Result:** Build-verified; live end-to-end pass pending.

---

### 04_personal_agent.py

**Status:** PASS (build)

**Description:** Personal agent with own tools plus remote news and coding contacts.

**Result:** Build-verified; live end-to-end pass pending.

---
