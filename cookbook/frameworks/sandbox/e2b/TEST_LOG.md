# Test log: E2B cookbooks

### e2b_template.py

**Status:** PASS

**Description:** Builds the `agno-sandbox` E2B template from this checkout with E2B SDK 2.56.0, 2 vCPU and 4 GiB.

**Result:** On 16 October 2026 the build finished in about a minute. A live check found that E2B gives `user` passwordless sudo after the template's build steps (a `NOPASSWD` line in `/etc/sudoers` and the `sudo` group), so removing it at build time does not hold. `E2BSandbox.create` now strips every setuid bit as root; afterwards `sudo -n true` and `su` fail for `user`, `/var/lib/agno-sandbox` cannot be listed by `user`, `HOME` is `/runtime`, and commands do not see the runtime token.

---

### e2b_session.py

**Status:** PASS

**Description:** `E2BSandbox` against the live template. Two turns on one generation by default; `--pause` pauses and resumes between turns; `--replace` checkpoints, destroys, and restores generation 2 on a fresh computer; `--runtime-port 8765` sends start/poll to the runtime server over the public E2B URL.

**Result:** On 16 October 2026:
- Fixture passed on all six paths: default, `--pause`, `--replace`, and each again with `--runtime-port 8765`. The `--replace` checkpoints were 537 bytes and restored both fixture files.
- Claude passed on the default path and with `--replace`. Turn 2 answered "The codeword you asked me to remember is **BLUE-HERON**" on the same computer and on a restored one (checkpoint 78,801 bytes), and its `test_primes.py` passed against turn 1's `primes.py`.
- Codex failed on both paths before #11050, which creates `CODEX_HOME` and logs Codex in.

On 19 October 2026, rebased on main with the template rebuilt from it:
- Codex passed on the default path and with `--replace`. Turn 2 answered "The codeword was `BLUE-HERON`" on the same computer and on a restored one, and wrote and ran `test_primes.py`. The Codex checkpoint was 53,060,220 bytes; streaming it over the SDK's default HTTP/2 failed with `too_many_data_frames`, so archives now come out over HTTP/1.1. A probe found HTTP/2 reads failing from 4 MiB with a slow reader and from 16 MiB with a fast one, and HTTP/1.1 reads of 16 and 64 MiB passing; writes passed on both.
- Final code, all paths: fixture passed on default, `--pause` and `--replace`, each with and without `--runtime-port 8765` (checkpoints 530 and 533 bytes). Claude passed on default, `--pause` and `--replace` (checkpoint 78,672 bytes), recalling the codeword on the same, the resumed and a restored computer; Codex passed on default.
- Fixture `--replace` passed six runs in a row. Before the listing fix, three of nine runs failed with "E2B sandbox disappeared after creation" and left their computer running: a listing showed the new computer and the next one did not.

No E2B sandboxes were left running after the runs.

---

### sandbox_claude_e2b.py

**Status:** PASS

**Description:** `ClaudeAgent(sandbox=E2BSandbox("agno-sandbox"))` with Postgres, two turns on a new session through the session coordinator.

**Result:** Turn 1 answered `hello`; turn 2 answered `hello.py`, the file from turn 1. The only warning is the expected one about the host-local default checkpoint directory. Rerun on 19 October 2026 on main, where the coordinator looks a generation up with `for_create` before every cold create; it passed after `E2BSandbox.afind` accepted that argument. On main the coordinator keeps the computer warm after a turn, so the run left one paused sandbox, which was killed by hand.

---

### warm_turns.py --provider e2b

**Status:** PASS

**Description:** The provider-neutral coordinator example with `E2BSandbox`: four fixture turns of one session showing the warm path and the cold fallback.

**Result:** On 19 October 2026: turn 1 cold on a new computer (21.0 s); turns 2 and 3 warm, resuming the paused computer with nothing restored (9.2 s, 10.5 s, `resumed=True`); after the shortened window, turn 4 cold on generation +1 restored from the checkpoint (13.5 s), whose workspace held all four turns. The script retired the last warm computer.

---

### sandbox_claude_e2b_agentos.py

**Status:** PASS

**Description:** The same agent behind AgentOS with a durable Redis-coordinated queue and `runtime_port=8765`. Two background runs submitted to one session over HTTP and polled.

**Result:** Both runs went PENDING, RUNNING, COMPLETED. Turn 1 answered `hello`; turn 2 answered `hello.py`.

Rerun on 19 October 2026 on main: turn 1 completed with `hello` on a new computer (`resumed=False`), and turn 2 completed with `hello.py` after resuming the computer turn 1 left paused (`resumed=True`). On main the POST with `background=true` answers with an event stream rather than a JSON run id, so the `curl` lines in the docstring, shared with the Docker and AgentCore cookbooks, no longer show the run id to poll; the runs were read from the session's runs endpoint. The session's paused warm computer was killed by hand after the run.

---

### e2b_load.py

**Status:** PASS

**Description:** Concurrent fixture sessions (no model, 3 s turns) on the live template with `runtime_port=8765`: create, turns over three transports on the same computers, pause/resume, checkpoint capture, and restore onto a fresh generation. Run with 2, 8 and 25 sessions.

**Result:** On 16 October 2026, 8 sessions:

| phase | result |
|---|---|
| create (boot, hardening, runtime server) | p50 6.9 s, max 8.9 s |
| exec, poll loop | 3.9 requests/turn, 11.6 E2B calls/turn, idle poll p50 1,080 ms |
| exec, long-poll | 2.0 requests/turn, 6.0 E2B calls/turn, idle poll p50 1,076 ms |
| http, long-poll | 2.0 requests/turn, 0 E2B calls/turn, idle poll p50 285 ms (412 ms before the client was pooled) |
| pause / resume | p50 0.7 s / 1.9 s |
| capture / restore | p50 2.2 s / 1.3 s (567-byte checkpoints) |

With 25 sessions the account's limit of 20 concurrent sandboxes held: 20 created and 5 failed with `SandboxError` carrying E2B's 429; the other phases matched the 8-session run at 20 sessions. Every run ended with no sandbox left in its namespace.

Rerun on 19 October 2026 on main with 8 sessions: create p50 9.6 s, http idle poll p50 397 ms, capture/restore p50 2.3 s / 1.1 s, nothing left running.

Create dominates. Each exec request costs three E2B calls (an identity check, staging the request, the command); HTTP costs none. The runtime server's client is pooled per event loop, so requests reuse TLS connections: against one computer, `/health` took p50 274 ms pooled and 411 ms with a new connection each time. The remaining floor is E2B's proxy path into the computer; TCP connect to E2B from this host is about 20 ms.

---

### Unit tests

**Status:** PASS

**Description:** `libs/agno/tests/unit/sandbox/test_e2b.py` against a fake E2B cloud and the real command runner: identity metadata, lost create replies, duplicate cleanup, configuration mismatch, namespace checks, setuid hardening, staged stdin, killing compute on uncertain commands, pause/resume, destroy, runtime server token, checkpoint round trip, exclusion and size checks, failed restore, and import isolation.

**Result:** 52 passed, including a handed-out computer kept when listings omit it, a runtime start failure killing a new computer but not an existing one, racing creates of one generation with lagging listings sharing one computer, a listing failure or cancellation after create killing the new computer, listings that lag or disagree after a create, a computer that never appears being killed, a refused create not waiting, checkpoint downloads over HTTP/1.1, `afind(for_create=True)`, a failed freeze resuming what it stopped, an import without `pwd`, a pooled runtime client closed with its event loop, and concurrency against a fake cloud that interleaves calls: five creates of one generation share one computer (the four duplicates are created and killed), twenty sessions get twenty computers each hardened once, creates past the concurrency limit fail with `SandboxError` and leave nothing, concurrent commands and checkpoints use separate staged files, and concurrent pause/resume keep each generation.

---
