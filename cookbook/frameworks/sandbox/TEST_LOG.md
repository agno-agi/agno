# Sandbox test log

### docker_execution.py

**Status:** PASS

**Description:** Real Docker: create, workspace write/read, reuse, deletion. Credential-free local infrastructure only.

**Result:** Passed on 11 October 2026 with `python:3.12-slim`, resolved digest `python@sha256:05cda9777409a9c3ffddd94a4c476b79f0769a0b4857f0c7ed9226b6800b0d6f`. Used the established `.venvs/claude-dx-validation` environment. No model calls, hosted-provider calls or clean-wheel install performed.

---

### execution provider regression tests

**Status:** PASS

**Description:** `libs/agno/tests/unit/sandbox`: 17 tests covering input validation, explicit environment, deterministic identity, lost creation response, ownership, command limits, failure cleanup and sync wrappers. `libs/agno/tests/integration/sandbox/test_docker.py`: 5 tests using real local containers, including non-root/read-only/no-mount/network configuration, file reuse, exit codes, timeout, output limits, cancellation, concurrent creation/deletion.

**Result:** 17 unit tests and 5 real-container tests passed. Initial real deletion race failed when Docker returned “removal already in progress”; fixed by bounded reconciliation, then the complete suite passed. Required formatting and validation passed. This evidence establishes execution-provider primitives, not durable AgentOS session recovery or live SDK compatibility.

---

### checkpoint_files.py and checkpoint regressions

**Status:** PASS

**Description:** Capture conversation metadata, native files and ignored/untracked workspace bytes; upload to an immutable object directory; delete source roots; restore through another store instance. 28 checkpoint tests cover checksums, corruption, missing objects, concurrent upload, partial cleanup, limits, path traversal, hardlink/device rejection, composed symlink escape/cycles, oversized PAX metadata and cancellation draining.

**Result:** The cookbook and all 45 sandbox unit tests (28 checkpoint + 17 Docker) passed in `.venvs/claude-dx-validation`. Both required scripts passed. Actual filesystem operations were exercised; no Docker-to-checkpoint transport, live SDK, production shared filesystem or host-loss guarantee was tested by this layer.

---

### runtime_journal.py and runtime protocol acceptance

**Status:** PASS

**Description:** 19 new runtime/client tests cover duplicate dispatch, one-writer locking, event replay, dead-worker uncertainty, incomplete frames, execution timeout, protocol/identity validation, sync/async clients, poll cancellation and a final-event/completion race. All 64 sandbox unit tests passed on Python 3.12 and Python 3.9. Real Docker: 11 combined provider/runtime cases plus one SDK-construction case passed; the reconnect cookbook passed. The construction check instantiates both adapters without authenticating or calling models.

**Result:** Runtime image `sha256:616c3e78f2e95c6e81eda400222ec142ebfffa2383412fcede3a97f966b42317`, Claude SDK 0.2.165, Codex SDK 0.162.1, SQLAlchemy 2.0.52. Required scripts passed in the established validation environment. The initial image build hit an HTTP Debian mirror checksum mismatch; switching the official mirror to HTTPS resolved it with verification retained. The initial SDK-construction assertion inspected a nullable configuration field instead of the engine; corrected the assertion and reran successfully. No live model calls, hosted provider calls or full AgentOS sandbox durability acceptance.

---

### replace_computer.py and checkpoint transfer

**Status:** PASS

**Description:** The cookbook clones a local Git fixture, edits code, runs tests, captures ignored/untracked files and native-state fixtures, destroys compute, restores generation 2, reruns tests, and retrieves an artifact after all compute is gone. 71 sandbox unit tests passed on Python 3.12 and 3.9. The combined 16 real Docker tests cover provider/runtime behavior plus replacement recovery, failure cleanup, stopping a partial restore and a 40 MiB archive beyond the command-output limit.

**Result:** Both required scripts and the cookbook passed. Two real probes established that ordinary container tmpfs produces an empty successful daemon copy, while Docker-managed bounded tmpfs volumes preserve data. The provider now uses the latter and the transport rejects the former. A first restore failed against the read-only container root; restore now targets the writable volumes directly. A synthetic tar fixture initially gave directories non-traversable permissions; corrected the fixture. No live SDK conversation, paid provider, host-loss shared-storage deployment or atomic AgentOS terminal commit was certified.

---

### runtime control transport recovery

**Status:** PASS

**Description:** Runtime start/poll now use a restricted provider RPC operation. A lost control response leaves the session computer available to its current coordinator; arbitrary shell commands retain stop-on-failure behavior. A real-container regression discards a poll response, reconnects through another client and verifies exactly one fixture effect.

**Result:** 74 sandbox unit tests passed on Python 3.12 and 3.9; all 17 real Docker provider/runtime/transfer cases passed. Required scripts passed. This fixes an integration risk where a stale polling request could stop compute during another coordinator's checkpoint. No live model or hosted-provider calls.

---

### durable_completion.py

**Status:** PASS

**Description:** Real local Postgres, unique fixture tables and immutable local archive; staged output remains RUNNING until checkpoint staging and cleanup acknowledgement permit atomic publication. No model calls or real compute in this cookbook.

**Result:** Passed. Companion integration suite: 24 passed across PostgresDb and AsyncPostgresDb, including independent owners, lease expiry, queue attempt fencing, transaction rollback, lost acknowledgement, immutable staged output, deleted/recreated session isolation, external cancellation, and sync entry points. Review found and fixed native metadata overwriting service fields and old-session recovery reuse. Provider shutdown and archive verification remain coordinator responsibilities.

---

### Strict native recovery and local persistence

**Status:** PASS

**Description:** Missing Claude/Codex native state fails without starting another conversation; new sessions still start normally. Failed local writes cannot emit terminal success. Runtime readback checks include a real SQLite round trip, with empty-event normalization handled by the RunOutput serializer.

**Result:** 575 combined external-agent/sandbox unit cases passed on Python 3.12; 8 real Docker runtime cases passed with the rebuilt image, including installed SDK construction with both strict flags. No authenticated model calls. The combined suite emitted an aiosqlite background-thread teardown warning from an existing async test environment; the focused runtime tests passed without it. Required scripts passed.

---

### session_computer.py

**Status:** PASS

**Description:** Two credential-free runtime turns on real Docker and Postgres, using the synchronous coordinator API. The second turn restores the previous files into different compute. Both computers are retired after durable publication.

**Result:** Cookbook passed. Integrated failure cases cover lost start/cleanup/commit acknowledgements, checkpoint outages, compute loss before checkpointing, identity mismatch on restore, unchanged configuration on reattach, cancellation, same-session contention, and terminal-event ordering. Real Postgres regressions additionally cover atomic rejection with no phantom run, explicit migration for older non-sandbox history, and cancellation drainage while a provider operation holds ownership rows. Self-review caught destructive RunOutput parsing during terminal event construction and fixed it by copying the input dictionary. No live models or hosted providers were used. Final counts are recorded in the PR validation notes.

---

Coordinator review follow-up: native transcript-mirror warnings and lost pre-checkpoint compute cannot publish success or trigger model execution retries. Tool audit history is retained on failure. Runtime output cannot replace the original submitted input or trusted service metadata. Added 2 real mirror-warning cases and 2 metadata/input boundary cases; final store suite: 32 passed. Focused finalization/mirror cases: 4 passed. Required scripts passed again.

### agentos.py and durable API integration

**Status:** PASS

**Description:** Real AgentOS HTTP requests with dedicated Postgres, Redis and Docker fixture execution. Foreground, background, streaming, idempotency/conflicts, same-session admission, retained indexed replay after Redis cleanup, finalization-only retries, active/retry cancellation, retry exhaustion cleanup, SDK background submission, missing-queue rejection, and detached SDK cancellation are covered. The actual cookbook server was also started and exercised over HTTP, then stopped; its temporary database was removed.

**Result:** 704 combined external-agent/sandbox/queue unit cases passed. The integrated suite passed 88 cases; its 9 Docker/transfer cases required a separate image environment variable and all 9 subsequently passed. 40 real Postgres cases cover both database adapters. Review found and fixed terminal ticket publication before sandbox cancellation cleanup, retained events missing transport indices, and pending preparation racing an already-claimed queue attempt. Required formatting/validation passed in the established environment. No live model or hosted-provider calls; local shared-storage deployment is not host-loss certification.

---

Python 3.9 follow-up: 76 sandbox unit tests, 40 real Postgres cases and 12 AgentOS HTTP cases passed. The first HTTP collection lacked the optional Redis dependency; installed Redis 6.4.0 in the dedicated environment and reran successfully.

### download_artifact.py and completed checkpoint inspection

**Status:** PASS

**Description:** Real HTTP server and cookbook download with byte comparison after compute removal. Exact owner/agent scope, configured HTTP user isolation, traversal/native-path rejection, file-size limits, replacement-session isolation, corrupted bytes, mismatched manifest, binary content, symlink rejection, paginated listing and last-completed reads during a new turn are covered.

**Result:** 81 sandbox unit tests plus 7 real artifact API cases passed on both Python 3.12 and Python 3.9. The real-server cookbook passed; its process and temporary database were removed. Required scripts passed. A pytest duplicate module basename and an imported-fixture lint collision were corrected before the final runs. HTTP identity isolation uses preverified request state; JWT signature verification is covered by the existing auth tests, not this fixture. No model or hosted-provider calls.

---

### retire_recovery.py and explicit lifecycle operations

**Status:** PASS

**Description:** Real-server cookbook retires its fresh fixture session, downloads its retained artifact, purges published recovery checkpoints, then deletes conversation history. Postgres tests exercise both adapters, exact-owner scope, active-session refusal, partial storage cleanup retry, foreign-reference refusal, lost commit acknowledgement, bulk-delete atomicity and the permanent session tombstone. HTTP tests cover retirement/cancellation reconciliation and a submission racing deletion.

**Result:** 197 focused database/sandbox/queue unit cases passed. Twenty lifecycle/database cases passed across both Postgres adapters; four lifecycle HTTP cases and twelve AgentOS regression cases passed after classifying retired-session input as a permanent queue failure. Required scripts passed in the established environment. Review fixed an early acknowledgement race with the queue cancellation worker. A test's ordinary-session fixture initially omitted its required creation timestamp and was corrected. No live model or hosted-provider calls. Unreferenced upload retention, warm reuse and fleet quotas are outside this published-checkpoint deletion slice.

---

### upload_input.py

**Status:** PASS

**Description:** Actual fixture AgentOS server, dedicated Postgres/Redis and rebuilt Docker runtime. Uploaded file bytes were stored in run input, checkpointed, restored into a second computer and downloaded unchanged. No model calls.

**Result:** Cookbook passed. Media/AgentOS integration: 19 passed; final media validation: 9 passed after adding malformed-array cases. Sandbox/external-agent units: 621 passed; queue regressions: 110 passed; Python 3.9 sandbox units: 94 passed. Required format and validation scripts passed. Model interpretation and hosted-provider behavior remain untested.

---

### coding_workload.py / workload_fixture.py

**Status:** PASS

**Description:** Real disposable Docker computers, network disabled and no model credentials. Created and cloned a local Git fixture, installed a local wheel into a copied-interpreter virtual environment, reproduced a failing test, edited code, passed tests, ran an HTTP application and committed SQLite data. Stopped the application, checkpointed, destroyed compute and restored into a second generation.

**Result:** Hashes for tracked, untracked and ignored files and database bytes matched; Git HEAD and the installed dependency survived; tests passed and the application restarted with the persisted database row. This is infrastructure acceptance, not model/harness conversation acceptance or a claim about arbitrary live-database snapshots.

---

### Combined stack and installed-wheel acceptance

**Status:** PASS

**Description:** Combined sandbox core plus queue acceptance-ordering fix and sandbox idempotency compatibility. Python 3.12, real dedicated Docker/Postgres/Redis, fixture harness. Fresh locally built wheel installed into a new service environment and its site-packages import path verified.

**Result:** 816 focused unit tests passed; 175 integration tests passed and 4 intentionally inapplicable controlled-interleaving backend variants skipped. The isolated wheel passed the actual HTTP background/replay, artifacts, retirement/recovery/history deletion, attachment restoration and coding-workload exercises. Required format/validation scripts passed. This verifies an unreleased local wheel, not a published package. No live models or hosted providers were exercised.

---

### Hosted allocation foundation

**Status:** PASS

**Description:** Verified service-side allocation tokens, lost-response intents, shared capacity and stale-token fencing on real synchronous and asynchronous Postgres adapters, including engines configured for repeatable read. Docker rejects unset process/filesystem limits before allocation.

**Result:** 10 real Postgres tests and 96 sandbox unit tests passed. Required format and validation scripts passed. No hosted provider calls were made; this is allocation contract evidence, not hosted acceptance.

---

### Hosted runtime and portable transfer

**Status:** PASS

**Description:** Local Docker bridge with real Postgres verifies UID/GID 1000, `no_new_privs`, inaccessible root control files, runtime events, background-writer freeze, native/workspace/symlink restoration, and rejection/teardown of imports into used computers. Provider-contract tests inject ambiguous creates, duplicate inventory, stale ownership, lost RPC/command replies, cancellation and resource mismatches.

**Result:** 6 real Linux/Postgres cases passed across sync/async database adapters; hosted contract tests passed within the sandbox unit suite. No hosted platform or native-model calls were made.

---

### E2B installed-SDK contract

**Status:** PASS

**Description:** Five tests against E2B 2.55.1 with network endpoints replaced: read-only secure transport construction, paused-compute refusal, create settings, SDK inventory serialization/pagination, and bounded stream cleanup.

**Result:** 5 passed. Format/validation passed. `hosted_workload.py --provider e2b` is prepared but has not run against an E2B account; template permissions, quotas, networking, and native harness behavior remain live acceptance gates.

---

### Daytona installed-SDK contract

**Status:** PASS

**Description:** Five tests against Daytona 0.223.1 without provider calls verify both transport retry configurations, creation/lifetime/network parameters, stopped-compute refusal, confirmed deletion, inventory ownership labels and bounded stream cleanup.

**Result:** 5 passed; SDK deprecation warnings observed. Required format/validation passed. The live Daytona workload remains unrun pending account/snapshot setup and a compute budget.

---

### Modal installed-SDK contract

**Status:** PASS

**Description:** Five tests against Modal 1.6.1 without account access exercise actual SDK signatures and image objects, resource/network/identity settings, stopped-compute refusal, termination waits, scoped inventory, and pre-download bounds.

**Result:** 5 passed. Required format/validation passed after correcting a test import-order issue. Live image, gVisor process-freeze and native harness acceptance remain pending.

---

### Vercel installed-SDK and protected staging contract

**Status:** PASS

**Description:** Five tests against Vercel Sandbox 0.9.0 with actual runtime-session handles and replaced network endpoints verify no automatic resume/replay, exact-session and project checks, creation parameters, and client cleanup. Real Linux staging tests reject tampered bytes and source symlinks and verify root-owned imports.

**Result:** 5 SDK tests passed. Local hosted runtime/transfer plus staging suite passed across both Postgres adapters. No Vercel account or live model calls were made; VCR and platform acceptance remain pending.

---
