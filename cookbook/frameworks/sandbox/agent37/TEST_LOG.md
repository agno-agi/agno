# Test log: Agent 37 cookbooks

### agent37_execution.py

**Status:** PASS

**Description:** Creates an instance from `agent37-base`, writes and reads a file as UID 1000 in `/workspace` using a variable set at create, reuses the instance, pauses and resumes it, and deletes it.

**Result:** On 17 November 2026 the run completed against Agent 37 in 8 seconds and left no instance in the workspace.

---

### agent37_setup.py

**Status:** PASS (deploy)

**Description:** Packs the public package sources and the shared `Dockerfile`, has Agent 37 build the image in its cloud, and sets the template's entrypoint to `sleep infinity`.

**Result:** On 17 November 2026 `deploy --name agno-sandbox` uploaded a 4.6 MB context, the build finished in about 2.5 minutes and the template was published at revision 2 (the entrypoint change is the second revision). The first instance from the new template took about 15 seconds to create; later ones about 5. `teardown` was not run: the template was left in place for the Claude cookbook.

---

### warm_turns.py --provider agent37

**Status:** PASS

**Description:** Four coordinator turns with the fixture runtime on the `agno-sandbox` template: a cold turn, two warm resumes, and a cold turn restored from the checkpoint.

**Result:** On 17 November 2026 all four turns completed against Agent 37. Turn 1 ran on a new instance (6.2 s), turns 2 and 3 woke the sleeping instance with nothing restored (7.1 s and 6.3 s), and turn 4 ran past the warm window on a new generation restored from turn 3's checkpoint (9.1 s), whose workspace held all four turns. `aretire_computer` removed the last instance and the workspace was empty afterwards.

---

### sandbox_claude_agent37.py

**Status:** NOT RUN

**Description:** Two turns of a sandboxed Claude agent on the `agno-sandbox` template, then removal of the session's sleeping instance.

**Result:** Not run: it forwards the Anthropic credential into the instance, where Agent 37 stores it, and that was not approved yet. The path it takes through the coordinator is the one `warm_turns.py` exercised.

---

### Live provider checks

**Status:** PASS

**Description:** Scripts against Agent 37 covering what its documentation leaves open.

**Result:** On 17 November 2026, on `agent37-base`: commands run as UID 1000 (`node`) in `/workspace` with `HOME=/runtime`, no new privileges, and the `env` given at create; the staging directory is closed to the agent and `sudo` cannot elevate; the exec API accepted commands of 100, 200, 400 and 700 KiB, so staged input moves in 512 KiB chunks; 1 MiB of stdin was staged and 900 KB of output read back; a process a command leaves behind survives the exec call and a sleep and wake; resume took 1.6 s; a timed out command stopped the instance and create then refused the stopped generation. One exec round trip, with its state check, took 0.4 to 0.5 s. On the `agno-sandbox` template a 10.1 MB checkpoint (a 6 MB file and a virtualenv, 976 entries) was captured in 3.6 to 5.1 s and restored into a second instance in 5.1 to 5.7 s with files, ownership, native state and absolute virtualenv links intact, and the agent's background process was running again after the capture's freeze. The first capture on the freshly built template took 94 s; four repeats did not reproduce it, and it is consistent with one request stalling until its read timeout and being rejoined. The chunk request timeout has since been lowered from 60 to 15 seconds.

---

### Local container checks

**Status:** PASS

**Description:** Before a key was available: `Agent37Sandbox` with the instances API replaced by an in-memory fake and every exec command run for real through `docker exec -u root <container> sh -c <command>` in a container from `agno-sandbox:local` carrying this checkout's package.

**Result:** 15 of 15 provider checks and four coordinator turns passed, covering the same ground as the live checks above.

---

### Unit tests

**Status:** PASS

**Description:** `libs/agno/tests/unit/sandbox/test_agent37.py` runs the provider against a fake REST API that executes the real in-instance script. Each guard was removed in turn to confirm a test fails without it.

**Result:** 47 tests pass, and the whole sandbox unit suite passes with `boto3` installed so the AgentCore tests run (624 passed, 1 skipped for `moto`).

---
