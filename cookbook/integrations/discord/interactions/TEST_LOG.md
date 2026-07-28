# Discord Interactions Cookbook Test Log

### basic.py

**Status:** NOT YET TESTED

**Description:** Minimal Discord bot exposing a single agent via the
`/ask` slash command. Tests the end-to-end Interactions API flow:
signature verification, PING handshake, deferred response, attachment
resolution, ephemeral replies, and followup webhook delivery.

**Result:** Pending live test against a real Discord application.

---

### team.py

**Status:** NOT YET TESTED

**Description:** Researcher + Writer team behind `/ask`; verifies team
delegation and member tool status surfacing in the thread.

**Result:** Pending live test.

---

### workflow.py

**Status:** NOT YET TESTED

**Description:** Two-step draft-then-edit workflow behind `/ask`; verifies
workflow step execution and live status flips between steps.

**Result:** Pending live test.

---

### research_assistant.py

**Status:** NOT YET TESTED

**Description:** Agent combining DiscordTools channel introspection with web
search; verifies dependency injection of channel/guild ids.

**Result:** Pending live test.

---

### support_team.py

**Status:** NOT YET TESTED

**Description:** Coordinator team routing between Technical Support and
Documentation Specialist; verifies routing and DiscordTools history search.

**Result:** Pending live test.

---

### channel_summarizer.py

**Status:** NOT YET TESTED

**Description:** Channel history summarizer with `reply_in_thread=False`;
verifies in-channel replies and get_channel_messages tool flow.

**Result:** Pending live test.

---

### personal_assistant.py

**Status:** NOT YET TESTED

**Description:** User-install + ephemeral-by-default combo: the app is
installable to user accounts (usable in any server, group DM, or bot DM)
and every `/ask` reply is visible only to the asker with no thread or
channel message.

**Result:** Pending live test (requires User Install enabled under
Installation in the Dev Portal).

---

### agent_with_memory.py

**Status:** NOT YET TESTED

**Description:** MemoryManager captures durable user facts on every run
(`update_memory_on_run=True`), keyed by Discord user id; verifies
memories persist across channels and servers.

**Result:** Pending live test.

---

### agent_with_media.py

**Status:** NOT YET TESTED

**Description:** Media analysis through the `/ask` `file` option:
attachments resolve to typed media (Image/Audio/Video/File) by content
type and are forwarded to the agent.

**Result:** Pending live test.

---
