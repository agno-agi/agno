# TEST_LOG for cookbook/04_workflows/06_advanced_concepts/background_execution

Generated: 2026-02-08 16:39:09

### background_poll.py

**Status:** FAIL

**Description:** Executed with `.venvs/demo/bin/python` (mode: normal, timeout: 35s).

**Result:** Timed out after 35s. DEBUG *** Agent Run End: 279bd889-9bd2-42b5-9b88-1d665ea235cd ****

---

### websocket_client.py

**Status:** PASS

**Description:** Executed with `.venvs/demo/bin/python` (mode: startup, timeout: 8s).

**Result:** Startup validation completed. [ERROR] Failed to connect: Multiple exceptions: [Errno 61] Connect call failed

---

### websocket_server.py

**Status:** PASS

**Description:** Executed with `.venvs/demo/bin/python` (mode: startup, timeout: 8s).

**Result:** Startup validation only; process terminated after 8.14s. INFO: Finished server process [29101]

---
