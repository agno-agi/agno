# Company Products

Manage standing responsibilities with SQLite for development.
PostgreSQL is supported for production, with the same sync and async methods.

| File | What it teaches |
| --- | --- |
| `01_manage_products.py` | Create two owners' Products, list unscoped or by owner, soft-delete, inspect and restore. |
| [`10_customer_feedback/`](10_customer_feedback/README.md) | Live GPT-6.1 Sol feedback review, human acceptance, and a saved product brief through the AgentOS UI. |

Run with the development environment:

```bash
.venv/bin/python cookbook/05_agent_os/30_company/01_manage_products.py
```

For HTTP access, configure `AgentOS(db=db, company=CompanyConfig())` using
`AgentOS` and `CompanyConfig` from `agno.os`. An explicit `CompanyConfig(db=...)`
overrides the OS database. Omitting Company leaves its routes and scopes absent.

The routes are `GET` and `POST /company/products`, `GET`, `PATCH` and
`DELETE /company/products/{id}`, and `POST /company/products/{id}/restore`.
Lists return `{data, meta}` with `limit` and `page`; reads accept
`include_deleted=true`. Restore requires `products:delete`, like deletion.
Read and create/update require `products:read` and `products:write` respectively.

`CompanyManager` takes a sync database; `AsyncCompanyManager` takes an async
database and exposes the same methods as coroutines. `list()` returns rows and
a total. `user_id=None` is unscoped; a string filters by owner before paging.
The HTTP layer records the authenticated caller as the creator. Company records
are shared: reads need the read scope and writes need the write or delete scope,
whoever created the Product. User isolation does not restrict Company records.

## Weekly Company Manager review

`10_weekly_product_review.py` runs a Company Routine with the framework's
`company-manager-internal` agent. It reads Sources and existing work, proposes
only evidence-backed Backlog Tasks, and updates status without accepting work.
The same declaration works with or without OS Manager; no application agent is
needed. Company Manager is the only framework manager that can run a Routine:
OS Manager, Platform Builder and Platform Manager can change the platform, and
Routines run unattended on Source content, so they are refused as executors.
Company Manager stays out of Studio's reusable registry and is served through
its normal agent routes whether or not OS Manager is enabled.

Check both configurations without model calls or an active scheduler:

```bash
.venv/bin/python cookbook/05_agent_os/30_company/10_weekly_product_review.py --check
.venv/bin/python cookbook/05_agent_os/30_company/10_weekly_product_review.py --check --with-os-manager
```

Start the local server with `--enable-weekly-review` to opt in to Monday reviews
at 09:00 `Europe/London`. Use `--source /absolute/path/to/docs.md` to select a
local Source, and `--with-os-manager` to serve OS Manager alongside it. Scheduled runs require
provider credentials and incur model usage. Automatic acceptance remains off.
Omitting the opt-in flag creates no new Routine; it does not remove a previously
saved schedule. Pause an existing Routine through its Company API/UI control.

The example uses SQLite and no authentication for local development. For an
authorized deployment, use PostgreSQL and configure the Routine through the
existing authenticated Routine API, setup API or human Company chat so the
caller's grant is saved.
A code/YAML declaration's `user_id` is attribution, not a grant. An authorized
execution-changing PATCH (for example, updating `instructions`) can authorize an
existing declared Routine. A timing-only edit does not replace its authority.
For direct Python bootstrap or `CompanyManager.create_routine`, pass the owning
`AgentOS` as `agent_os=agent_os` when selecting a framework manager.

The caller needs Routine/schedule configuration permissions and the target's
agent/team run permission; scheduled result polling also needs the target's read
permission. Grant only the Company tools the review uses: Sources and existing
work reads, proposal writes, wiki reads/writes and decision recall. Delegation
retains those grants and Routine restrictions. Company-wide collaborative reads
keep their existing visibility; Source contents and mutations retain Product
checks, and private sessions retain the deployment's ownership isolation.

Any caller with `routines:write`, `schedules:write` and the executor's run
permission can manually trigger, edit, pause or resume a Routine, including one
created by another user or seeded without an owner. Manual runs use the caller's
authority and record that caller in the run's `user_id`. The scheduler follows
the run with that authority, so the caller also needs the executor's read
permission for the run to be recorded as successful. The saved Routine creator
and authorization remain unchanged for scheduled runs; only edits to the
executor, instructions or acceptance policy save the editor's authorization. A
Routine with automatic acceptance accepts proposals with the saved grant of the
user who authorized it, so under user isolation only that user can trigger it
manually.

## Work records

| File | Demonstrates |
| --- | --- |
| `02_manage_projects.py` | Product-contained Projects, owner filtering, explicit transitions, soft delete and restore. |
| `03_manage_tasks.py` | Backlog proposals, executor acceptance, frozen scope, rescoping, review and completion. |
| `09_sandboxed_engineers.py` | Claude and Codex execute a Task from a public repository in Docker, with durable checkpoints and checkout pinning. |

A Product contains Projects and Routines. Every new Task belongs to a Project
in that Product: `project_id` is required by Task creation and proposal/Intake
tools. HTTP rejects omission with 422; Python managers and tools raise
`ValueError`. When no Project fits, propose one with `propose_company_project`,
then pass its ID to the Task proposal. A Backlog Task can move between Projects
but cannot clear its Project. Existing nullable storage rows remain readable.

Projects start `proposed` and move to `active`, then `done`. Tasks start
`backlog` and move through `ready`, `in_progress`, `in_review`, and `done`.
Either can be `cancelled` from any non-terminal state. Each transition takes
`target` and a non-empty `reason`; history is returned on the record. Tasks
may return to Backlog to clear acceptance and change scope, and In review may
return to In progress for revisions by starting the next run attempt. Direct HTTP
transitions to In progress return 409 and name the runs endpoint. Terminal states cannot transition.

The HTTP routes use `/company/projects` and `/company/tasks`, with the same
CRUD, paging, soft delete and restore conventions as Products, plus
`POST /{id}/transitions`. Task Ready requests include `executor_type` and
`executor_id`; the API applies the scheduler's caller run-permission check.
Acceptance also validates the executor against the registry. Direct Python callers
pass `registry=Registry(...)` to their Company manager.

Project and Task HTTP reads are company-wide for callers with the resource's
read scope, matching Products. Edits and transitions are collaborative: callers with the resource write
scope can update or transition another creator's work, even with user isolation
enabled. This includes cancellation and returning Tasks to Backlog. The creator
stays unchanged, and transition history records the acting caller. Ready still
requires the caller's executor run permission; accepted Tasks must return to
Backlog before editing. Delete and restore need the delete scope, not ownership.
New work can use another owner's Product or Project, with the Task and
Project still required to belong to the same Product. Manager and storage
methods retain explicit owner filters for direct callers.


## Playbook and Company Manager

| File | Demonstrates |
| --- | --- |
| `04_manage_playbook.py` | Sync/async wiki namespaces, atomic page creation, version conflicts and the learning decision log without a model. |
| `05_company_manager.py` | Model resolution, a standalone Company Manager, bounded Company tools and explicit MCP publication without a model call. |

Each Product has a durable wiki namespace with `brief.md` (human direction) and
`status.md` (current work). A second namespace holds company context. Default
pages are created on first access and never reset. GET `/company/products/{id}/wiki`
lists pages; GET and PUT `/company/products/{id}/wiki/{path}` read and write them.
The company namespace has the same surface at `/company/wiki`. Writes require the
filesystem `expected_version` read with the page; zero means create only. Conflicts
return 409. Pages are Markdown and paths must be relative and normalized.

Wiki reads require `wiki:read`; writes require `wiki:write`. Product and company
pages are shared documents, so any caller with `wiki:write` can change them, and
every caller with read permission can read both namespaces. Company services use FileSystem;
its existing backend owns storage and version checks.

GET and POST `/company/decisions` use `decisions:read` and `decisions:write`.
Decisions are learning log entries in the `company` namespace, never a file.
Listings support text, agent, session and age filters plus standard paging.
The server stamps human identity; agents get identity from injected run context.
Automatic learning recall includes human and agent decisions across the company;
explicit searches can still filter by agent. The learning machine binds the agent
ID when supplying decision tools. Standalone CompanyTools and direct MCP calls
leave agent attribution unset. The log is append-only: later outcomes are new
entries that reference the original decision.

Company Manager uses `CompanyConfig(model=...)`, otherwise the first declared
registry model. If neither exists, its unavailable reason appears in diagnostics
and manual APIs still work. It is served at `GET /agents/company-manager-internal`
and `POST /agents/company-manager-internal/runs`. When OS Manager is enabled it also
gets a separate Company Manager member that carries the manager's tool-call limit and
focused instructions; the served agent, which direct chat and Routines use, keeps its
own policy. It was previously named Product Manager with the id
`product-manager-internal`; that id stays reserved, and `AgentOS.product_manager`
remains a deprecated alias of `AgentOS.company_manager`. Its id is reserved and its tools stay out of
the registry. It proposes Projects and Backlog Tasks, edits owned proposals,
updates `status.md` with a version check, and logs decisions through its learning
machine. It can read Sources and add website Sources with permission and Product
ownership. Acceptance, completion, ownership changes, local Source additions and
scheduling remain outside its tools.

CompanyTools can be published explicitly with `MCPConfig(tools=[...])`, following
the existing MCP toolkit convention. Direct MCP calls have the same write fence.
The examples make no provider calls; they do not demonstrate live model quality.
The heartbeat examples below demonstrate Routines and Sources.

Optional Company tool arguments accept `null` for omission. Empty strings are
normalized to omission as well; omitted pagination uses 20 results on page 1.
Required identifiers and titles still require valid values.

Async PostgreSQL derives its default database ID from the connection URL and
schema, like synchronous PostgreSQL. Async SQLite already derives a stable ID
from its connection details. Reuse those details (or an explicit stable `id`)
after restart and across replicas so saved run database references resolve.
This does not rewrite references saved with older randomly generated IDs;
retaining a known old ID explicitly is necessary for those references.

## Execution and attention

| File | Demonstrates |
| --- | --- |
| `06_execute_tasks.py` | Durable execution, duplicate starts, ordinary run history and attention with no model call. |

`06_execute_tasks.py` starts an accepted workflow Task through its ordinary run
route and the durable queue, waits for In review, reads paged history and checks
attention. It makes no provider calls. Start PostgreSQL with
`./cookbook/scripts/run_pgvector.sh`, then run:

```bash
.venv/bin/python cookbook/05_agent_os/30_company/06_execute_tasks.py
COMPANY_DB=postgres .venv/bin/python cookbook/05_agent_os/30_company/06_execute_tasks.py
```

The default stores Company records and sessions in temporary SQLite, with a
PostgreSQL queue. `COMPANY_DB=postgres` uses PostgreSQL for both. The example
creates and removes its own database schema. `COMPANY_QUEUE_DB_URL` overrides
the local PostgreSQL URL. SQLite follows the queue's existing development
fallback; use PostgreSQL session storage for production attempt fencing.

POST `/company/tasks/{id}/runs` accepts `{"attempt": 1}` (the default). Repeating
an active attempt returns the first run. In review, a stale attempt returns 409. A full queue returns 429 without changing
the Task or consuming the attempt; retry the same attempt when capacity is available.
The durable ticket is accepted before the Task moves to In progress, and the worker
can recover that update if the submitting process stops. If acceptance changes
before the Task can reserve a fresh ticket, the request returns 409 and cancels
the waiting ticket; an already-claimed ticket is rejected by the worker.
To request a revision from In review, POST to the runs route with `attempt` equal
to the highest recorded attempt plus one. The reservation writes the In review
to In progress transition and clears the previous result, retaining the same
session and executor. A rejected submission leaves the result and lifecycle unchanged.
A fresh Ready Task starts attempt 1. Work returned to Backlog, edited, and accepted
again starts the next unused attempt from Ready, retaining its session. Backlog
cannot start a run. Failed or cancelled runs can still be retried while the Task
remains In progress. No
revision feedback field is accepted by this request. Each Task retains one session. GET on the same route returns ordinary session runs
with `limit` and `page`. GET `/company/runs/{id}` reads an individual run and
POST `/company/runs/{id}/cancel` uses the executor's existing cancellation route.

Start rechecks the registry, `tasks:write`, `wiki:read` and the executor's run
permission. Registry-only executors receive their ordinary routes when Company
is enabled. Each executor needs a run database, and execution requires
`QueueConfig(durable=True)`. Every attempt runs as the Task's accountable owner,
`task.user_id`. Company checks the starting human's current executor run permission
first, then uses the internal service transport with the Task owner header. The
owner does not need the executor's run permission; that permission belongs to the
acting human. For an unowned Task, Company records the executor's default user as
the effective session owner and reuses it on later attempts, even if that default
changes. Cancellation checks the acting human's executor permission too, then
uses the recorded run owner for cancellation and Task reconciliation. A refused
cancel leaves the queue ticket unchanged.
The attempt transition records that human as `started_by`; automatic starts record the
policy's accepting human. Revisions by another authorized collaborator keep the
same session and owner in both isolation modes. The ordinary session ownership
check still rejects unrelated sessions. For a legacy session created by a starter,
Company recovers with the recorded reservation identity and transfers an idle
session to the Task owner only after matching its original reservation and run. Engineering executors cannot be started yet. Framework-reserved executors,
including Company Manager and OS Manager, cannot be accepted or started as
Task executors.

Executor input contains only the Task brief, its evidence and the current
company and Product wiki pages. Queue retries and restart recovery use the
existing queue policy. Results are saved on the Task; success moves it to
`in_review`. Retryable failures remain outside failed attention while the queue
has attempts left. An exhausted, permanent or cancelled run leaves the Task
In progress with a visible `ERROR` or `CANCELLED` result. It can start another numbered attempt or return to
Backlog for replanning. Executors cannot acquire scheduler mutation authority.

GET `/company/attention?product_id=...` returns `proposals`, `in_review` and
`failed` counts using the Task list filters. Omitting Product counts all work.
Attention and run reads are company-wide with `tasks:read`; Task lists also
accept `failed=true`. Failed work means an In progress Task whose latest result
is `ERROR` or `CANCELLED`. Moving the Task to Cancelled, Backlog, Ready or In review
clears it from failed attention while preserving the result as history. Starting
a new attempt clears the previous result. `failed=false`
includes all other Tasks, including those with no result. The Task table is
created with its execution, evidence and result columns in the initial schema.

## Cascading archive

| File | Demonstrates |
| --- | --- |
| `07_cascading_archive.py` | Active-work refusal, moving a Backlog Task, cascading archive, hidden children, and exact restore with sync and async managers. Add `--postgres` for PostgreSQL. |

Archiving a Product archives all its active Projects and Tasks. Archiving a
Project archives its active Tasks. Every cascaded child's `transitions` history
records an `action: "archive"` event with `archived_by: {type, id}` naming the
parent. Lifecycle status stays unchanged. Restore brings back only those
children; records archived separately or before the parent stay archived.
Restore the parent before restoring individual children.

A Product or Project with Ready, In progress, or In review Tasks refuses archive,
even if an active Task was separately archived.
The API returns 409 with `detail.message` and `detail.tasks`, an array of `{id,
title}` objects. Managers raise `ValueError` with the same detail dictionary.
Finish or cancel that work first. Backlog Tasks may move to another active
Project in the same Product using `PATCH /company/tasks/{id}` with `project_id`;
Product membership is immutable.

Project and Task lists always hide children of archived parents, including when
`include_deleted=true`. Totals and pagination follow the same visibility rule.
Use `include_deleted=true` on the parent's own list to find it, or read an
individual archived record with that flag. Cascades and restores run in one
database transaction; refusal leaves the entire hierarchy unchanged.

Standalone Task archive and restore change visibility without adding lifecycle
transitions, preserving acceptance for an existing queued run. Restore closes an
archive history event only when one was recorded by a cascade. Returning to
Backlog or otherwise changing acceptance still invalidates an old queue ticket.
For records archived by older versions that left live children behind, restore
the parent before editing or restoring those children; individual reads remain
available with `include_deleted=true`.

Cascade writes currently update each child inside one transaction. Large archives
hold the Product lock until all child updates finish; bulk-update optimization is
a separate follow-up. The list-page query bound is independent of archive size.

Product and Project reads also carry `counts`. A Product has `counts.projects`
(the number of proposed or active Projects) and `counts.tasks` with integer
`backlog`, `ready`, `in_progress`, `in_review`, `done`, and `cancelled` fields.
A Project has the same `counts.tasks` object. Missing statuses are zero.
Archived children and children of archived parents contribute nothing, even
when the parent's own read includes archived records. Managers and HTTP use
`BaseDb.get_product_counts(ids)` or `get_project_counts(ids)` and their async
twins, issuing one grouped query for the entire returned page. A warmed list
page uses three SQL statements in total, regardless of the number of cards.

## Heartbeat

| File | Demonstrates |
| --- | --- |
| `07_heartbeat.py` | Code-declared Products, a reader Source, an Intake Skill, scheduler rows and duplicate-free scans without a model call. |

Declare `Product`, `Source` and `Routine` from `agno.company`, then pass
`CompanyConfig(products=[...])`. The same declarations work in OS configuration:

```yaml
company:
  products:
    - id: documentation
      name: Documentation
      purpose: Keep docs current
      sources:
        - type: markdown
          reference: /workspace/docs
          credential_ref: DOCS_ACCESS_TOKEN
      routines:
        - name: intake
          template: intake
          executor_type: agent
          executor_id: source-reader
          cron_expr: "0 9 * * 1-5"
```

The executor must already be registered; an invalid declared target fails startup
instead of silently dropping its Routine. Give it `CompanyTools(db)` and
`load_routine_skills()` for reader, Intake and Summary tools. AgentOS binds its
interfaces to custom `CompanyTools(db)` executors automatically; an explicit
`interfaces=` override is preserved, and `summary_tools=False` disables delivery.
Company Manager has no outbound Summary tool. Enable the existing AgentOS scheduler and queue to run schedules; the
cookbook only creates and inspects them. Scheduling alone never grants acceptance.
The OS scheduler database owns Routine definitions/history even with a separate
Company database. `metadata.routine_ids` links them to Products.

The templates are packaged `SKILL.md` files under `agno/company/skills`, loaded
through `LocalSkills`. Creation snapshots the selected Skill's instructions into
the schedule, with the Product id explicitly included in the model message.
Following scheduler behavior, restarting or editing a Skill never overwrites
human-edited schedule instructions. Apply revised instructions to an existing
Routine with an authorized PATCH to `/company/routines/{id}`.
Source types are `git` (a local checkout), `markdown` (a
file or directory), and `website` (a single page). Optional `config.paths` limits
local reads to relative files. Workspace exclusions and path confinement apply;
credential references name environment variables, whose presence diagnostics
report without disclosing values. These readers use local files or an unauthenticated
website GET: `credential_ref` is a diagnostic prerequisite, not an authentication
adapter, and its value is never passed to an executor or reader.
Source reads require `sources:read`, not a separate filesystem grant.
`read_product_source` without `path` returns a content-free index (`data`,
`total_count`, `next_offset`). Use a filename glob in `pattern` and `offset`/`limit`
to page through it. Discovery does not open document contents. Pass a returned
`path` to read one document; the response contains evidence and up to 8,000
characters by default (`max_chars` can be 1..16,000). `next_content_offset` lets
you continue a large document using `content_offset`. Every tool response is
capped at 64 KiB of serialized JSON, including metadata. The full-document
`content_hash` must stay the same across fragments; reread if it changes.
Selection can narrow but never expand a human's `config.paths`, and Workspace
exclusions and root confinement still apply. Website Sources only read their
configured URL. The programmatic whole-Source `read_source` API still skips
undecodable/oversized directory entries and reports `skipped_paths`; explicit
selected-file reads fail on reader errors.
Source reads produce evidence with the run id,
a SHA-256 hash of reader content, and a link. Task deduplication is per Product,
including completed and soft-deleted proposals. Failed reads create no proposals.
Reader failures fail the executor and Routine run, appear in Routine history,
and contribute to the Product's failed attention count. Routine authority uses
the configured Source's confined reader under `sources:read`; the human creating
the Routine does not need an additional `filesystem:read` grant.
Reading files creates no Tasks. The reader first decides whether useful work is
needed, then supplies a title, concise brief, selected `evidence_links`, an
`evidence_hashes` mapping from each selected link to the `content_hash` observed
in the preceding read, and a stable Source-local `proposal_key` to Intake.
Intake rereads only the selected links, verifies their hashes, and rejects
evidence changed since observation. Read again and reconsider the proposal after
such a rejection. It stores hashes and links, without copying document content
into the Task. Reuse the issue key across content and wording edits; a distinct issue
has a distinct key. Database uniqueness remains scoped to the Product.
Routines must use evidence-backed Intake: plain `propose_company_task` and
Company service Task creation reject Routine authority. Human and Company Manager
proposals retain their normal behavior.

`/company/routines` wraps the scheduler. Writes require both `routines:write`
and `schedules:write`; histories require `routines:read` and `schedules:read`.
Routine creation saves the schedule disabled, links its id to the Product, then
activates it through the scheduler. If linking or activation fails, retrying the
same request as the same creator resumes the pending creation. Edited requests
and already-created schedules still return 409; a retry never undoes a deliberate
pause. Resume also repairs a missing Product link before activation.

Routine reads and histories are company-wide, including under user isolation.
Like Projects and Tasks, any caller with the Routine write scopes can add a
Routine to any active Product, including an unowned declared Product, and edit,
pause or resume any Routine; the creator stays recorded on the schedule.
Pause/resume use scheduler disable/enable and its filtered state response; saved
authorization claims are never returned. Routine schedule names follow scheduler
validation, including the 255-character limit on `product_id + "." + name`.
Invalid names return 422 before creation, including setup. Sources use `sources:read`,
`sources:write` and `sources:delete` on any Product.
`POST /company/setup` uses `products:write` to seed a blank deployment; nested
Sources and Routines also require their own write permissions. Retries and
restarts repair interrupted creation and linking, retain existing edits and do not
restore archived records. Setup returns 201 for creation and 200 for a retry.
If the deployment already has Products other than this setup identity, setup
returns 409.

Summary uses Product metadata such as
`{"summary": {"interface": "slack", "destination": "C012345"}}` and the matching
interface configured on AgentOS. The executor supplies its narrative to
`summarize_company_product`; the page includes counts, that narrative, changes
since the last delivered summary, and failed-Task details. Summary updates the versioned
`summary.md` Product wiki page before delivery. Delivery receipts and the last
delivered snapshot persist in a separate Product filesystem namespace, outside
the wiki and executor input, so report retention cannot resend a delivered run or
reset the change baseline. Existing report receipts migrate before expiry.
A repeated run does not resend after intervening successful runs;
a transport failure remains a failed run with the report retained and the previous
delivery baseline unchanged. The baseline advances with the receipt only after
transport succeeds, so the next report still includes undelivered changes. Provider
retry guarantees still apply if a process dies after sending but before recording
success. No live messages are sent by this cookbook.

Task evidence identity and deduplication are part of the initial Company schema.
Task responses expose `origin`, `routine_id` and `dedupe_key`. Human-created Tasks
have origin `human`, Company Manager proposals have `product_manager`, and Routine
proposals have `routine` with the trusted Routine id.
Automatic acceptance is opt-in as described below.


## Automation

Enabling Company serves eligible registry executors on their ordinary AgentOS
routes (for example, `/agents/{id}/runs`), with the usual run permissions.
Registry-only executors holding `SchedulerTools`, including nested agents in
teams or workflows, are excluded from mounting. Explicitly served components
retain their ordinary routes but cannot serve as Company executors if they hold
`SchedulerTools`.

With Company, `scheduler=True`, and the durable queue configured, the scheduler
creates one managed `Company automation` schedule. This runtime-owned row cannot
be edited, disabled, deleted or manually triggered through schedule APIs or
SchedulerTools; those operations return a refusal. Ordinary Routines remain
editable and pausable. When the scheduler starts without Company configured, it
disables any existing managed automation row before polling; a fresh deployment
without Company creates no such row. Enabling Company again re-enables that row
and preserves its history. Deployments sharing scheduler storage must use the
same Company configuration.

Candidate queries select Backlog, Ready and In progress
Tasks before pagination, leaving completed history out of the pickup scan.
Automatic transitions compare the observed `updated_at` with the stored value,
including SQL NULL for a record that has never been updated. The existing status
and terminal-Task predicates remain in the database UPDATE. `updated_at` uses
epoch seconds: two writes in the same second share that timestamp, while the
status predicate still holds in that window. There are no field snapshots or
child-set comparisons in SQL or Python. A same-second scope edit is therefore
indistinguishable from the checked record. Project completion still refuses any
current non-terminal Task, but child evidence changes do not advance the Project's
timestamp and are not fenced by this comparison.

Each hour it checks Ready Tasks and authorized Routine proposals using the
scheduler's ordinary claims and release. The cadence is
`CompanyConfig(cron_expr="0 * * * *")`. The setting must be a cron
expression; a changed cron is applied to the existing schedule on restart. A tick
records history only when it accepts, dispatches, completes, or recovers work, or
encounters an execution error. Dispatch failures, including unavailable queue
storage or a missing executor, produce failed history with Task-specific reasons,
readable through `/schedules/{id}/runs`. Idle ticks and expected acceptance-policy skips leave no
run rows. Unexpected database errors are recorded even before dispatch starts.
Engineering executors and a previous attempt whose ticket is still active are
expected skips. If a Ready Task's accepting human loses permission, the Task
returns to Backlog with the refusal reason and appears in attention; the failed
tick is recorded once instead of repeating every hour.

Recovery runs before current Routine pause, policy and permission checks. It only
reconciles existing reservations and never enqueues work. A terminal durable run
repairs a missing Task result, including after its Routine is paused or its policy
is revoked. A ticketless Pending row is cancelled. A ticketless Running row is
observed until durable completion or an explicit cancellation request. Absence
from a cancellation registry does not prove that another worker has stopped;
without authoritative liveness evidence, recovery leaves the attempt unresolved.
The conditional database update preserves a concurrent worker's status change.
Task result projection checks the reservation history and writes only while the
attempt has no result, so the first terminal outcome wins. A
reservation with neither a queue ticket nor a run is cancelled on the Task.
Failed or cancelled attempts require a human retry; new dispatch still checks
current actor permissions and the policy fingerprint.
Reservation identity conflicts return HTTP 409, and unavailable original run
stores or recovery executors return HTTP 503. Unrelated session ownership remains
an HTTP 404 refusal.

Consecutive dispatch failures for the same Task state and reason update one failed
schedule-history row. `/company/attention` includes an `automation_failures` list
when actionable failures exist, with `task_id`, `reason` and `count`; `failed`
counts each active streak once. A changed reason, Task move or successful check
ends that streak. Refresh deletes completed automation history after
`CompanyConfig(automation_history_retention_days=30)` days, measured from the most
recent occurrence. The setting must be a positive integer. Routine history and
ordinary executor runs are unaffected. Retention also supports sync and async
MongoDB schedule storage paired with SQL Company storage. Synchronous
`CompanyManager.attention()` can be called from an application event loop.

New dispatch refuses a disabled Task owner and follows the user directory's
configured failure policy. An authorized collaborator can still cancel existing
work after its owner is disabled; recovery can still project a completed result.

`09_task_session_ownership.py` demonstrates Alice starting attempt 1 and Bob
starting attempt 2, with both runs owned by Alice and distinct `started_by` entries.
Run it with SQLite or `COMPANY_DB=postgres`; it uses a local workflow and the durable
PostgreSQL queue without a model call.

Starting AgentOS without Company disables an existing automation schedule with
`disabled_reason="company_off"`. Enabling Company again re-enables that row;
other disabled reasons are preserved. GET `/config` exposes `company.dbs` with
the configured Company database id and its Product, Project, Task, and Source
tables. The `company` key is null when Company is off. YAML Product declarations
can share their `company` section with optional `display_name` and `dbs` display
overrides.

The tick stops admitting work 240 seconds after its claim, before the scheduler's
default 300-second stale-lock threshold. It checks again after IO and before
acceptance or dispatch, without cancelling a database transaction. Releases match
both the worker ID and the claim timestamp on the built-in scheduler adapters,
so an expired invocation cannot release a later claim by that same worker.

Run both behaviors without a model call:

```bash
COMPANY_AUTOMATION=1 .venv/bin/python cookbook/05_agent_os/30_company/06_execute_tasks.py
COMPANY_AUTOMATION=1 COMPANY_DB=postgres .venv/bin/python cookbook/05_agent_os/30_company/06_execute_tasks.py
```

The example advances the existing schedule's due time to avoid an hour-long
wait. The poller still claims the schedule, and Tasks still enter the ordinary
executor run route and durable queue. A pending submission retains its original
attempt on restart. The queue owns execution retry limits; new ticks do not
start additional attempts for running or failed Tasks. A human can request a
retry using the existing run route. Returning queued work to Backlog prevents
its executor from starting. Once a Task has been accepted, returning it to
Backlog requires fresh human acceptance before another pickup; automation does
not treat it as a new proposal. This also applies to automatic policy withdrawals.
The distinct-Task policy budget is unchanged. Successful work remains In review.

An authenticated human needs `routines:write`, `schedules:write`, `tasks:write`,
`wiki:read`, and run permission for both the Routine target and the proposed Task
executor. Automatic acceptance rechecks wiki access before and after required
checks, so missing or revoked access leaves the proposal in Backlog without
spending its acceptance budget or queuing a run.
POST `/company/routines` accepts `auto_accept` at creation; PATCH
`/company/routines/{id}` can authorize, edit, or revoke it. For example, replace
the IDs below with real records and PATCH this body:

```json
{
  "auto_accept": {
    "executor_type": "agent",
    "executor_id": "writer",
    "source_ids": ["release-notes"],
    "work_scope": {
      "product_ids": ["documentation"],
      "project_ids": ["release-documentation"]
    },
    "required_checks": ["project_active", "has_source_evidence", "executor_registered"],
    "limits": {"max_acceptances": 5, "expires_at": 1798761600}
  }
}
```

Every authorization names an exact executor type and ID. A proposal with no
executor receives that authorized executor at acceptance. A proposal that names
an executor must name the same one. It must belong to the Routine's Product and
carry the framework's Routine origin. `propose_company_task` and
`intake_product_source` require a Project and can name a proposed executor; neither can
accept work. Source IDs and work scope are optional bounds. Omitted Source/scope
bounds impose no additional restriction; an empty allowed-ID list permits no matching work.
`project_ids` can include `null` for legacy Tasks without a Project; new Tasks require a Project. Unknown fields and
check names fail closed. A Source bound requires verified reader evidence.
Omitting `required_checks` defaults to `["executor_registered"]`; an explicit
empty check list is rejected. Every policy therefore runs at least one server-side
check. `limits.expires_at` is required on every policy creation or replacement,
including PATCH, and must be a UTC epoch-second timestamp in the future.
Automatic executors must be local and have a database for durable run storage.

| Built-in required check | Server-side fact checked |
| --- | --- |
| `project_active` | The proposal's Project exists, belongs to the same Product, and is active. Independent Tasks fail this check. |
| `has_source_evidence` | Evidence names an existing Source in this Product; a fresh read through its configured reader matches each content hash and link. An asserted hash or `passed` field is insufficient. |
| `executor_registered` | The proposed executor exists in the current registry and passes the ordinary Company executor checks. Registry validation is also mandatory for every acceptance and dispatch. |

`limits.max_acceptances` defaults to **1**. Each distinct Task counts at most
once per policy version, including archived Tasks; returning a Task to Backlog
and re-accepting it under the same policy does not spend another slot. The version
is a fingerprint of the executor, Source/work scope, checks and limits. Editing
that content (including raising a limit) starts a new version with its own budget.
Re-sending the same policy, refreshing a token, changing instructions or restarting
does not change the version or revoke its in-flight acceptances. The existing
Product row serializes accounting on SQLite and PostgreSQL so concurrent ticks
cannot exceed the limit. An early budget check skips exhausted proposals before
reading Sources or running application checks; the transaction still checks the
limit again. Changing the policy opens the new version's budget on the next tick.
Other failed checks are retried because server facts may change. Cheap built-in
checks and application checks run before Source IO. Source bounds
and `has_source_evidence` share one fresh evidence read per acceptance.

Applications can add checks with
`CompanyConfig(acceptance_checks={"custom_check": callable})`. Every built-in
and custom callable has the same `(task, manager)` signature: a copy of the
proposal and the sync or async Company manager for the configured database.
A callable may be sync or async and must return exactly `True` to pass. Errors,
false results, and missing names keep the proposal in Backlog. Built-in names
cannot be overridden. Registration is application code, never a Routine payload
or agent tool operation.

PATCH `{"auto_accept": false}` to revoke. Every tick reloads the schedule,
checks the saved human's current authority using the scheduler's authorization
conventions, and repeats the checks before acceptance. Changed or revoked
policies also block already accepted automatic work at dispatch and in the
queue. An unchanged Ready Task whose policy was withdrawn returns to Backlog
with the reason in its transition history, so it is visible for human attention.
Human acceptance snapshots use the same scheduler convention: stored-role
changes are re-evaluated; token-scope grants retain their saved scopes. Tasks
accepted before snapshots were introduced need fresh acceptance before pickup.
A disabled human cannot authorize automatic work through the user directory.
The Routine API validates executor registration and check names before saving a
policy; unknown names return 422. Generic schedule mutations of Company Routines
return 409: edit them through `/company/routines`. Direct Python ScheduleManager
payload writes strip acceptance grants; only the human API can issue them after
checking the caller's authority.

In a local deployment with authentication disabled, API callers are trusted
operators, as for the existing scheduler. Code/YAML declarations remain
proposal-only: write an automatic authorization through the human API.
Executors and Company Manager retain no `schedules:write` or SchedulerTools.
Private authorization is removed from public payloads and executor input;
Routine metadata is data, never a source of broader executor authority.

### Refresh, completion and retention

`refresh_company_product` proposes completion for active Projects with at least
one Task and only terminal Tasks. Each proposal is a versioned page under
`project-completion/`; unchanged scans do not rewrite it. New open work withdraws
the proposal. A human accepts it through the existing Project transition route.
Refresh cannot transition a Project. Moving a Project to Done returns 409 with
the open Task names and ids until every Task is Done or Cancelled, including
Tasks that were manually archived while still open.

Products store `metadata.archive_window_days`, default 14. Refresh soft-archives
Done and Cancelled Projects and Tasks whose last update is strictly older than
that window, falling back to creation time when no update exists. The delete
transaction rechecks age and terminal state. Project retention uses the same
cascading archive as manual archive: it refuses Ready, In progress or In review
Tasks, and archives remaining children even if their own updates are newer.
Refresh processes qualifying Projects before standalone Tasks, so a single
maintenance pass preserves the Project's cascade as one restorable group.
Restoring the Project restores only children taken by that cascade; Tasks
independently archived before that pass stay archived. Retention skips terminal
Projects that still contain Backlog work and refuses active Tasks. New open Tasks
cannot be added or moved into Done or Cancelled Projects.
Restore retains the lifecycle and starts a fresh retention window. Archived
records leave normal lists, grouped counts and execution. Read an individual
record with `include_deleted=true` for inspection; lists still hide children
of archived parents, so restore the parent first.
Refresh removes expired generated `summary.md` and completion-proposal pages
through version-guarded filesystem deletion; a concurrent replacement is kept.
Human pages, `brief.md` and `status.md`
are protected. The Refresh Skill updates status.md to reflect the remaining work.

The maintenance tool requires Routine authority, Product ownership when
isolation applies, `products:read`, `projects:read`, `projects:delete`,
`tasks:read`, `tasks:delete`, `wiki:read` and `wiki:write` on the saved caller.
No scheduler-write grant is added. Company Manager does not receive maintenance
or outbound Summary tools. Existing schedule instructions retain the scheduler's
snapshot behavior; apply the revised Refresh Skill through an authorized PATCH.

Products, Projects and Tasks list routes accept `sort_by=updated_at` and
`sort_order=asc|desc`. Activity ordering uses creation time for records without
an update and a deterministic id tie-breaker, before pagination. Omitting these
parameters preserves the existing creation-time descending order.

Optional Company tool arguments accept `null` for omission. Empty strings are
normalized to omission as well; omitted pagination uses 20 results on page 1.
Required identifiers and titles still require valid values.

Async PostgreSQL derives its default database ID from the connection URL and
schema, like synchronous PostgreSQL. Async SQLite already derives a stable ID
from its connection details. Reuse those details (or an explicit stable `id`)
after restart and across replicas so saved run database references resolve.
This does not rewrite references saved with older randomly generated IDs;
retaining a known old ID explicitly is necessary for those references.

### Bounded Project completion

`auto_accept.complete_projects` defaults to `false`, preserving existing Task-only
policy fingerprints and budgets. Set it to `true` on a
Refresh Routine to allow the automation tick to accept its persisted completion
proposals. The human author must also hold `projects:write`. Refresh itself only
proposes completion and archives eligible terminal work; it never accepts Tasks
or transitions a Project to Done.

Completion uses the same executor/run permission, Source and Product/Project
scope, required checks, expiry and count as Task acceptance. The proposed
Project must still be active, its Tasks (including archived Tasks) must all be
terminal, and its stored Refresh proposal must still match those facts. Checks
receive the Project as the work record, with `project_id` set to its ID and
`evidence` collected from its Tasks. The policy supplies the executor fields and
its executor still requires registry validation and the human's run permission.
`has_source_evidence` re-reads that evidence;
a Project without evidence fails Source bounds and that check. `project_active`
and `executor_registered` work without application registration.

Each distinct Project completion spends one slot in the same per-policy budget
as distinct Task acceptances. Archived records still count. The completion
permission is part of the policy fingerprint; changing it creates a new policy
version. Project completion creates no executor run. Existing Task completion
still requires human review.

### Custom Routines and discovered websites

Website Sources use public HTTP(S) addresses on standard ports. Each read checks
all DNS answers and pins the connection to an allowed public address; redirects
must stay on the configured origin. Private, loopback, link-local and reserved
local hosts are refused. Downloads use a 4 MiB byte limit and a 30-second deadline
covering resolution, redirects and streaming. Compressed responses are refused
to keep the byte bound meaningful. These restrictions apply to human-added and
agent-added website Sources; local files remain human-configured Sources.

Team executors record the team's injected id in `config.metadata.agent_id`.
Routine authority is bound to its Product even with isolation disabled. Ordinary
schedule mutation routes refuse Company-managed rows; use `/company/routines`.
An archived Product cannot dispatch its Routine: the scheduler records the refusal
and disables the schedule. Owners can still pause it; restore the Product before
explicitly resuming the Routine.

Repeated Routine Project proposals reuse an identity derived from Product,
Routine and proposal name, preserving human edits and archives. Intake's Task
dedupe survives completion and archive; a returned row with `deleted_at` set is
an archived existing proposal, not newly created work.

Supply Product declarations in code or YAML, not both. An explicit `CompanyConfig`
with no Products can still provide the database/model while YAML declares them.
Conflicting declaration lists fail clearly at startup instead of silently losing
one list.

Summary serializes delivery per Product with a versioned lease. A live overlapping
delivery is refused; retry after it finishes. A lost worker's lease expires after
ten minutes. Transport is bounded to one minute. Delivery remains at least once
across a crash after sending but before recording its receipt; interfaces do not
provide a common transactional delivery guarantee.

Run `08_custom_routines.py` to create a Routine with instructions and no template
or initial Sources, then add an attributed website through `CompanyTools`.
The example is offline; the integration tests execute custom and search-style
Routines through the scheduler and durable queue on all four SQL adapters.

`template` is optional. Without one, creation requires nonempty `instructions`.
With a template, creation copies its Skill text unless explicit instructions are
supplied. Name, instructions, executor type/id, cron expression and timezone can
be edited with PATCH. Executor edits reuse scheduler authorization and target
checks. If a policy is present, executor edits also recheck the human's permission
to run the policy executor and re-stamp the grant. Editing instructions preserves
the policy fingerprint and its spent acceptance budget. Stored instructions are
not refreshed when Skill files change.
A Routine with `template: null` never completes Projects automatically, even
when its policy sets `complete_projects: true`.
A custom Routine does maintenance only when it calls the Refresh tool, and
Summary bookkeeping only when it calls the Summary tool.

Company Manager and executors can call `add_product_source(product_id, reference, config=None)`
when granted `sources:write` and permitted to write the Product. Repository and
path Sources remain human-added. Source storage has a single existing JSON
field, `config`: server-stamped `config.metadata.agent_id` or
`config.metadata.team_id`, plus `config.metadata.run_id`, identify the first discovery.
The tool adds website Sources only; there is no `type` argument. These fields are not
reader options or model-supplied identities. Matching additions reuse the same
Source; conflicting settings or archived references are refused with the existing
Source id. Policies may name these website Sources in `source_ids`;
`has_source_evidence` reads and verifies them like human-added Sources.
A human can inspect provenance in GET `/company/sources` and archive
through DELETE `/company/sources/{id}`. AgentOS applies its isolation setting to
custom Company toolkits. Non-admin scoped tokens missing a subject are rejected
under isolation on Company reads as well as writes; the existing administrator
exemption is unchanged.

Summary's unresolved failures match attention: only Tasks still `in_progress`
with an ERROR or CANCELLED execution result appear under Failed Tasks. Moving
work on or archiving it removes that unresolved failure without deleting its
execution history.

## Routine controls and on-demand work

`GET /company/routines/{id}` returns the same Routine shape as the list.
Create, read, update, pause, and resume responses include `schedule_type`
(`scheduled` or `on_demand`) and `last_run`. The latter is null before the first
run, then contains `status`, `triggered_at`, `completed_at`, `run_id`,
`session_id`, and `error`. List pages fetch the latest runs together in one
query. Run history remains at `GET /company/routines/{id}/runs`.

Omit `cron_expr` (or use null) to create an on-demand Routine in code, YAML,
setup, or `POST /company/routines`. It stays enabled with `next_run_at: null`
and is never claimed by the poller. `PATCH /company/routines/{id}` with a cron
makes it scheduled; `{"cron_expr": null}` removes the schedule and keeps history.
Pause and resume also apply to on-demand Routines.

On-demand execution is a scheduler rule for all schedules. The generic schedule
API accepts an empty or omitted cron on creation and an empty cron on update;
omitting it from a PATCH preserves the current cron. Schedule responses expose
an empty stored cron as null. These schedules run only through trigger, with
`next_run_at` remaining null across polling, restart, and pause/resume.

With the scheduler enabled, `POST /company/routines/{id}/trigger` starts one
execution and returns its schedule-run record when it finishes. It uses the
same owner and executor permission checks as the other Routine controls;
paused Routines return 409. Automation and non-Company schedule IDs return 404.
A concurrent GET exposes the live `last_run.run_id` and `session_id` while
execution is running. Stop uses the existing executor cancel route, such as
`POST /agents/{executor_id}/runs/{run_id}/cancel` (or the equivalent Team or
Workflow route). There is no separate Routine stop operation.

`08_custom_routines.py` demonstrates on-demand declaration, single read, pause,
resume, and adding/removing a cron without calling a model.


## Named arguments for Company mutations

The long `CompanyManager` and `AsyncCompanyManager` mutation methods require
keyword arguments: `create`, `create_project`, `create_task`, `transition_project`,
`transition_task`, `write_wiki`, `log_decision`, `create_source`, `add_source`,
`intake`, and `summarize`. Name the fields explicitly, for example
`manager.create_project(product_id=product["id"], name="Release")`. The sync and
async signatures match; short lookup and update methods retain their existing
calling convention.


Routine `last_run` uses creation-ordered scheduler history identifiers to resolve
executions started within the same second. History IDs are opaque strings; they
are distinct from the executor `run_id` used to cancel a live run. Existing history
is retained, although the order of old UUID-only records with identical timestamps
cannot be reconstructed. Pause and resume return the same Routine resource shape
as a single read, including `last_run`.

Python `ScheduleManager.update(enabled=True)` and `aupdate(enabled=True)` re-arm
recurring schedules using their current cron and timezone. On-demand schedules
remain enabled with a null deadline. Clearing a cron during execution also keeps
the deadline null after release on SQL and MongoDB storage.

### Sandboxed engineering executors

[09_sandboxed_engineers.py](09_sandboxed_engineers.py) configures one reusable
ClaudeAgent and one CodexAgent with `repository=Repository(...)`. Select either
with `--executor claude` or `--executor codex`. Both use the public
`octocat/Hello-World` repository, Docker `network="isolated"`, and an explicit
`checkpoints=FileCheckpointStore(...)`. `--config-only` makes no model calls.

The Product has a matching git Source URL and `config.branch` names its default
branch. The agent's Repository config selects the checkout branch. Acceptance
checks the URL; the sandbox resolves and publishes the commit on its first turn.
The first successful completion records the pin, including a successful retry
after an earlier failed or cancelled attempt. The Task retains
`{source_id, url, branch, commit}` in `metadata.checkout` and later attempts
reuse its session and verify that pin at completion. Recovery of a completed run
uses the same pin validation and saves the checkout atomically with its result.
A checkout validation error can be retried after repairing its cause. Reacceptance
requires a sandboxed executor with the same repository and branch once a checkout
is pinned. Use a new Task for a non-sandboxed executor or a different repository.
A second sandboxed Task start receives 409 while another has a live job, including after that Task is
returned to Backlog, reassigned or archived. Ordinary agents remain eligible
and report `sandboxed: false`. This marker is derived from the component and
cannot be set on a Task.

Deployment requirements:

- PostgreSQL for executor runs and the durable queue; Redis for queue coordination.
  SQLite is supported for local Company records, but sandbox executor state is
  PostgreSQL-backed.
- An explicit checkpoint store on one host, or a shared checkpoint filesystem
  across replicas. Local checkpoint directories are not portable between hosts.
- Docker with `network="isolated"` (or AgentCore with network access). Egress
  filtering belongs to the deployment. No Docker socket or privileged container.
- Set `workspace_mb` for the shallow clone and tools: this example uses 2048 MiB,
  suitable for an Agno checkout plus a virtual environment. Checkpoints have a
  1 GiB cap. Set `execution_timeout` for the intended test run; the example uses
  1800 seconds within the provider lifetime.
- For Agno development, build the engineering image with development dependencies,
  PostgreSQL/pgvector and Redis running as unprivileged processes with disposable
  data under `/tmp`. Run targeted tests there; full CI remains the release check.
- Public repositories need no git credentials. Private repositories use a
  read-only token in `Sandbox.env["GITHUB_READ_TOKEN"]`; the matching Source's
  `credential_ref` must be `GITHUB_READ_TOKEN`, and acceptance checks that the
  executor has that variable in `Sandbox.env`. Never pass a write credential to
  the sandbox. Local-path git Sources remain read-only; URL Source HTTP reads
  and publishing are outside this example.

Set `SANDBOX_IMAGE`, `SANDBOX_CHECKPOINTS`, `DATABASE_URL`, and `REDIS_URL` for your
deployment, plus the selected harness's model API key. Running the example
without `--config-only` makes a real model call and leaves its Task for review.
