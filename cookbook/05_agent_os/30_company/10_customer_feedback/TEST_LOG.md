# Customer feedback cookbook test log

## 2026-10-23

### company_os.py — startup and live UI workflow

**Status:** PASS

**Description:** Tested GPT-6.1 Sol against synthetic Markdown customer feedback.
Connected the AgentOS UI, triggered the Routine, inspected generated Projects and
Tasks, selected Feedback Analyst, saved the executor, and changed a Task from
Backlog to To do. Company automation dispatched the accepted Task.

**Result:** The Task reached Reviewing with a saved product brief and regression
plan (13,560 characters). The other Task remained in Backlog. The result
explicitly distinguished proposed behavior from verified implementation. The
initial UI exercise used the development checkout with the Company Manager
routine lookup repair. The PR uses current main's existing manager support and
Product-scoped Source tool names; its separate scheduled execution check is
recorded below.

---

### Source quality and authority checks

**Status:** PASS

**Description:** Live Sol runs covered first discovery, repeat discovery,
positive/resolved feedback, an empty folder, and an unavailable folder.

**Result:** Discovery identified both actionable themes; a repeat created no
extra work; quiet and empty inputs created no work; a missing folder produced
a failed Routine. Proposals retained evidence links and content hashes and
stayed in Backlog. Built-in managers were rejected as Task executors. Separate
source checks covered recursive discovery, paging over 127 files, sync/async
parity, changed evidence, path traversal and symlink confinement.

---

### Clean PR validation

**Status:** PASS

**Description:** Ran `./scripts/format.sh` and `./scripts/validate.sh` on current
main plus this cookbook, using Python 3.10 and the repository's development
extras in an isolated environment.

**Result:** Both scripts passed. Earlier broad validation on the development
checkout passed 1,091 integration tests (8 skipped), 222 unit tests, and the
follow-up affected integration selection passed 145 tests. These earlier
counts are development-checkout evidence, not an exact-PR test count.

---

### company_os.py — scheduled execution on the PR checkout

**Status:** PASS

**Description:** Started the exact PR cookbook against a fresh PostgreSQL schema
with GPT-6.1 Sol. Temporarily set discovery to the next minute to exercise the
real scheduler, then restored the daily 09:00 UTC schedule.

**Result:** Scheduled discovery completed and created two evidence-backed Tasks
in Backlog. Accepted one Task through the API with Feedback Analyst as executor.
Company automation dispatched it automatically through ready, in_progress, and
in_review. The saved result contained a 14,749-character implementation brief
and regression plan. The unaccepted Task remained in Backlog. This verifies
the PR checkout independently of the earlier development-checkout UI exercise.

---

## 2026-10-23 — 95-simulation stress test

**Status:** PASS for sequential, human-approved operation; FAIL for duplicate
prevention during overlapping reviews.

**Environment:** GPT-6.1 Sol, an isolated local PostgreSQL schema, durable queue,
and the cookbook from PR #11271 at `33796bec1243`. The final five executions used
the source-path instruction improvement described below. These were live model
runs through AgentOS HTTP endpoints, not mocked model responses or repeated UI
clicks. Discovery batches ran with up to six concurrent reviews; independent
scenario groups and accepted Task executions also overlapped.

| Simulation group | Runs | Result |
| --- | ---: | --- |
| Sequential discovery/review | 76 | All met expectations |
| Same-Product overlapping review | 6 (3 pairs) | Two pairs created duplicate Tasks; one also duplicated the Project |
| Accepted Task execution | 13 | All reached Reviewing with persisted deliverables |
| **Total** | **95** | **91 met expectations; 4 runs exposed the overlap defect** |

Coverage included positive/resolved feedback, empty and unavailable folders,
non-Markdown files, nested Unicode paths, multilingual reports, contradictory
evidence, single severe reports, different product domains, eight malicious
instruction cases, repeated reviews, new evidence, and review after execution.
The unavailable-folder run correctly failed; it recovered after the folder was
restored. This expected failure is counted as a passing test.

The reviewer read all 105 files in the large-directory case and found the only
issue in the last file. A 40,187-byte document was read in three content pages.
Thirty duplicate reports produced one Task. All 12 unchanged-input reruns reused
existing work. New issues added to four previously quiet Products produced new
work; resolution updates produced no new work and left lifecycle decisions to
the human.

**Approval and persistence:** No unaccepted Task ran, no Project was automatically
approved, and all Routines retained `auto_accept=False`. A global audit found no
unexpected Products, Sources, Routines, or Product-definition changes. A graceful
server restart preserved every record ID, prior deliverable, and other Task
state. A Task accepted just before shutdown dispatched automatically after
restart and reached Reviewing. This does not test recovery from a process crash
while a model call is running.

**Deliverables:** All 13 executions read Source evidence and saved substantial
briefs with acceptance criteria and regression plans. Automated checks verified
source scope, final run status, preserved Task briefs/Project definitions, and
no extra work. Manual inspection of representative outputs confirmed that
unverified reports, contradictory evidence, assumptions, and proposed test
results were distinguished. These planning artifacts do not prove an application
fix or executed regression tests.

**Cookbook improvement:** Three of the original eight executions first supplied
a file URL or absolute path to `read_product_source`. Each recovered and
completed, but the attempts produced avoidable tool errors. The executor now
lists the Source, uses its returned relative path, and follows content pagination.
Retests of those three cases, a clean control, and the post-restart execution
all completed with zero Source tool errors.

**Known framework limitation:** Two simultaneous triggers can both observe no
existing work and choose different `proposal_key` values for the same issue.
Both runs then persist valid, evidence-backed Backlog Tasks. This reproduced in
two of three independent pairs; one pair also chose different Project names.
The database's exact-key deduplication does not reconcile semantic duplicates.
The README now instructs users to wait for a review to finish before triggering
another. Serializing discovery for a Product across manual and scheduled
triggers is the recommended framework follow-up; this PR does not implement it.

**Assessment limits:** Synthetic feedback, one local server/database, and a
bounded set of model runs. This is evidence for a sequential planning example,
not a guarantee for arbitrary inputs, concurrent discovery, provider outages,
multi-replica operation, or shipped product improvements. Suggested executors
on Backlog Tasks were treated as suggestions, not acceptance; state and job
records determined whether work was authorized.

---
