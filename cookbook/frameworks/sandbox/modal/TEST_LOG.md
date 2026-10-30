# Test log: Modal cookbooks

### sandbox unit tests

**Status:** PASS

**Description:** `libs/agno/tests/unit/sandbox/test_modal.py`: 17 tests against a fake Modal SDK that runs each sandbox's commands on the host under a temporary root. They cover constructor validation, the missing-extra error, idempotent create with identity tags, concurrent first creates sharing one image resolution, a lost create reply found by name, refusing a generation with other configuration or another namespace, refusing to recreate a stopped generation while allowing a destroyed one, the bounded runner, stopping compute after a timed-out or lost command, leaving compute alone after a failed runtime RPC, dropping to UID 1000, checkpoint round trips into a fresh generation (symlinks, native mode, default exclusions), stopping a partially restored sandbox, rejecting an export that escapes its root, the capture byte limit, and the sync wrappers. `test_sandbox_param.py` checks that `ModalSandbox` carries the harness settings.

**Result:** 538 sandbox unit tests passed on 22 October 2026. The Docker checkpoint logic moved into `checkpoint.py` so both providers share it, and the Docker transfer integration tests still passed against `python:3.12-slim` (4 passed). `setpriv` and `tar` are present in the shared base image.

---

### modal_session.py

**Status:** PASS

**Description:** Fixture harness, no model calls, run with `.venvs/demo/bin/python` on 22 October 2026. The first run built the runtime image on Modal from the shared `Dockerfile` with its entrypoint cleared, created the sandbox and started turn 1. Its first poll then failed: `modal.Sandbox.from_id` hung until the 75 second transport timeout, and the cookbook destroyed the sandbox on the way out. The rerun completed both turns in 32 seconds, with turn 2 finding the same sandbox through `create` and the workspace holding `fixture-effects.txt` and `fixture-env.txt`. Standalone checks against the same account showed commands running as UID 1000 through `setpriv`, about 3 seconds per exec, start in 3 seconds and the first poll returning the finished result in 5 seconds.

**Result:** Pass on rerun. The single `from_id` stall right after the first image build did not recur in four later runs.

---

### modal_session.py --replace

**Status:** PASS

**Description:** Fixture harness. Turn 1 ran, capture produced a 416 byte checkpoint, the sandbox was destroyed, and generation 2 was restored on a new sandbox, where turn 2 completed with both workspace files present. Both sandboxes were destroyed and `modal container list` showed nothing running afterwards. Took 49 seconds.

**Result:** Checkpoint capture and restore work on Modal.

---

### modal_session.py --harness codex

**Status:** PASS

**Description:** Codex wrote and ran `primes.py` in turn 1. In turn 2 on the same sandbox it recalled the codeword BLUE-HERON, then added and ran `test_primes.py`. Took 44 seconds.

**Result:** The conversation and workspace survive on a warm sandbox.

---

### modal_session.py --harness codex --replace

**Status:** PASS

**Description:** After turn 1, capture produced a 52,861,213 byte checkpoint, the sandbox was destroyed, and generation 2 was restored on a new sandbox. Turn 2 recalled BLUE-HERON and ran its test. Took 454 seconds against 44 without `--replace`. A separate measurement on the same account moved 50 MB at about 1.5 MB/s each way, 33 seconds for capture and 34 for restore, so the transfer accounts for about a minute of the difference.

**Result:** The conversation and workspace survive a restore onto a fresh sandbox. Large checkpoints are slow over Modal exec.

---

### modal_session.py --harness claude

**Status:** PASS

**Description:** Rerun with a valid ANTHROPIC_API_KEY. Claude wrote and ran `primes.py` in turn 1. In turn 2 on the same sandbox it recalled BLUE-HERON, then wrote and ran `test_primes.py` (6 tests passed). Took 55 seconds. The first attempt failed only because the exported key returned 401 from Anthropic.

**Result:** The conversation and workspace survive on a warm sandbox.

---

### modal_session.py --harness claude --replace

**Status:** PASS

**Description:** Turn 1 ran, the sandbox was checkpointed and destroyed, and generation 2 was restored on a new sandbox, where Claude recalled BLUE-HERON and its tests passed. Both sandboxes were destroyed. Took 71 seconds.

**Result:** The conversation and workspace survive a restore onto a fresh sandbox.

---

### sandbox_claude_modal.py

**Status:** PASS

**Description:** Turn 1 returned `hello`; turn 2 named `hello.py`. Took 61 seconds. The first version left the session's warm sandbox running after the script exited, until its one hour lifetime. The script now retires it at the end: the rerun printed `Warm sandbox removed: True` and no sandbox was left running.

**Result:** Pass, with no sandbox left behind.

---

### sandbox_claude_modal_agentos.py

**Status:** PASS

**Description:** Served against the local `pgvector` (5532) and `agno-redis` (6379) containers. Two background turns on one session through `/agents/coder/runs`, polled to completion: turn 1 returned `hello`, turn 2 named `hello.py`. Turn 2's run metadata shows `resumed: true` at epoch 2 with a committed checkpoint. Stopping the server left that warm sandbox running; it was terminated by hand. The README now says a process that exits after a turn leaves its warm sandbox running for up to `lifetime`.

**Result:** The queue, coordinator and Modal path work end to end.

---

### modal_load.py

**Status:** PASS

**Description:** Concurrent sessions, each created, running a fixture turn, running one command and destroyed, all started at once with `cpu=0.25` and `memory_mb=512`. The first four rows ran before the provider shared image resolution between concurrent creates; rows marked pre-resolved resolved it once by hand before the burst. The last row is the stock cookbook after that fix, with the image already built.

**Result:** On 22 October 2026:

| Sessions | Turn | Completed | Peak alive | Create p50 / p90 | Turn p50 | Command p50 | Destroy p50 | Total time |
|---|---|---|---|---|---|---|---|---|
| 20 | 5 s | 20 | 20 | 31.9 s / 33.6 s | 7.94 s | 2.41 s | 0.76 s | 46 s |
| 100 | 10 s | 100 | 71 | 98.9 s / 109.0 s | 13.86 s | 2.54 s | 0.77 s | 127 s |
| 100, pre-resolved | 10 s | 100 | 100 | 6.5 s / 9.5 s | 13.78 s | 2.73 s | 0.85 s | 29 s |
| 300, pre-resolved | 10 s | 300 | 300 | 12.3 s / 19.7 s | 16.38 s | 2.84 s | 0.98 s | 40 s |
| 300, after the fix | 10 s | 300 | 300 | 22.1 s / 28.7 s | 17.51 s | 3.60 s | 0.81 s | 49 s |

No call failed. Before the fix, every concurrent first create looked up the app and built the image itself, and those calls queued behind each other: resolving once first cut 100 sessions from 127 to 29 seconds. Now the first create resolves and the rest wait for it, which adds one resolve of about 10 seconds to the burst. A run right after the package sources change includes a full image rebuild, about 110 seconds on the first create.

---

### warm_turns.py --provider modal

**Status:** PASS

**Description:** Fixture runtime, four turns. Turn 1 was cold. Turns 2 and 3 resumed the warm sandbox with nothing restored. After the shortened window expired, turn 4 was cold and restored from turn 3's checkpoint. The warm sandbox left by turn 4 was removed. Took 91 seconds.

**Result:** Warm resume and cold restore both work on Modal.

---

### Concurrent runs

**Status:** PASS

**Description:** The first version of `modal_image.runtime_image()` deleted and recopied one shared build context under `~/.agno/sandbox/modal-context`, so cookbooks started at once failed within seconds with `FileExistsError` or `FileNotFoundError`. Each process now stages its own temporary context and removes it at exit. Two `modal_session.py` runs, `sandbox_claude_modal.py` and `modal_load.py --sessions 100` then ran at once and all passed, sharing one image build, and no context directory was left behind.

**Result:** Cookbooks can run at the same time.

---
