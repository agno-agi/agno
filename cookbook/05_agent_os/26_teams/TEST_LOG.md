# Test Log: 26_teams

**Date:** 2026-08-27

**Library source:** `libs/agno` in this worktree at commit `b776c5c4d`.

Both examples were run live against a real Azure Bot resource (F0, single-tenant)
on the Bot Framework **Web Chat** channel, reached through an HTTPS tunnel to
`localhost:7777`. Inbound activities carried genuine Bot Framework JWTs, verified
against Microsoft's live JWKS; outbound replies used a real bot token minted from
the app registration's client credentials.

Not exercised, because Web Chat cannot produce them: the Microsoft Teams channel
itself, `content.downloadUrl` file attachments (Teams sends these; Web Chat sends
a plain `contentUrl`), and app sideloading. Those need a Teams-licensed tenant.

| Variable | Purpose |
|---|---|
| `MICROSOFT_APP_ID` | Bot Framework application id |
| `MICROSOFT_APP_PASSWORD` | Client secret for that application |
| `MICROSOFT_APP_TENANT_ID` | Required here: the Azure portal no longer offers a Multi Tenant bot, so the app is single-tenant and the token endpoint needs the tenant guid |
| `OPENAI_API_KEY` | Model calls for both examples |
| `ALERT_USER_ID` | `proactive_alert.py` only |

---

### basic.py

**Status:** PASS

**Test mode:** LIVE

**Command:**

```bash
PYTHONPATH=$PWD/libs/agno .venvs/demo/bin/python cookbook/05_agent_os/26_teams/basic.py
```

**Description:** One persistent Agent behind the default `MicrosoftTeams`
interface at prefix `/msteams`, driven from Azure's "Test in Web Chat".

**Result:** `GET /msteams/status` returned `{"status": "available"}`. An
unauthenticated `POST /msteams/messages` from the public internet returned
**403**, while every Web Chat activity in the same session returned **200** —
JWT validation is on and rejects strangers.

Sessions persisted as `teams:teams-assistant:<user-id>`, with the conversation
reference stored under `session_data.teams_conversation_ref` carrying
`service_url`, `conversation_id` and `bot_identity`, alongside the existing
`session_state` and `session_metrics` keys. Repeat messages reused one session
rather than creating new ones; the reference survived subsequent saves unchanged.
Final state: 3 sessions, 12 runs.

`/new` replied `New conversation started!` and created a suffixed session
(`…:<8-hex>`). Every later message landed on the newest session, and each earlier
session stopped accumulating runs at the point its successor was created —
verified across two consecutive resets.

Attachments: an image was described correctly. A PDF was summarised across 31
pages. A `.zip` — a type outside `File`'s 20-entry MIME allowlist — was skipped
rather than forwarded, and the reply began
`[Some attachments could not be read: …]`, so the user's own text still reached
the model. Bot token requests over roughly fifteen messages: **4**, spaced by the
token TTL and by server restarts rather than by message count.

---

### proactive_alert.py

**Status:** PASS

**Test mode:** LIVE

**Command:**

```bash
export ALERT_USER_ID="<user-id from the session row>"
PYTHONPATH=$PWD/libs/agno .venvs/demo/bin/python cookbook/05_agent_os/26_teams/proactive_alert.py
```

**Description:** The same interface plus a daemon-thread scheduler that calls
`teams.asend_alert(user_id, text)` 30 seconds after startup, retrying every 15
seconds until a conversation reference exists.

**Result:** With no reference stored yet, the loop printed
`[demo] No conversation reference yet for <user-id>; retrying in 15s.` repeatedly
without failing. After one inbound message it printed
`[demo] Proactive alert delivered to <user-id>` and the alert appeared in the chat
window unprompted.

Delivery was then re-tested in the window opened by `/new`, where the newest
session exists but holds no reference: `send_alert` returned `True` and the alert
was delivered from the previous session's reference. The database confirmed the
window was genuine — the newest session row read `NO REF` at the time of the
send.

This example writes `tmp/teams_alerts.db` and registers agent id
`teams-alerts-agent`, which are **not** the database and agent used by
`basic.py`. A conversation reference stored by `basic.py` is therefore invisible
here; the bot must be messaged once under this example before an alert can be
delivered.

---
