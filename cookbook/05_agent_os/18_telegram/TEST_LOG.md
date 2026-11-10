# Test Log: 18_telegram

Tested on 2026-07-24 against Agno source commit
`a7ffb023da5f99a1c43fe28a181e379d855831ba`.

The construction smoke used sentinel-only credentials and loaded Agno from
this worktree through
`PYTHONPATH=/Users/ab/code/worktrees/agno-agent-os-rewrite/libs/agno`.
It did not contact Telegram, OpenAI, Google, or ElevenLabs.

### basic.py

**Status:** PASS

**Test mode:** CONSTRUCTION_SMOKE

**Description:** Constructed the SQLite-backed Telegram AgentOS app with
sentinel `TELEGRAM_TOKEN` and `OPENAI_API_KEY` values, entered its ASGI
lifespan, and checked the standard and interface-owned read-only routes.

**Result:** `GET /health` returned `ok`; `GET /config` returned OS
`telegram-basic-os`, Agent `telegram-assistant`, and Telegram interface route
`/telegram`; `GET /telegram/status` returned `available`; OpenAPI exposed
`POST /telegram/webhook`.

---

### media.py

**Status:** PASS

**Test mode:** CONSTRUCTION_SMOKE

**Description:** Constructed the Gemini, DALL-E, and ElevenLabs media Agent
with sentinel `TELEGRAM_TOKEN`, `GOOGLE_API_KEY`, `OPENAI_API_KEY`, and
`ELEVEN_LABS_API_KEY` values, then entered its ASGI lifespan and checked its
read-only routes.

**Result:** `GET /health` returned `ok`; `GET /config` returned OS
`telegram-media-os`, Agent `telegram-media-agent`, and Telegram interface route
`/telegram`; `GET /telegram/status` returned `available`; OpenAPI exposed
`POST /telegram/webhook`.

---

### multiple_instances.py

**Status:** PASS

**Test mode:** CONSTRUCTION_SMOKE

**Description:** Constructed both Telegram interfaces with distinct sentinel
`ASSISTANT_TELEGRAM_TOKEN` and `RESEARCH_TELEGRAM_TOKEN` values plus a
sentinel `OPENAI_API_KEY`, entered the shared ASGI lifespan, and checked each
mount independently.

**Result:** `GET /health` returned `ok`; `GET /config` returned OS
`telegram-multiple-os`, Agents `telegram-concise-assistant` and
`telegram-web-researcher`, and interface routes `/assistant` and `/research`.
Both `GET /assistant/status` and `GET /research/status` returned `available`.
OpenAPI exposed `POST /assistant/webhook` and `POST /research/webhook`.

---

## Validation

- All three examples passed construction, lifespan, health, configuration, and
  interface-status checks with worktree-pinned source.
- Recursive pattern validation checked exactly 3 Python files with 0
  violations.
- Targeted Ruff format and check passed.
- Python compilation, exact inventory, README link parity, retained-source,
  stale-surface, Unicode/emoji, status-mode, and `git diff --check` gates
  passed.
- Live webhook delivery, Telegram command registration, model inference, and
  media transfer require real provider credentials plus a public HTTPS
  callback and were not claimed by this smoke test.
