# Test Log: 26_teams

Sentinel `MICROSOFT_APP_*` values suffice to construct either example; live
rounds require a real Azure Bot resource. Importing either file needs no Bot
Connector traffic.

### basic.py

**Status:** PASS

**Test mode:** CONSTRUCTION_SMOKE + LIVE

**Description:** Constructs one persistent Agent behind the default
`MicrosoftTeams` interface at prefix `/msteams`.

**Result:** `GET /msteams/status` returned `{"status": "available"}`. OpenAPI
exposed `POST /msteams/messages`. Live round-trip through Azure "Test in Web
Chat" delivered text replies end-to-end, and again from a Microsoft Teams
desktop client.

---

### proactive_alert.py

**Status:** PASS

**Test mode:** CONSTRUCTION_SMOKE + LIVE

**Description:** Constructs the same interface plus a daemon-thread scheduler
that fires `teams.asend_alert(user_id, text)` 30 seconds after startup,
retrying every 15 seconds until a conversation reference is available.

**Result:** After a first inbound message from the target user, the scheduled
proactive alert was delivered to the Web Chat window. The same
`asend_alert(...)` call also delivered when invoked from a separate Python
process sharing the SQLite database.

---
