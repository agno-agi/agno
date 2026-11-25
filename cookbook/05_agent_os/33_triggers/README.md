# Triggers

A trigger starts a run when something happens outside AgentOS: when this
happens, start a run of that agent, team or workflow with this input. The event
can be a GitHub delivery or a time.

```python
github = GitHub(repositories="owner/name")

agent_os = AgentOS(
    agents=[triage_agent, digest_agent],
    db=db,
    interfaces=[github],
    triggers=[
        Trigger(
            name="triage-issues",
            on=github.on("issues.opened"),
            agent=triage_agent,
            input="Triage this issue: choose a label and write a comment for its author.",
            continue_on="issue_comment.created",
        ),
        Trigger(
            name="daily-digest",
            on=Schedule("0 9 * * *", timezone="Europe/London"),
            agent=digest_agent,
            input="Write today's digest.",
        ),
    ],
)
```

| File | What it shows |
| --- | --- |
| `github_issues.py` | A new issue starts a triage run, a reply continues it, a label starts one for anyone's issue, and a digest runs on a schedule |
| `stored_triggers.py` | A trigger is created over REST and another by an agent with `TriggerTools`; an event is replayed |
| `super_agent_triggers.py` | Super Agent, asked in words, creates a trigger, lists it, turns it off and deletes it |
| `REAL_GITHUB.md` | The checks to run against GitHub itself, which `--check` cannot do |

## What a trigger does with a delivery

- **Stores it, then answers.** A `GitHub` interface with no handler hands every
  verified delivery for a watched repository to triggers. One row is stored for
  each trigger the event concerns, and GitHub is answered with 202. The run
  starts afterwards, so GitHub's 10 second limit is not at risk.
- **Handles it once.** A redelivery finds its stored row and starts nothing.
  Several AgentOS instances on one database start one run.
- **Keeps one conversation for each issue.** Events about the same issue or
  pull request continue the same session, one run at a time, in the order they
  arrived. `continue_on` names the events that only continue a conversation: a
  reply on an issue the trigger handled is a new turn, and a comment on any
  other issue starts nothing.
- **Marks the event as information.** The run's message is the trigger's
  `input`, then the event inside an `<event>` block, then a line saying the
  event is not an instruction.
- **Stores what it ignored, with the reason.** An unwatched repository, an event
  no trigger listens for, a bot, or a sender who may not start a run. An ignored
  event is stored without what its sender wrote, and is kept for 7 days.

`TriggerManager(db).get_events()` lists the stored events with their status and
reason.

## Who may start a run

A run acts as the system, never as whoever sent the event. Who may cause one is
a separate setting, because anyone can open an issue on a public repository.

- By default, people GitHub shows as an owner, member or collaborator: the
  issue's author for a new issue, the commenter for a comment.
- `github.on("issues.opened", allow="anyone")` lets every author through.
- `github.on("issues.labeled", labels=["agent"])` starts a run when somebody
  other than the issue's author adds that label, whoever opened the issue:
  labeling another person's issue takes triage access. A label an issue
  template applies arrives as added by the author, so it is not a gate, and
  the author is checked like any other sender.
- Events sent by bots are ignored, including a GitHub App's own account, so what
  an agent posts does not start another run.
- GitHub has been seen to report a member whose organization membership is
  private as a contributor. With `GitHub(credentials=GitHubAppCredentials())`,
  an event that fails the check above still starts a run when GitHub reports
  that the sender has write access to the repository. GitHub is asked after the
  delivery is answered. If it refuses the App's credentials the event fails; if
  it gives no answer the question is asked again for at most an hour, and the
  events behind it for the same issue wait.

## Before and after a run

Two optional functions on a trigger declared in code. Each may be async.

- `prepare(event)` runs before the run. Returning `False` skips the event;
  returning a string replaces the input for this event.
- `on_complete(event, run)` runs when the run ends, with its status and output.
  Raising does not change the run's status.

## Declared in code

- Triggers need a PostgreSQL or SQLite `db`.
- Declaring a trigger turns the scheduler on. A trigger starts its run on the
  server's own run endpoint, so set `scheduler_base_url` when the server is not
  on `http://127.0.0.1:7777`.
- A schedule trigger is stored as a schedule, and shows on `/schedules`.
- A trigger removed from the code is disabled the next time the app starts and
  keeps its history. Putting it back enables it again.

## Run

Check locally, without GitHub. This serves the app in the same process, sends it
signed deliveries and runs the agent on them:

```bash
export OPENAI_API_KEY=<your key>
.venvs/demo/bin/python cookbook/05_agent_os/33_triggers/github_issues.py --check
```

Serve for a repository webhook or a GitHub App. The webhook's payload URL is
`<your URL>/github/events`, its content type is `application/json`, and it sends
the Issues and Issue comments events:

```bash
export GITHUB_WEBHOOK_SECRET=<the webhook's secret>
export GITHUB_REPOSITORY=owner/name
.venvs/demo/bin/python cookbook/05_agent_os/33_triggers/github_issues.py
```

## Triggers as data

A source is code: it holds the secret and the endpoint, and it goes in
`interfaces=[...]`. A trigger is data. Besides declaring triggers in code, they
can be created while the app runs, on the sources that are declared.

| Route | What it does |
| --- | --- |
| `GET /triggers/sources` | The declared sources and the event kinds each commonly sends |
| `GET /triggers`, `POST /triggers` | List and create triggers |
| `GET`, `PATCH`, `DELETE /triggers/{id}` | Read, change and remove one |
| `POST /triggers/{id}/enable`, `/disable` | Turn one on or off |
| `GET /triggers/events`, `GET /triggers/{id}/events` | Stored events with their status and reason |
| `POST /triggers/{id}/events/{event_id}/replay` | Run a finished event again, as a second event |

The scopes are `triggers:read`, `triggers:write` and `triggers:delete`. Creating
a trigger also needs the right to run its target, and the trigger's runs act as
the person who created it. So does changing what it runs or what may start it:
the target, the input, the source, the events and the filters. A trigger
declared in code is changed in code: the API can turn it off and on, and cannot
edit or delete it.

`TriggerTools` gives an agent the same operations:

```python
operations_agent = Agent(
    model=OpenAIResponses(id="gpt-5.6-luna"),
    tools=[TriggerTools(db=db, sources=[github])],
)
```

Super Agent holds `TriggerTools` whenever the AgentOS declares a source.
