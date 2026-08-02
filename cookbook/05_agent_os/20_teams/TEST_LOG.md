# Test Log: 20_teams

Construction smoke plus live round-trip verification via Azure "Test in Web
Chat" through an ngrok tunnel. Sentinel `MICROSOFT_APP_*` values suffice for
construction; the live rounds used a real Azure Bot resource. No live Bot
Connector traffic is required to import either example.

### basic.py

**Status:** PASS

**Test mode:** CONSTRUCTION_SMOKE + LIVE

**Description:** Constructs one persistent Agent behind the default
`MicrosoftTeams` interface at prefix `/msteams`.

**Result:** `GET /msteams/status` returned `{"status": "available"}`. OpenAPI
exposed `POST /msteams/messages`. Live round-trip through Azure "Test in Web
Chat" delivered text replies end-to-end. Additionally verified inside an actual
Microsoft Teams desktop client belonging to a user in a different tenant, via
the tenant admin's "Manage apps" approval flow.

---

### proactive_alert.py

**Status:** PASS

**Test mode:** CONSTRUCTION_SMOKE + LIVE

**Description:** Constructs the same interface plus a daemon-thread scheduler
that fires `teams.send_alert(user_id, text)` 30 seconds after startup,
retrying every 15 seconds until a conversation reference is available.

**Result:** After a first inbound message from the target user, the scheduled
proactive alert was delivered to the Web Chat window. The same
`send_alert(...)` call also delivered when invoked from a separate Python
process sharing the SQLite database.

---
