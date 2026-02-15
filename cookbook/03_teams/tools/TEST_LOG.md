# Test Log: tools

> Updated: 2026-02-12

### async_tools.py

**Status:** SKIP

**Description:** Async tools using AgentQL for web scraping.

**Result:** Missing: agentql package not installed.

---

### custom_tools.py

**Status:** PASS

**Description:** Custom team tools with FAQ answering and web search member. Demonstrates team-level tools alongside member agents.

**Result:** Completed successfully. Team tools and member delegation both worked correctly.

---

### member_tool_hooks.py

**Status:** PASS

**Description:** Member-level tool hooks with pre/post hooks on medical data read/write tools. Demonstrates permission checking via hooks.

**Result:** Completed successfully. Reader agent fetched data, writer agent correctly had permission denied by pre-hook for unauthorized customer. Hook system working as designed.

---

### tool_hooks.py

**Status:** SKIP

**Description:** Team tool hooks using RedditTools.

**Result:** Missing: praw package not installed.

---
