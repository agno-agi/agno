# Customer feedback in the AgentOS UI

Company Manager reviews local Markdown feedback with `gpt-6.1-sol`, proposes
Projects and evidence-backed Backlog Tasks, and leaves acceptance to you.
After approval, Feedback Analyst writes a product brief and regression test plan.
Its complete response is saved on the Task for review. This example produces
planning documents; implementing a code fix requires an engineering executor
and access to the application repository.

## Start

Run from the Agno repository root using this checkout, which includes support for
built-in Company Manager Routines. The sample feedback is synthetic.

```bash
# If the development environment does not exist:
./scripts/dev_setup.sh

# Start PostgreSQL if nothing is already listening on port 5532:
./cookbook/scripts/run_pgvector.sh

export OPENAI_API_KEY="your-api-key"
.venv/bin/python cookbook/05_agent_os/30_company/10_customer_feedback/company_os.py
```

The server listens at `http://127.0.0.1:7777`. PostgreSQL stores Company records,
agent runs and the durable queue in the `customer_feedback_ui` schema. SQLite
cannot provide this example's durable queue. Redis is not required for this
single-server example.

Optional configuration:

```bash
export FEEDBACK_DATABASE_URL="postgresql+psycopg://ai:ai@localhost:5532/ai"
export FEEDBACK_DB_SCHEMA="customer_feedback_ui"
export FEEDBACK_PORT="7777"
```

Use a different schema for a fresh test without deleting earlier results.
Changing the port also updates the scheduler's callback URL. Source paths are
relative to this example's file, so launching from another directory still
reads the same `feedback/` folder.

## Test in the UI

1. Sign in at [AgentOS](https://os.agno.com) and connect a local AgentOS endpoint
   at `http://127.0.0.1:7777` (or your configured port). This local example has
   no AgentOS authentication token configured.
2. Open Company and the **Customer Feedback** Product. Inspect its purpose,
   Source, Projects and Routines.
3. Run **review-feedback** from the Product's Routines. You can trigger it now;
   the daily schedule is 09:00 UTC while the server is running.
4. Inspect the resulting Projects and Tasks. The sample evidence contains two
   actionable themes: cross-midnight CSV export failures and missing timezone
   labels. Positive onboarding feedback and an already resolved email issue
   should produce no work. Exact titles and Project grouping can vary.
5. Wait for the Routine to finish, then run it again without changing the files.
   Verify that it reuses the existing work. Tasks should remain in **Backlog** until you approve them.
6. Open a Task and inspect its brief and evidence. Select **Feedback Analyst**
   (`feedback-analyst`) as its executor and accept it, moving it to **To do** (the API state is `ready`).
   This example configures Company automation to check accepted work once per minute, so dispatch may
   take about a minute. The Task then moves through **In progress** to **Reviewing** (the API state is `in_review`).
7. Read the saved result and run history. The deliverable should contain the
   observed problem, supporting source links, proposed behavior, acceptance
   criteria, regression cases and open questions. Mark it **Done** only after
   you have reviewed it.

Company Manager handles discovery. Feedback Analyst executes accepted Tasks;
the built-in managers cannot be selected as business Task executors.
`auto_accept=False` keeps discovery from authorizing execution.

Run one review at a time for a Product. Overlapping manual or scheduled reviews
can create duplicate proposals: separate runs may choose different issue keys
before either sees the other's work. Check existing run status before triggering
another review, and inspect proposals before accepting them.

The UI requires its own sign-in. The UI walkthrough and persisted REST results were tested locally. After selecting
**Agent → Feedback Analyst**, save the Task, then change its status from
**Backlog** to **To do**. UI labels may differ between frontend versions.

## Try more feedback

Add customer notes, issue summaries or support conversations as `.md` or
`.markdown` files under `feedback/`, then trigger the Routine again. Nested
folders are supported. Keep credentials and unrelated private files out of
this folder. Emails and support conversations must first be saved here;
this example does not fetch inboxes or support systems.

Useful checks:

- Add a genuinely new issue: expect new evidence-backed work for that issue.
- Add another report of an existing issue: expect reuse, not a duplicate Task.
- Use a fresh schema and only positive or resolved feedback: expect no work.
- Remove the configured folder: expect a failed Routine with a Source error.
- Restart the server: existing proposals, decisions, run history and acceptance
  should remain. Declarations do not reset edits made through the UI.

Pause the Routine in the UI to stop daily reviews. Stop the server with Ctrl+C
when finished. Startup itself does not trigger feedback review; manual triggers
and scheduled runs make model calls.
