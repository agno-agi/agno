# Sandbox cookbook test log

## October 20, 2026: virtualenv links and uncheckpointable turns

### Checkpoint archive and transfer unit suites

**Status:** PASS

**Description:** Ran `libs/agno/tests/unit/sandbox` with `PYTHONPATH=libs/agno`. New cases cover a Linux virtualenv's absolute interpreter link and its relative aliases through capture, validation, host restore and in-computer restore; a host secret behind an absolute link is neither read at capture nor reachable after a host restore; FIFOs, escaping links, hardlinks to excluded credentials and entry limits raise `CheckpointContentError`; the Docker combine and split path keeps absolute link targets verbatim; the AgentCore round trip recreates an absolute link in the replacement computer.

**Result:** 568 passed. Every new case failed on the unchanged code first, including the AgentCore round trip with the in-computer restore flag reverted.

---

### Coordinator integration with Docker and PostgreSQL

**Status:** PASS

**Description:** Ran `test_coordinator.py`, `test_transfer.py`, `test_docker.py` and `test_checkpoint_access.py` against a fresh PostgreSQL database on port 5532 and a runtime image built from this tree with `build_image.py`. A turn runs `python -m venv --without-pip /workspace/.venv`; the next turn, on a fresh generation restored from the checkpoint, runs `/workspace/.venv/bin/python`. A turn that leaves a FIFO in the workspace ends in `ERROR` with `retryable: False`, the session goes back to idle with the previous checkpoint, and the next run is accepted.

**Result:** 98 passed, 23 skipped (opt-in S3 and live repository cases). On the unchanged code the virtualenv turn failed with `Unsafe checkpoint symlink 'workspace/.venv/bin/python' -> '/usr/local/bin/python'` and the FIFO turn left the session finalizing. No model calls were made.

---

## October 16, 2026: agent repository configuration

### repository_workspace.py

**Status:** PASS

**Description:** Imported `cookbook/frameworks/sandbox/repository_workspace.py` with a test PostgreSQL URL, explicit checkpoint directory, runtime image, and public GitHub repository. Constructed the agent and inspected its runtime submission configuration.

**Result:** `repository=Repository(url, branch)` reached `config.repository`; no per-run repository option was needed. This was a construction/configuration smoke test, without a live Codex or Claude model call.

---

### Repository and external-agent regression suites

**Status:** PASS

**Description:** Ran `libs/agno/tests/unit/sandbox` and `libs/agno/tests/unit/agents` using the development environment and a temporary dummy AWS profile.

**Result:** 1,030 passed; one existing deprecation warning. Repository cases cover local Git branch resolution, shallow detached checkout, engineer commits and edits across resume/replacement, missing and mismatched markers, configuration validation without subprocess/network calls, both harness cwd settings, sync/async run rejection, configuration fingerprints, fixed errors, cancellation drain, and cleanup. Credential checks inspect argv, workspace/runtime files, error text, and captured checkpoint bytes for both raw and encoded token leakage.

---

### Repository integration

**Status:** PASS

**Description:** Ran PostgreSQL state-store tests, repository coordinator checks with a Docker runtime containing the feature source, and the opt-in public GitHub fetch.

**Result:** 122 distinct PostgreSQL cases passed across sync/async adapters, with 12 existing conditional skips, counted across the full run and corrected fixture rerun. Four Docker/PostgreSQL repository cases passed: retryable preparation failure plus live public checkout, warm reuse, cold replacement, edit/pin retention, and changed/removed configuration refusal. One standalone `live` public GitHub fetch passed without credentials. Run metadata matched the marker. No private GitHub or live model calls were made.

---

### Format and validation

**Status:** PASS

**Description:** Ran the full `scripts/format.sh` and `scripts/validate.sh`; removed unrelated baseline formatter changes from the feature diff.

**Result:** Format passed. Full validation passed in the existing clean Python 3.10 environment. Development Python 3.12 validation reported the same 40 errors in 14 files as untouched main `ab0e2d233a`, with identical diagnostics and zero introduced. `git diff --check` passed.

---

## October 16, 2026: first-turn metadata override

### Repository metadata overrides and transport

**Status:** PASS

**Description:** Added `metadata.repository` with exactly one full commit SHA or valid branch name. Validation refuses URL overrides before Git/network access. The first turn uses the override; later turns and restored computers retain the marker's pin. A branch override records its effective branch and retains the original configured branch internally for configuration mismatch checks.

**Result:** All 511 sandbox unit tests passed. Tests cover old-commit checkout after the default branch advances, a different branch, same/different later overrides, restored checkpoints, URL refusal, and sync/async harness, coordinator, and runtime-client forwarding. Six PostgreSQL cases passed across both adapters for default, commit, and branch pin publication. One live AgentOS route/Redis/PostgreSQL/Docker test passed: middleware `request.state.metadata` reaches the queued payload and runtime, the requested commit is published, later overrides are ignored, and a URL override returns 400 before allocation. No live model calls.

---

### Override format and validation

**Status:** PASS

**Description:** Ran the full format script and full validation script in the clean Python 3.10 environment after the forwarding changes.

**Result:** Both passed; `git diff --check` passed. Unrelated baseline formatter edits were removed. The earlier development-environment baseline comparison above belongs to the initial revision and was not rerun for this addition.

---

## October 16, 2026: repository review fixes

### Preparation and execution boundaries

**Status:** PASS

**Description:** Reproduced the execution-deadline failure with a delayed local Git fetch, missing native/marker/checkout state, and the non-repository token compatibility regression before applying fixes. Verified that preparation cancellation drains filesystem work and reports a retryable preparation failure, while timeouts or marker deletion after the harness starts remain terminal. Repository agents still reject publishing tokens before Git starts; other sandboxed agents retain their existing token support.

**Result:** The full sandbox unit suite passed 517 cases. A subsequent focused repository run passed 77 cases, including two additional boundary regressions (519 distinct unit cases total). No live models were used.

### Metadata and restore integration

**Status:** PASS

**Description:** Ran repository integration tests against PostgreSQL, Redis, and a rebuilt Docker fixture runtime, including public GitHub fetches. Verified missing native root, marker, and checkout recovery across both PostgreSQL adapters, pin publication, preserved engineer edits, and the AgentOS request-state metadata path.

**Result:** All 19 selected integration cases passed. Inbound metadata persists on successful and failed runs without overriding reserved runtime fields or leaking into later turns. Missing state before execution remains retryable and the following turn restores the last committed checkpoint without repeating the failed turn's tools.

### Review format and validation

**Status:** PASS

**Description:** Ran the full format and clean Python 3.10 validation scripts after the review fixes. Checked the diff for whitespace errors.

**Result:** Format, validation, and diff checks passed. Unrelated baseline formatter changes were removed. The earlier development-environment diagnostic comparison was not rerun. No live-model calls or private GitHub requests were made.

---
