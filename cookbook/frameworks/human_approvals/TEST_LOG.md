# Native approval validation

### agentos.py

**Status:** PASS (local direct, Docker, and AgentOS UI); hosted AgentCore untested

**Description:** AgentOS example for direct and sandboxed Claude/Codex approvals.

**Result:** Eight bounded live model runs passed: Claude and Codex, direct and
Docker, approved and rejected. Marker files were absent before approval and after
rejection; approved Docker runs contained the marker in the final checkpoint.
Persisted approval and terminal run statuses were checked.

AgentOS UI was connected to an isolated local backend. Claude approval and
Continue Run completed in the original session. Codex rejection and Continue Run
completed after killing and restarting the API worker during the permission wait.
The replacement worker reclaimed the same sandbox execution, without a new turn;
the denied marker was absent from the final checkpoint. The UI showed the rejected
tool and completed response. A six-minute wait did not exhaust the two-minute
active execution budget.

Environment: Python 3.12.8, claude-agent-sdk 0.2.174, openai-codex 0.163.0,
SQLAlchemy 2.1.6, disposable PostgreSQL and Redis, and a Docker image built from
this checkout. Models: claude-sonnet-4-6 and gpt-5.6-luna. The existing Render
service and its sandbox image were not modified.

### Deterministic regression and failure checks

**Status:** PASS

**Description:** Native permission transport, persisted pause/continue, existing
agent behavior, queue ownership, sandbox runtime, and real PostgreSQL integration.

**Result:** After rebasing onto current main, broad regression: 1,542 passed and
33 skipped (including 21 Docker team/workflow cases requiring an explicit runtime
image). All 21 of those cases then passed with the isolated runtime image and real
Docker/PostgreSQL. Subsequent focused approval tests: 27 passed, including cleanup checks
for both public synchronous continuation APIs. Coverage includes approve/deny on sync and async SQLite, no execution
on expiry/cancellation/storage failure, altered arguments, unresolved continuation,
parallel requests, nonblocking Codex reader, file-change/permission response
contracts, stale sandbox owners, duplicate delivery, old-image refusal, and direct
worker loss without replay. PostgreSQL tests cover both database adapters.

The rebased code also passed another real Docker Claude approval and Codex rejection
with checkpoint evidence. Approval delivery is limited to standalone agents;
the automatic-forwarding follow-up below preserves ordinary nested execution.

The repository format and validation scripts passed using a clean development
dependency environment. Optional-provider type drift in the full test environment
was kept separate; seven SQLAlchemy typing errors were also reproduced on the
unchanged base and corrected with type-only annotations/casts.

### Automatic forwarding from native policy (29 October 2026)

**Status:** PASS

**Description:** Removed the additional Agno human-mode switch. Native Claude
permission modes and Codex approval policies select automatic delivery when a
database is available, including database injection by AgentOS and execution in
Docker. Full-access/deny modes, custom Claude callbacks, ordinary transcript
continuation, nonstreaming results, and retries before an approval remain intact.

**Result:** The broad suite passed 1,567 cases with 12 adapter-specific skips;
three continuation-router cases exposed a missing import. After fixing that
import, all 349 focused agent, team, approval, and authorization cases passed,
including all three failures. Another 21 real Docker/PostgreSQL team and workflow
tests passed. Mandatory format and validation scripts passed.

Eight fresh live cases passed: approve and reject for Claude and Codex, both
direct and in Docker, without any extra approval mode. Each case verified no
marker before approval and the correct final marker presence or absence.
The actual AgentOS UI also approved and continued a new Claude run automatically;
persisted run `16d0fab7-a8e3-46d8-ad77-8e681fa051a9` completed and its final checkpoint
contained `automatic-ui-marker.txt` with exactly `approved`. The UI test used an
isolated server on port 8791; Local AgentOS selection was restored afterward.
The earlier API-worker restart evidence remains applicable: this follow-up did
not change sandbox ownership recovery or decision delivery.

Team/workflow agents still execute operations permitted by native policy. An
actual nested permission request fails explicitly before the requested action,
because nested approval delivery is not supported yet.

### Validation limits

Hosted AgentCore was not deployed or exercised. Its operation forwarding and the
shared runtime are covered by deterministic tests; real hosted acceptance remains
separate. Codex file-change and permission grants have protocol tests, while the
live model acceptance tests exercise shell permission requests. This log records
local validation, not GitHub CI or a release/deployment result.
