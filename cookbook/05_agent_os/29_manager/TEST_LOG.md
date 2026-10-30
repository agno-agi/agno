# Test log

## PR #11394 review, 2026-10-30

### manager_discovery.py

**Status:** PASS

**Description:** Re-ran `cookbook/05_agent_os/29_manager/manager_discovery.py`
at commit `285aacbb5` using `.venvs/demo/bin/python`.

**Result:** Sync and async listings matched the manifest description, and the
agent description remained unset. No model calls or hosted deployment tests.
The manager/runner unit suites returned 655 passed and one warning-capture
failure in `test_the_ignored_child_version_pin_is_said_out_loud`. The same
failure reproduced alone on both the PR and base commit `9153aacd83` using
the same environment. Ruff lint and formatting checks passed for changed Python files.

---

## Manifest discovery descriptions, 2026-10-30

### manager_discovery.py

**Status:** PASS

**Description:** Ran `cookbook/05_agent_os/29_manager/manager_discovery.py`
with `.venv/bin/python`, a temporary SQLite database, and no model calls.
The agent has only a manifest description. Both sync and async manager
discovery return that description without changing the agent's description.

**Result:** Both listings matched and contained the configured description.
The cookbook also passed in an isolated development environment, alongside
656 manager/runner tests and the full format/validation scripts. The shared
`.venv` validation reported nine existing typing errors in unchanged Google/AWS
model files. No API key, hosted deployment, or live-model routing was exercised.

---

## Focused documentation lookup, 2026-10-19

### manager_source.py

**Status:** PASS

**Description:** Constructed the example with branch source and a temporary
working directory, without model or network calls. Inspected the configured
documentation tool; the manager unit suite exercises direct sync/async lookup
with a scripted model.

**Result:** OS Manager and Platform Manager share one docs toolkit. The scripted
manager lookup completes with one docs tool call, two model invocations, and no
member runs. This verifies the available execution path, not live-model routing
quality or latency. Live conversations remain an opt-in check. Follow-up unit
regressions verify that both path and provider roots retain search and direct
read access to requested artifacts under `tmp`. After splitting the changes, the
independent manager branch passed 578 manager, authorization and workspace tests
with one skip. The source example also constructs without the retrieval or
Parallel copying changes.

---

## Manager package and default offloading, 2026-10-14

### basic_manager.py

**Status:** PASS

**Description:** Constructed the app after moving the manager into its own package.

**Result:** OS Manager and its two members are created with default offloading.
Manager resources stay excluded from the build registry. No model calls.

---

### manager_builds_agents.py

**Status:** PASS

**Description:** Constructed the app and published Budget Helper through the
builder's create tool against a temporary SQLite database.

**Result:** The model, calculator tools and workflow functions remain available
for building; manager components remain excluded. No model calls.

---

### manager_with_resources.py

**Status:** PASS

**Description:** Constructed the app with a workspace and learning, then wrote
and read `project.md` through the manager's notebook tools.

**Result:** Three members are configured, and the saved note is returned. No
live-model memory or source explanation was tested.

---

### manager_diagnostics.py

**Status:** PASS

**Description:** Ran the script with `OPENAI_API_KEY` unset and model calls blocked.

**Result:** Completed the report and reported the missing required key as FAIL.

---

### Manager offloading regression checks

**Status:** PASS

**Description:** Ran the manager, diagnostics and offloading unit suites. New
cases exercise delegation and each specialist directly, in sync and async mode,
with default offloading, explicit opt-out and custom ResultStore settings.

**Result:** 186 tests passed, including 24 new manager cases. Stored results can
be read beyond their previews; reads by another user or session are rejected.
Two existing duplicate OpenAPI operation-id warnings remain. Tests use SQLite
and scripted models; no live provider or PostgreSQL run was performed.

---

## Revised manager examples, 2026-10-14

Used `.venv/bin/python` with this checkout's `libs/agno` on `PYTHONPATH`.
Serving examples were loaded from a temporary working directory. Model calls
were blocked in the smoke check; no live conversations or servers were started.

### basic_manager.py

**Status:** PASS

**Description:** Constructed the OS and FastAPI app without an explicit registry.

**Result:** OS Manager has two members and uses the revised instructions. No
manager models, tools or components entered the build registry.

---

### manager_builds_agents.py

**Status:** PASS

**Description:** Constructed the app and called the builder's create tool directly
to publish Budget Helper with calculator tools.

**Result:** Publishing succeeded using the declared model and calculator. The
registry contains the three JSON/CSV functions and excludes manager components.
The README's live conversation and arithmetic response have not been tested.

---

### manager_with_resources.py

**Status:** PASS

**Description:** Constructed the app with three manager members, a notebook and
learning. Called the manager's notebook tools to write and read `project.md`.

**Result:** The saved note was returned. Learning is attached to the manager,
and manager resources remain excluded from the build registry. Cross-session
memory and source explanation through a live model have not been tested.

---

### manager_diagnostics.py

**Status:** PASS

**Description:** Executed with `OPENAI_API_KEY` unset and model calls blocked.

**Result:** Completed the report and correctly reported the missing required key
as FAIL. No registry setup or source workspace was needed.

---

### Manager and diagnostics unit tests

**Status:** PASS

**Description:** Ran `test_manager.py` and `test_diagnostics.py` against the revised
prompt, field placement and component exclusion message.

**Result:** 87 passed. Two existing duplicate OpenAPI operation-id warnings were
reported. Targeted Ruff formatting and lint checks also passed. These checks do
not establish live-model prompt quality.

---

## Diagnostics regression validation, 2026-10-14

### manager_diagnostics.py

**Status:** PASS

**Description:** Executed with the development environment against the updated
branch after pulling `ad76cf015a`. Deliberately unset `OPENAI_API_KEY`; no model
calls were made.

**Result:** SQL connectivity passed without provisioning session tables. The
overall report correctly returned FAIL for the missing required environment
variable, and WARN for disabled authorization. Manager wiring and sync/async
session persistence also passed a separate scripted-model smoke check.

### Diagnostics regression tests

**Status:** PASS

**Description:** Covered broken and empty SQL databases with sync and async
adapters, schedules beyond page one, incomplete scans, later-page errors, and
real in-process MCP initialization at default, custom and host-root endpoints.
Also checked a proxy path prefix.

**Result:** All 16 new cases passed; 11 fail against the pre-fix diagnostics
implementation. The combined manager, diagnostics, scheduler and queue suites
passed 369 tests. No external model calls or live PostgreSQL checks were made.

---

Executed 2026-10-14 with `/Users/ab/code/agno/.venv/bin/python` and this branch's `libs/agno` on `PYTHONPATH`, after printing `agno.__file__` to confirm the branch source. Serving examples were imported from a temporary working directory; no server or live model conversation was started by these runs.

### manager_diagnostics.py

**Status:** PASS

**Description:** Constructs a manager with a workspace against a temporary SQLite database, prints the served and registry component lists, and runs the diagnostics. No model calls.

**Result:** Served agents are platform-builder, platform-manager and platform-engineer; served team is os-manager. The registry's agent list is empty and its tool palette holds only the declared calculator. Diagnostics returned WARN: live database PASS, authorization WARN because it is disabled in this demo.

---

### basic_manager.py

**Status:** PASS (constructed, not served)

**Description:** Imported the module to assemble the OS and its FastAPI app without starting the server or calling a model.

**Result:** OS Manager (os-manager) with two members, Platform Builder and Platform Manager; registry agents empty; the FastAPI app assembled. A live conversation was not run.

---

### manager_with_resources.py

**Status:** PASS (constructed, not served)

**Description:** Imported the module to assemble the OS with a notebook, knowledge, learning and a workspace attached to the manager.

**Result:** OS Manager with three members, Platform Engineer included because a workspace is configured; registry agents empty; the FastAPI app assembled. A live conversation was not run.

---

### End-to-end over HTTP

**Status:** PASS (28/28)

**Description:** A scripted model drives a server on a throwaway PostgreSQL database with JWT authorization, user isolation, MCP and the scheduler enabled. Checks cover token refusal and scoping on `teams:os-manager:run`, session isolation for list, read and continue, SSE streaming, delegation from OS Manager to Platform Manager's diagnostics, Platform Builder publishing a palette component that then runs, Platform Builder refusing to compose a manager member, MCP over streamable HTTP, sixteen concurrent runs, resync identity, reserved-id refusal from a second OS on the same database, a Slack interface and an MCP tool bound to `agent_os.manager` after construction, and refusal of an async database.

**Result:** All 28 checks passed. This establishes runtime and tool behaviour, not live-model answer quality.

---
## Review corrections — 2026-10-14

### manager_diagnostics.py

**Status:** PASS

**Description:** Ran the model-free diagnostics cookbook after correcting Slack credential resolution and component ID checks. Database, components, registry and interfaces passed. Authorization reported WARN, and the absent `OPENAI_API_KEY` correctly reported FAIL.

**Result:** The script completed successfully without model calls. The report's overall FAIL reflects the missing required environment variable, not a script failure.

---

### Manager authorization and diagnostics regressions

**Status:** PASS

**Description:** 168 manager and diagnostics tests passed, including 57 new cases. Coverage includes the manager and every specialist, JWT and managed-role authority, service-account tokens with and without JWT authorization, continuation refusal, schedule target checks, MCP and default A2A gates, Slack environment/explicit credentials, and component ID namespaces. Existing ordinary agents remain runnable by ordinary grants.

**Result:** Selected regression cases were also run against the reviewed commit: 19 failed and 22 passed, confirming the tests detect the original issues. The final authorization, service-account and diagnostics selection passed 297 tests. Full formatting and validation passed with isolated validation dependencies. No paid model calls or live Slack delivery checks were performed.

---

## Caller permissions — 2026-10-14

This supersedes the admin-only manager policy recorded above. Ordinary component
run grants now admit the conversation; protected tools authorize each operation.

### manager_user_access.py

**Status:** PASS (construction only)

**Description:** Loaded the example with a temporary verification key and working
directory. The managed role grants Alice manager access, math-helper access and
diagnostics, without component publishing or schedule creation.

**Result:** The AgentOS app constructed successfully. No model calls or live JWT
issuer integration were performed. The diagnostics cookbook was also rerun and
completed; its missing `OPENAI_API_KEY` check still reports the expected FAIL.

---

### Caller authorization regressions and validation

**Status:** PASS

**Description:** Added 36 offline regressions covering allowed and denied target
runs, direct and delegated builder writes, JWT/role/service-account decisions,
MCP calls, durable jobs, queued continuation authority, scheduled execution,
concurrent callers, parallel synchronous delegation, cached results, forged
snapshots and preservation of the parent policy through mounted applications.
The existing manager tests now verify ordinary run grants can reach the manager.

**Result:** The broad affected run passed 6,375 tests with 24 skips. Its one failing
assertion expected the old queued-continuation payload; it was updated for the
persisted authority and passes in the 77-test targeted rerun. Final selections
passed 674 MCP/authorization/continuation tests, 86 provider/service-account tests,
and 278 workspace/authorization tests (one skip). Formatting and full validation
passed with the isolated validation dependencies. An attempted all-tools run
could not collect unrelated optional integrations; the affected selection excludes
three Telegram files whose optional dependency is unavailable.

---

## OSManager API and fixed identity — 2026-10-15

These results supersede the earlier configurable-ID and Platform Engineer descriptions.

### basic_manager.py

**Status:** PASS

**Description:** Constructed the example in a temporary directory without model calls.

**Result:** OS Manager has the fixed `os-manager-internal` ID, exactly two members, and its model is available in the build registry. No privileged manager tools are exposed to builds.

---

### manager_builds_agents.py

**Status:** PASS

**Description:** Constructed the declared-registry example without model calls.

**Result:** The fixed manager team reuses the declared model and keeps Platform Builder and Platform Manager as its two members.

---

### manager_with_resources.py

**Status:** PASS

**Description:** Constructed the notebook, learning, root and optional docs example in a temporary directory. No model or live MCP calls were made.

**Result:** Platform Manager receives read-only source tools and the opt-in Agno docs MCP toolkit. There is no Platform Engineer. Separate regressions verify file exclusions and stubbed MCP connection/cleanup.

---

### manager_user_access.py

**Status:** PASS

**Description:** Constructed the example using a temporary JWT verification key, without model calls.

**Result:** The managed role uses the new reserved team ID. Regression tests verify that run, discovery and session-reading grants remain separate and another user's sessions stay inaccessible.

---

### manager_diagnostics.py

**Status:** PASS

**Description:** Executed the model-free diagnostics example.

**Result:** The command completed. Its overall report is FAIL because the required `OPENAI_API_KEY` is absent; this is expected and is not a failed execution.

---

### OSManager regression and validation suites

**Status:** PASS

**Description:** Added 27 parametrized regression cases for reserved IDs, disabled-manager and resync protections, metadata on discovery/detail/run responses, model-only builds, docs MCP lifecycle, and independent run/read/session permissions. Updated existing tests for the API, IDs and two-member composition, preserving source confinement and authorization coverage.

**Result:** The broad affected suite passed **6,082 tests, 24 skipped**. The final manager/authorization/registry/component API selection passed **563 tests, 14 skipped** after the final reservation checks; selections overlap. The focused manager/authorization selection passed **182 tests**. Three unrelated Telegram files were excluded because their optional dependency is unavailable. Required `scripts/format.sh` and `scripts/validate.sh` pass using `.venv` with isolated validation dependencies; mypy covers **1,126 framework files and 21 CLI files**. Unrelated formatter-only changes were removed. No paid model, live PostgreSQL, live Slack delivery or live docs MCP calls were made.

---

## Final permissions and developer-experience review — 2026-10-15

### check_manager_permissions.py

**Status:** PASS

**Description:** Ran the new in-process HTTP checker with a temporary development signing key and no model API key.

**Result:** All seven checks pass: Alice can discover the manager and math-helper and list her sessions; unassigned users and anonymous callers are refused; a wrong audience is refused; an admin claim in a JWT does not grant Alice publication access. No model calls. The accompanying regression also runs a scripted manager conversation and verifies Alice can reopen it while Bob's session returns 404.

---

### manager_source.py

**Status:** PASS

**Description:** Constructed the separate read-only source/Agno docs example without network or model calls.

**Result:** The manager has two members, Platform Manager carries source tools and opt-in docs MCP, and the example's root is anchored to its file location. Live docs delivery and live-model answers were not tested.

---

### manager_user_access.py

**Status:** PASS

**Description:** Enabled audience verification explicitly and added session-read access to the example's managed role. Ran the new checker and session ownership regression against this exact cookbook.

**Result:** Wrong-audience credentials return 401. Alice can read her own chat history; another user's session remains inaccessible. The role still cannot publish or schedule, and a JWT admin claim does not elevate it.

---

### basic_manager.py, manager_builds_agents.py, manager_with_resources.py, manager_diagnostics.py

**Status:** PASS

**Description:** Reconstructed the serving examples in a temporary directory without model or live MCP calls, and executed the diagnostics script.

**Result:** All examples construct with the fixed manager IDs and two-member composition. Diagnostics completes and correctly reports FAIL for the deliberately absent required `OPENAI_API_KEY`.

---

### Permanent permission regressions

**Status:** PASS

**Description:** Added 42 cases covering direct and delegated source reads, diagnostics and admin-only aggregates across scope JWTs, managed roles and service accounts; credential-file exclusion even for administrators; and rejection of missing, malformed, expired and wrong-audience tokens. Added the actual-cookbook/session-history regression.

**Result:** The focused manager, authorization, diagnostics, workflow-helper and schedule-creation selection passed **291 tests**. Full format/lint/type validation passed. Final broad-run results are recorded below.

---

**Final broad result:** 6,321 passed, 24 skipped in 285.85 seconds. The selection includes OS, Studio/runner, scheduler, workspace, operational tools, run, registry, workflow helpers and authorization/service-account integration regressions. The final required formatting and validation scripts passed. This selection overlaps the 291 focused tests above. Three unrelated Telegram files were excluded for missing optional dependencies.


## Default documentation access, 2026-10-15

All checks used temporary SQLite data and blocked live model calls. The docs
connection was forced to fail locally; no hosted docs request was made.

### basic_manager.py

**Status:** PASS

**Description:** Constructed the example with default `access_docs=True` and
entered its FastAPI lifespan while the docs connection raised `OSError`.

**Result:** Startup completed and the config endpoint responded normally
(including authentication enforcement for the regular-user example). Platform
Manager retained its documentation toolkit without exposing it to the registry.

---

### manager_builds_agents.py

**Status:** PASS

**Description:** Constructed the example with default `access_docs=True` and
entered its FastAPI lifespan while the docs connection raised `OSError`.

**Result:** Startup completed and the config endpoint responded normally
(including authentication enforcement for the regular-user example). Platform
Manager retained its documentation toolkit without exposing it to the registry.

---

### manager_source.py

**Status:** PASS

**Description:** Constructed the example with default `access_docs=True` and
entered its FastAPI lifespan while the docs connection raised `OSError`.

**Result:** Startup completed and the config endpoint responded normally
(including authentication enforcement for the regular-user example). Platform
Manager retained its documentation toolkit without exposing it to the registry.

---

### manager_with_resources.py

**Status:** PASS

**Description:** Constructed the example with default `access_docs=True` and
entered its FastAPI lifespan while the docs connection raised `OSError`.

**Result:** Startup completed and the config endpoint responded normally
(including authentication enforcement for the regular-user example). Platform
Manager retained its documentation toolkit without exposing it to the registry.

---

### manager_user_access.py

**Status:** PASS

**Description:** Constructed the example with default `access_docs=True` and
entered its FastAPI lifespan while the docs connection raised `OSError`.

**Result:** Startup completed and the config endpoint responded normally
(including authentication enforcement for the regular-user example). Platform
Manager retained its documentation toolkit without exposing it to the registry.

---

### check_manager_permissions.py

**Status:** PASS

**Description:** Ran all seven HTTP checks with default docs access enabled and
the docs server simulated as unavailable.

**Result:** All seven checks passed. Discovery, session reads, invalid-token
rejection and denied publishing retain their existing behavior. No model calls.

---

### Documentation availability regressions

**Status:** PASS

**Description:** Verified default-on and explicit opt-out, connection errors and
timeouts, partial-session cleanup, continued manager/operator runs, unavailable
tools omitted from model requests, recovery on a later async run, registry
exclusion after recovery, a missing optional MCP dependency, and cancellation
propagation. Existing manager and permission suites use simulated docs outages.

**Result:** 230 manager/permission tests passed. Required format and validation
scripts passed, including mypy for 1,126 framework and 21 CLI files. The broader
AgentOS/MCP unit suite passed with **4,075 passed, 23 skipped**. Three unrelated
Telegram files were excluded because their optional dependency is unavailable.
The broader count includes the manager/permission tests; counts are not additive.

---


## Existing StudioTools compatibility, 2026-10-15

### Existing agents and manager permissions

**Status:** PASS

**Description:** Compared a model-free, authenticated StudioTools agent with
only `agents:legacy:run` against base `160d246d6e`, earlier PR revision
`0be962ef8a`, and the compatibility fix. No manager was enabled in the probe.

**Result:** Base and fixed code both list registry models and publish an agent.
The earlier PR revision denied both operations. Permanent tests cover JWTs,
managed roles and PATs with manager omitted, None, False and enabled, as well as
shared tools, delegation in both directions, MCP, caches, queues, schedules,
streaming tools and post-hook result preservation. Manager operation checks remain
active through delegated and deferred execution. No live models or services.

---

### check_manager_permissions.py and permission regressions

**Status:** PASS

**Description:** The actual regular-user cookbook's seven HTTP checks and its
session-ownership regression run in the permission suite with docs offline.

**Result:** Focused manager, authorization and tool execution suites: **486 passed**.
Required format/validation scripts passed, including 1,126 framework and 21 CLI
files checked by mypy. Final broad affected suite: **6,589 passed, 24 skipped**.
The broader count includes the focused tests; counts are not additive. Three
unrelated Telegram files were excluded for their missing optional dependency.

---


## Final review corrections, 2026-10-15

### Schedule edits and async manager authorization

**Status:** PASS

**Description:** Added 14 model-free HTTP regression cases for schedule timing
and description edits, subsequent scheduled execution, checked execution edits,
forged authority rejection, and manager discovery/source reads with an
`AsyncSqliteDb` managed-role store. Discovery covers agents, teams and workflows;
source operations cover reading, listing and searching. Allowed and denied
callers are both exercised.

**Result:** The pre-fix revision `1938e9dcd2` fails 11 of these cases; all 14 pass
with the fixes. Affected manager, authorization, schedule router, scheduler,
workspace and runner suites: **1,155 passed, 1 skipped**. This includes the actual
regular-user cookbook's seven HTTP checks and session-history regression.
Required format and validation scripts passed, including mypy for 1,126 framework
and 21 CLI files. Tests use disposable data and scripted models; no live model,
PostgreSQL or hosted docs requests were made.

---


## Private OS Manager members, 2026-10-15

### Discovery, loading, delegation and schedule migration

**Status:** PASS

**Description:** Only OS Manager is public; its builder and operator remain
native private members. Coverage includes reserved-ID errors in explicit catalog
and class loaders, database-independent REST errors, sync/async lookups, legacy
rows, runner dispatch, queued replay, permissions, confirmation, continuation,
session history and result offloading. Unmanaged specialist schedules can be
retargeted; Studio-managed schedules require replacement because their targets
are immutable.

**Result:** The local follow-up to `61c29327f9` passed **1,411 tests** across
manager, authorization, runner, scheduler, component-config and rehydration
suites. Two existing duplicate OpenAPI operation-ID warnings remain. The required
format script passed; unrelated baseline formatter changes were removed. The
validation script passed in the existing isolated dependency environment,
including mypy for 1,126 framework files and 21 CLI files. The shared development
environment reported the same 33 mypy errors as the untouched base
`28ee417d5d` (confirmed by a separate mypy run).

Historical results are not current validation: `03fe8ef9b8` passed 7,890 broad
checks with 32 skipped; `61c29327f9` passed 441 focused checks and the required
format/validation scripts. These counts overlap and are not additive. Historical
validation used isolated dependencies because the shared environment had
unrelated SDK typing errors; optional Telegram files were excluded.

Tests use disposable data and scripted models. No live model, hosted docs,
PostgreSQL or frontend rendering checks were performed.

---

## Focused execution limits, 2026-10-19

### basic_manager.py

**Status:** PASS

**Description:** Constructed the serving example with checkout source in a temporary
working directory. No provider calls or shared database writes.

**Result:** Coordinator limit is 8; both specialists have limit 24. The example
continues to expose the framework-owned manager.

---

### Manager execution and explanation regressions

**Status:** PASS

**Description:** The manager, Company playbook/tools and run-authorization suites
passed 424 tests. New scripted-model checks exercise sequential and batched tool
calls, sync/async runs, both streaming modes, reuse across turns, and both sides
of delegation. Configuration tests cover overrides, zero, opt-out and invalid
values; standalone Product Manager and application agents retain their policies.

**Result:** Ordinary tools execute only within the configured per-invocation
limit. All manager roles receive the shared focus/evidence instructions. Scripted
models verify plumbing and enforcement, not live-model reasoning quality.

---

### Live framework manager rehearsal

**Status:** PASS

**Description:** Ran four conversations using GPT-6.1 Sol, low reasoning, default
framework prompts/limits and Agno documentation access against a disposable SQLite
database and source fixture. Counted coordinator and persisted member tools.

**Result:** Final run: conceptual learning explanation used 3 calls (22.35s),
learning configuration used 4 (27.35s), agent publication used 4 (22.07s), and one
Project with two unaccepted Backlog Tasks used 13 (48.66s). Publication and Company
records were verified from storage; the published agent was not executed. The
configuration answer explicitly distinguished file configuration from attachment
and actual learning execution.

An earlier configuration attempt used 6 calls; guidance was tightened to read
named files directly and count result read-backs in the explanation budget before
the successful rerun. These are single-run behavioral checks, not a guarantee
across models. Execution limits remain per invocation; offloaded-result reads
are exempt, and model turns/tokens and dispatched application runs are not capped.

---

## Framework concept grounding, 2026-10-19

### manager_source.py conversation checks

**Status:** PASS

**Description:** Added the exact questions "what is agno" and "can you tell me
about learning machines" to the manual rehearsal. Live docs search previously
ranked CLI pages above the product overview; the old learning-machines response
explained generic ML training. Updated shared instructions to choose relevant
product overviews, preserve Agno terminology, distinguish business knowledge,
and honor explicitly general questions. Basic explanations omit unsolicited code.

**Result:** With GPT-6.1 Sol (low reasoning) and disposable storage, framework-only
checks answered both questions from Agno documentation and preserved an explicitly
general supervised/unsupervised ML question.

The manager unit suite passed 255 tests; full format and validation scripts passed.
These are local behavioral samples against live docs, not hosted deployment proof
or a guarantee of factual accuracy on every run.

---

## Template without appended manager instructions, 2026-10-20

**Status:** PASS for four manager scenarios; Company proposal state check failed.

**Description:** Removed Railway's entire application manager prompt and exercised
its existing isolated PostgreSQL cases with GPT-6.1 Sol. The unknown-file
configuration lookup initially spent its budget listing/searching. A follow-up
found the definitions but passed four calls to a specialist in addition to the
delegation. Shared framework guidance now prioritizes reading definitions after
one targeted search and subtracts the delegation from the explanation budget.
Basic explanations explicitly stay within 200 words unless more detail is asked.

**Result:** Targeted runs passed learning explanation, configured learning,
README onboarding and read-only diagnostics without application-component
execution. The template supplied no manager instructions or configuration-path
hint. The configured-learning answer passed both evidence/budget checks and its
semantic judge. The separate Product Manager fixture produced one unaccepted
Project/Task with correct source evidence, but its strict business-state check
failed after a decision-log write; this is not a full release-suite pass.

The template's 26 offline/PostgreSQL tests and full formatting/type checks passed
before concurrent template refactoring. The framework manager suite passed 255
tests and full format/validation passed. A superseded rehearsal was invalidated
by changing its test environment installation while it was still running; those
runtime errors are excluded from the targeted validation above. No hosted rollout
or template-runtime restart was performed.

---

## Prompt simplification, 2026-10-20

### basic_manager.py and manager regressions

**Status:** PASS

**Description:** Constructed the basic example in a temporary directory and ran the
255 manager tests after shortening shared guidance and moving role-specific rules
into the existing coordinator and operator prompts.

**Result:** The example retains the 8/24 defaults without explicit overrides.
All tests and full format/validation scripts pass. Live-model checks above predate
this simplification and were not rerun.

---

## Shared prompt scope, 2026-10-20

### Manager regressions

**Status:** PASS

**Description:** Reduced the shared member guidance to scope, stopping, evidence
and execution rules. Framework-explanation guidance now reaches only the lead and
Platform Manager, which have documentation access, and no longer names specific
questions. Removed the four-call explanation allowance, which asked the lead to
count member calls and read-backs it cannot observe.

**Result:** The manager unit suite passes, including a new check that Platform
Builder and Product Manager receive the shared rules but not the explanation
guidance. Live-model checks were not rerun for this change.

---

## External engineer dispatch, 2026-10-22

### `libs/agno/tests/unit/os/test_manager.py::test_manager_discovers_and_runs_external_agents`

**Status:** PASS

**Description:** Both Claude Engineer and Codex Engineer appear in OS Manager's
roster and execute through the sync and async runner tools. The real adapter
lifecycle uses stubbed harness responses and a temporary SQLite database. Checks
cover ID/name lookup, follow-up history, user isolation, saved runs, dispatch
metadata, permission denial, the shared session-admission guard, and removal
from the live roster after copying the manager.

**Result:** All four cases passed. The manager and runner suites passed 644 tests;
the Studio and Claude/Codex adapter suites passed 1,279 tests (including the
runner suite again). The four new cases also passed in an isolated development
environment. Full format/validation passed there with SQLAlchemy 2.0.55; the
shared demo environment reports unrelated Google/AWS provider typing errors.
The README example was not run against live models or harness processes; no
provider calls were made.

---
