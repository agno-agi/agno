# Test Log: remote

> Reworked after renaming the interface to RemoteAccess and removing RemoteWorkflow. Re-run each file and update this log.

### server.py

**Status:** PENDING

**Description:** Backing AgentOS server on port 7778. Mounts the RemoteAccess interface for assistant-agent, researcher-agent, and research-team; internal-agent is registered on the OS but not exposed remotely. The QA workflow is served locally only.

**Result:** Previous run (2026-07-23, pre-rename): PASS — opt-in listing, 404 for internal-agent, /remote/config, RemoteAgent and RemoteTeam round trips all verified. Note: on Windows, `python server.py` can log a spurious IPv6 bind error (WinError 10048) while the IPv4 server keeps serving; running via `uvicorn server:app --port 7778` avoids it.

---

### 01_remote_agent.py

**Status:** PENDING

**Description:** AgentOS app on port 7777 serving RemoteAgent proxies to the server's agents via the /remote endpoints.

---

### 02_remote_team.py

**Status:** PENDING

**Description:** AgentOS app on port 7777 serving a RemoteTeam proxy to research-team.

**Result:** Previous run (2026-07-23, pre-rename): PASS — team metadata resolved through the interface; run round trip verified.

---

### 03_remote_agent_as_team_member.py

**Status:** PENDING

**Description:** AgentOS app on port 7777 serving a local Team with RemoteAgent members plus a local summarizer.

---

### 04_agent_os_gateway.py

**Status:** PENDING

**Description:** Gateway AgentOS on port 7777 combining remote agents, a remote team, and local story-writing agents/workflow.

**Result:** Previous run (2026-07-23, as 05_agent_os_gateway.py with a remote workflow): PASS — aggregation and chained runs verified.

---
