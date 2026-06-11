# Discord Gateway Adapter Cookbook Test Log

### basic.py

**Status:** NOT YET TESTED

**Description:** Single agent with fluid chat via the Gateway interface.
Tests the listener thread (WebSocket connect, mention-gating, DM handling),
the relay POST to /discord/gateway/events with the shared secret, thread
creation off the user's message, the native typing indicator while the agent
runs, live tool status edits, chunking, and session continuity inside a
thread.

**Result:** Pending live test against a real Discord application. Requires
the Message Content Intent enabled and discord.py installed; no tunnel
needed.

---

### team.py

**Status:** NOT YET TESTED

**Description:** Researcher + Writer team behind mention-gated chat; verifies
team delegation through the gateway relay path.

**Result:** Pending live test.

---

### workflow.py

**Status:** NOT YET TESTED

**Description:** Two-step draft-then-edit workflow via mention/DM chat;
verifies workflow execution and live status through the relay.

**Result:** Pending live test.

---

### research_assistant.py

**Status:** NOT YET TESTED

**Description:** DiscordTools + web search agent via mention/DM chat;
verifies channel/guild id dependency injection through the gateway payload.

**Result:** Pending live test.

---

### support_team.py

**Status:** NOT YET TESTED

**Description:** Coordinator team routing between specialists via fluid chat;
verifies routing and DiscordTools history search through the gateway.

**Result:** Pending live test.

---

### channel_summarizer.py

**Status:** NOT YET TESTED

**Description:** Channel summarizer triggered by mention with
`reply_in_thread=False`; verifies in-channel replies via the gateway.

**Result:** Pending live test.

---
