# Test Log: 32_github

### basic.py --check (2026-11-11)

**Status:** PASS

**Description:** Sends five signed deliveries in process to an AgentOS serving the GitHub interface for `agno-agi/agno`: a new issue, a redelivery of it with the same `X-GitHub-Delivery`, the same issue on another repository, one sent by a GitHub App's bot account, and one signed with the wrong secret.

**Result:** The new issue reached the handler and returned 202 `recorded` with the handler's result under `result`. The redelivery returned the same answer with `"duplicate": true` without calling the handler. The other repository and the bot returned 200 `ignored` with their reasons, and the wrong signature returned 403. The handler ran once.

---

### basic.py, served for a real repository webhook (2026-11-11)

**Status:** PASS

**Description:** Served `basic.py` for a private test repository through ngrok, created a repository webhook for `issues` and `issue_comment` with `gh api`, then opened an issue, commented on it and edited its title. Responses were read from the webhook's delivery log and ngrok's inspector.

**Result:** The first ping returned 403 `Invalid signature` because the server was started with a different secret than the webhook's. After both used the same secret, pings returned 200 `pong`. `issues.opened` returned 202 `recorded` and the server printed the issue. `issue_comment.created` returned 202 `recorded`, and `issues.edited` returned 200 `ignored` ("issues.edited is not handled").

---

### basic.py, served for a GitHub App (2026-11-11)

**Status:** PASS

**Description:** Created a GitHub App on a personal account (Issues read and write, Contents and Metadata read-only; Issues and Issue comment events; webhook to `<ngrok URL>/github/events`), installed it on a private test repository, deleted the earlier repository webhook, and served `basic.py` with `GITHUB_APP_ID` and `GITHUB_APP_PRIVATE_KEY_PATH`. Opened an issue.

**Result:** The `issues.opened` delivery was marked as coming from the App (`X-GitHub-Hook-Installation-Target-Type: integration`), carried installation `180936050`, and returned 202 `recorded`. The handler minted an installation token from the App's private key and read the issue back: "Read #4 with installation 180936050's token: open, 0 comments". The App's `installation` events returned 200 `ignored`. A first run without `GITHUB_APP_ID` received the event but skipped the read-back silently; the cookbook now prints at startup whether App credentials are configured.

---

### basic.py, served for a GitHub App after review changes (2026-11-11)

**Status:** PASS

**Description:** Served the updated `basic.py` for the same GitHub App and private test repository through ngrok: the handler records the event and returns, and reads the issue back afterwards. Opened an issue, then replayed its delivery from ngrok's inspector with the same `X-GitHub-Delivery`.

**Result:** The delivery returned 202 `{"status": "recorded", "delivery_id": ..., "result": {"received": 1}}` straight away, and the server printed the event, then "Read #6 with installation 180936050's token: open, 0 comments". The replay returned the same answer with `"duplicate": true`; the handler did not run again. `GET /github/status` returned `{"status": "available"}`.

---
