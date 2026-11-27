"""Super Agent reads what an agent changed in its sandbox checkout, from the checkout the sandbox saved."""

import asyncio
import json
import re
import shutil
import subprocess
from dataclasses import asdict

import pytest

from agno.agent import Agent
from agno.agents.claude import ClaudeAgent
from agno.db.postgres import PostgresDb
from agno.db.sqlite import SqliteDb
from agno.offload.store import DEFAULT_THRESHOLD_CHARS
from agno.os import AgentOS, OSManager
from agno.os.authz.provider import AuthorizationContext
from agno.os.authz.scope_provider import ScopeAuthorizationProvider
from agno.os.manager import background_runs
from agno.os.manager.background_runs import DIFF_LENGTH, BackgroundRunTools
from agno.os.manager.finished_work import READ_TOOLS
from agno.os.manager.prompts import SANDBOX_CHANGES_INSTRUCTIONS
from agno.registry import Registry
from agno.run import RunContext
from agno.run.authorization import RunAuthorization, authorization_scope
from agno.sandbox import Repository, Sandbox
from agno.sandbox.checkpoint import CheckpointArchive, FileCheckpointStore
from agno.tools.studio_runner import StudioRunnerTools
from tests.unit.os.test_mini_agent_tasks import ScriptedModel

pytestmark = [
    pytest.mark.usefixtures("unavailable_manager_docs"),
    pytest.mark.skipif(shutil.which("git") is None, reason="the reader compares a checkout with git"),
]

URL = "postgresql+psycopg://ai:ai@localhost:1/ai"
REPOSITORY = Repository(url="https://github.com/acme/platform", branch="main")
SETTINGS = 'def default_model():\n    """Fresh model instance per agent."""\n    return "gpt"\n'
modes = pytest.mark.parametrize("mode", ["sync", "async"])


class GoneSandbox(Sandbox):
    """A sandbox whose computer is gone: every call that would reach one fails. It keeps its checkpoints."""

    def __init__(self, checkpoints):
        self.checkpoints = checkpoints
        self.network = "isolated"

    async def acreate(self, session_id, *, agent_id=None, generation=1, env=None):
        raise AssertionError("reading the changes must not create a sandbox")

    async def afind(self, session_id, **kwargs):
        raise AssertionError("reading the changes must not look for a sandbox")

    async def aget(self, provider_ref):
        raise AssertionError("reading the changes must not look for a sandbox")

    async def aexec(self, handle, argv, **kwargs):
        raise AssertionError("reading the changes must not run anything in a sandbox")

    async def aresume(self, handle):
        raise AssertionError("reading the changes must not resume a sandbox")

    async def astop(self, handle):
        raise AssertionError("reading the changes must not stop a sandbox")

    async def adestroy(self, handle):
        raise AssertionError("reading the changes must not remove a sandbox")


def git(directory, *args):
    done = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false", *args],
        cwd=directory,
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout.strip()


class Saved:
    """The checkouts a sandbox saved: a real repository, captured into a real checkpoint store."""

    def __init__(self, tmp_path):
        self.root = tmp_path
        self.checkout = tmp_path / "live" / "workspace" / "repository"
        self.checkout.mkdir(parents=True)
        (tmp_path / "live" / "native").mkdir()
        (self.checkout / "app").mkdir()
        (self.checkout / "app" / "settings.py").write_text(SETTINGS)
        (self.checkout / "README.md").write_text("# Platform\n")
        (self.checkout / ".gitignore").write_text("build/\n")
        git(self.checkout, "init", "--quiet")
        git(self.checkout, "add", "--all")
        git(self.checkout, "commit", "--quiet", "-m", "base")
        self.commit = git(self.checkout, "rev-parse", "HEAD")
        self.store = FileCheckpointStore(tmp_path / "objects")
        self.captures = 0

    def capture(self):
        """Save the checkout as a completed turn does, and return the reference a run row records."""
        self.captures += 1
        archive = self.root / f"checkpoint-{self.captures}.tar"
        live = self.root / "live"
        CheckpointArchive().capture(
            {"workspace": live / "workspace", "native": live / "native"}, archive, state={"binding": "b"}
        )
        return self.store.put(archive)

    def row(self, reference=None, *, run_id="run-1", session="", status="COMPLETED", user="alice", index=1, **pin):
        sandbox = {"repository": {"url": REPOSITORY.url, "branch": REPOSITORY.branch, "commit": self.commit, **pin}}
        if reference is not None:
            sandbox["checkpoint"] = asdict(reference)
        return {
            "run_id": run_id,
            "agent_id": "engineer",
            "session_id": session,
            "user_id": user,
            "status": status,
            "run_index": index,
            "created_at": index,
            "run_data": {"run_id": run_id, "status": status, "metadata": {"sandbox": sandbox}},
        }


@pytest.fixture
def saved(tmp_path):
    return Saved(tmp_path)


def database(monkeypatch, rows):
    """The engineer's database, holding these run rows. Nothing connects."""
    db = PostgresDb(db_url=URL)
    asked = []

    def get_runs(session_id=None, **kwargs):
        asked.append(session_id)
        return [row for row in rows if row["session_id"] == session_id], len(rows)

    monkeypatch.setattr(db, "get_runs", get_runs)
    monkeypatch.setattr(db, "get_run", lambda run_id, deserialize=True: next(r for r in rows if r["run_id"] == run_id))
    db.asked = asked
    return db


def person(scopes=("agents:engineer:run", "tasks:read"), user="alice", session="chat"):
    authority = RunAuthorization(
        ScopeAuthorizationProvider(),
        AuthorizationContext(principal_id=user, scopes=list(scopes), claims={"sub": user}),
    )
    return RunContext(run_id="chat-run", session_id=session, user_id=user, authorization=authority, session_state={})


class Reader:
    """Super Agent's run tools over one sandboxed engineer and the run rows a test gives it."""

    def __init__(self, monkeypatch, saved, company=None):
        self.rows: list = []
        self.db = database(monkeypatch, self.rows)
        self.engineer = ClaudeAgent(
            id="engineer", name="Engineer", db=self.db, sandbox=GoneSandbox(saved.store), repository=REPOSITORY
        )
        self.writer = Agent(id="writer", name="Writer", model=ScriptedModel())
        self.os = type("OS", (), {"dbs": {}, "db": None, "_company_db": company, "registry": None})()
        self.tools = BackgroundRunTools(self.os, sandbox_changes=True, include_agents=[self.engineer, self.writer])

    def session(self, run_context):
        return StudioRunnerTools._sub_session_id(run_context, "agent", "engineer")

    def read(self, run_context, mode="async", **arguments):
        with authorization_scope(lambda: run_context.authorization):
            if mode == "sync":
                return json.loads(self.tools.read_sandbox_changes(**arguments, _agno_run_context=run_context))
            return json.loads(asyncio.run(self.tools.aread_sandbox_changes(**arguments, _agno_run_context=run_context)))


@pytest.fixture
def reader(monkeypatch, saved):
    return Reader(monkeypatch, saved)


def edit(saved):
    """What an engineer left: one line changed and committed, one more uncommitted, a new file, an ignored one."""
    settings = saved.checkout / "app" / "settings.py"
    settings.write_text(SETTINGS.replace("Fresh model instance per agent.", "Return the gpt model."))
    git(saved.checkout, "commit", "--quiet", "-am", "docstring")
    (saved.checkout / "README.md").write_text("# Platform\n\nReviewed.\n")
    (saved.checkout / "notes.txt").write_text("a new file\n")
    (saved.checkout / "build").mkdir()
    (saved.checkout / "build" / "out.bin").write_text("ignored\n")


# ----------------------------------------------------------------- the diff


@modes
def test_the_changed_files_and_the_diff_are_read_from_the_saved_checkout(reader, saved, mode):
    edit(saved)
    run_context = person()
    reader.rows.append(saved.row(saved.capture(), session=reader.session(run_context)))
    result = reader.read(run_context, mode, agent_id="engineer")
    assert "error" not in result
    assert {entry["path"]: entry["change"] for entry in result["changed_files"]} == {
        "README.md": "modified",
        "app/settings.py": "modified",
        "notes.txt": "added",
    }
    assert result["changed_files"][0] == {
        "path": "README.md",
        "change": "modified",
        "lines_added": 2,
        "lines_removed": 0,
    }
    # Committed and uncommitted changes and a new file are all in the diff; an ignored file is not.
    assert '+    """Return the gpt model."""' in result["diff"]
    assert '-    """Fresh model instance per agent."""' in result["diff"]
    assert "+Reviewed." in result["diff"] and "+a new file" in result["diff"]
    assert "out.bin" not in result["diff"]
    assert result["base_commit"] == saved.commit and result["run_id"] == "run-1"
    assert result["repository"] == REPOSITORY.url and result["agent_id"] == "engineer"
    assert "note" not in result
    # The session read is the one this conversation's runs of the engineer enter, and no other.
    assert reader.db.asked == [reader.session(run_context)]


@modes
def test_a_display_name_names_the_agent(reader, saved, mode):
    edit(saved)
    run_context = person()
    reader.rows.append(saved.row(saved.capture(), session=reader.session(run_context)))
    assert reader.read(run_context, mode, agent_id="Engineer")["run_id"] == "run-1"


@modes
def test_no_changes_is_said_plainly(reader, saved, mode):
    run_context = person()
    reader.rows.append(saved.row(saved.capture(), session=reader.session(run_context)))
    result = reader.read(run_context, mode, agent_id="engineer")
    assert result["changed_files"] == [] and result["diff"] == ""
    assert result["note"] == "No file differs from base_commit: this agent changed nothing in its checkout."


@modes
def test_a_cut_diff_says_how_much_is_missing(reader, saved, mode):
    edit(saved)
    (saved.checkout / "big.txt").write_text("".join(f"line {number}\n" for number in range(3000)))
    run_context = person()
    reader.rows.append(saved.row(saved.capture(), session=reader.session(run_context)))
    result = reader.read(run_context, mode, agent_id="engineer")
    # The whole diff holds each of the 3000 added lines, about 34,000 characters.
    length = int(re.search(r"of (\d+) characters", result["note"]).group(1))
    assert length > 30000
    missing = length - DIFF_LENGTH
    assert result["note"] == (
        f"The diff is cut. It shows the first {DIFF_LENGTH} of {length} characters: {missing} more are not "
        "shown, so this is not the whole change. changed_files lists every changed file; call again with path "
        "to read one file's diff."
    )
    marker = f"\n[The diff is cut here: {missing} more characters are not shown.]"
    assert result["diff"].endswith(marker) and len(result["diff"]) == DIFF_LENGTH + len(marker)
    assert result["diff"].startswith("diff --git a/README.md b/README.md")
    # A cut result is still short enough to be shown to Super Agent whole, not as a preview.
    assert len(json.dumps(result)) < DEFAULT_THRESHOLD_CHARS
    # The note comes before the diff, and the list of files is whole whatever was cut.
    assert list(result).index("note") < list(result).index("diff")
    assert {entry["path"] for entry in result["changed_files"]} == {
        "README.md",
        "app/settings.py",
        "big.txt",
        "notes.txt",
    }
    # One file's diff is read by its path.
    one = reader.read(run_context, mode, agent_id="engineer", path="notes.txt")
    assert "+a new file" in one["diff"] and "big.txt" not in one["diff"] and "note" not in one
    other = reader.read(run_context, mode, agent_id="engineer", path="app/missing.py")
    assert other["diff"] == "" and other["note"] == "app/missing.py is not among the changed files."


@modes
def test_a_long_list_of_files_is_cut_and_says_so(reader, saved, mode, monkeypatch):
    monkeypatch.setattr(background_runs, "_FILES_LISTED", 2)
    edit(saved)
    run_context = person()
    reader.rows.append(saved.row(saved.capture(), session=reader.session(run_context)))
    result = reader.read(run_context, mode, agent_id="engineer")
    assert len(result["changed_files"]) == 2
    assert "changed_files shows the first 2 of 3 changed files: 1 more are not listed." in result["note"]


# ----------------------------------------------------------------- the sandbox is gone


@modes
def test_the_read_never_reaches_the_sandbox(reader, saved, mode):
    """Every compute call of the test sandbox fails, as for a sandbox that was removed: the read still answers."""
    edit(saved)
    run_context = person()
    reader.rows.append(saved.row(saved.capture(), session=reader.session(run_context)))
    assert "+Reviewed." in reader.read(run_context, mode, agent_id="engineer")["diff"]


@modes
def test_a_saved_checkout_that_is_gone_too_is_said_plainly(reader, saved, mode):
    edit(saved)
    run_context = person()
    reference = saved.capture()
    reader.rows.append(saved.row(reference, session=reader.session(run_context)))
    saved.store.delete(reference)
    assert reader.read(run_context, mode, agent_id="engineer") == {
        "error": "The checkout saved by run run-1 is no longer in checkpoint storage, so its changes cannot be "
        "read. A sandbox keeps the checkouts of its last few runs only."
    }


@modes
def test_a_later_run_that_did_not_complete_is_named(reader, saved, mode):
    edit(saved)
    run_context = person()
    session = reader.session(run_context)
    reader.rows.append(saved.row(saved.capture(), session=session))
    reader.rows.append(saved.row(None, run_id="run-2", session=session, status="ERROR", index=2))
    result = reader.read(run_context, mode, agent_id="engineer")
    assert result["run_id"] == "run-1" and "+Reviewed." in result["diff"]
    assert result["note"] == (
        "A later run (run-2) is error and saved no checkout: these are the files as run run-1 left them."
    )


@modes
def test_the_newest_saved_checkout_is_the_one_read(reader, saved, mode):
    run_context = person()
    session = reader.session(run_context)
    reader.rows.append(saved.row(saved.capture(), session=session))
    edit(saved)
    reader.rows.append(saved.row(saved.capture(), run_id="run-2", session=session, index=2))
    result = reader.read(run_context, mode, agent_id="engineer")
    assert result["run_id"] == "run-2" and "+Reviewed." in result["diff"] and "note" not in result


@modes
def test_a_run_that_never_completed_has_nothing_to_read(reader, saved, mode):
    run_context = person()
    reader.rows.append(saved.row(None, session=reader.session(run_context), status="RUNNING"))
    assert reader.read(run_context, mode, agent_id="engineer") == {
        "error": "Engineer has no completed run in this conversation: its latest run is running. A sandbox "
        "saves its checkout only when a run completes, so there are no changes to read yet."
    }
    reader.rows.clear()
    assert reader.read(run_context, mode, agent_id="engineer") == {
        "error": "Engineer has not run in this conversation, so there are no changes to read."
    }


# ----------------------------------------------------------------- whose work is read


@modes
def test_another_conversation_and_another_person_read_nothing(reader, saved, mode):
    edit(saved)
    alice = person()
    reader.rows.append(saved.row(saved.capture(), session=reader.session(alice)))
    nothing = {"error": "Engineer has not run in this conversation, so there are no changes to read."}
    # The same person in another conversation, and another person who sends this conversation's id.
    assert reader.read(person(session="other-chat"), mode, agent_id="engineer") == nothing
    assert reader.read(person(user="bob"), mode, agent_id="engineer") == nothing


@modes
def test_reading_needs_the_permission_to_run_the_agent(reader, saved, mode):
    edit(saved)
    run_context = person(scopes=["agents:writer:run"])
    reader.rows.append(saved.row(saved.capture(), session=reader.session(run_context)))
    result = reader.read(run_context, mode, agent_id="engineer")
    assert result["error"].startswith("Cannot read the changes:") and "diff" not in result
    assert reader.db.asked == []


@modes
def test_refusals_are_one_sentence(reader, saved, mode):
    run_context = person(scopes=["agents:*:run"])
    assert reader.read(run_context, mode) == {"error": "Give a task_id or an agent_id, one of the two."}
    assert reader.read(run_context, mode, agent_id="engineer", task_id="t-1") == {
        "error": "Give a task_id or an agent_id, one of the two."
    }
    assert reader.read(run_context, mode, agent_id="writer") == {
        "error": "Writer does not work in a sandbox, so it has no checkout of its own to read."
    }
    assert reader.read(run_context, mode, agent_id="nobody")["error"].startswith("Agent not found: nobody")
    reader.rows.append(saved.row(saved.capture(), session=reader.session(run_context), commit="--output=/tmp/x"))
    assert reader.read(run_context, mode, agent_id="engineer") == {
        "error": "Run run-1 recorded no commit its sandbox started from, so there is nothing to compare its "
        "checkout with."
    }


# ----------------------------------------------------------------- a Task


class Tasks:
    """The Task reads the tool makes, standing in for the Company database and registry."""

    def __init__(self, reader, task):
        self.reader, self.value = reader, task

    def __call__(self, agent_os):
        return self

    async def task(self, task_id):
        from fastapi import HTTPException

        if task_id != self.value["id"]:
            raise HTTPException(404, "Task not found")
        return self.value

    def executor(self, value):
        return self.reader.engineer if value["executor_id"] == "engineer" else self.reader.writer

    def run_database(self, value):
        return self.reader.db


@pytest.fixture
def task_reader(monkeypatch, saved):
    from agno.os.routers.company import runs

    reader = Reader(monkeypatch, saved, company=object())
    task = {"id": "t-1", "executor_type": "agent", "executor_id": "engineer", "job_id": "run-1", "session_id": "task-s"}
    monkeypatch.setattr(runs, "_TaskStarter", Tasks(reader, task))
    reader.task = task
    return reader


def test_a_tasks_changes_are_read_from_its_own_session(task_reader, saved):
    edit(saved)
    # Whoever started the Task's run, a person who may read Tasks reads its changes.
    task_reader.rows.append(saved.row(saved.capture(), session="task-s", user="carol"))
    result = task_reader.read(person(scopes=["tasks:read"]), task_id="t-1")
    assert result["task_id"] == "t-1" and result["run_id"] == "run-1" and "+Reviewed." in result["diff"]
    assert task_reader.db.asked == ["task-s"]


def test_a_task_the_person_may_not_read_is_refused_before_anything_is_read(task_reader, saved):
    edit(saved)
    task_reader.rows.append(saved.row(saved.capture(), session="task-s"))
    result = task_reader.read(person(scopes=["agents:engineer:run"]), task_id="t-1")
    assert result["error"].startswith("Cannot read the changes:") and "diff" not in result
    assert task_reader.db.asked == []


def test_task_refusals(task_reader, saved):
    run_context = person()
    assert task_reader.read(run_context, task_id="missing") == {"error": "Cannot read the Task: Task not found"}
    task_reader.task.update(job_id=None)
    assert task_reader.read(run_context, task_id="t-1") == {
        "error": "This Task has not run yet, so its sandbox has saved no checkout."
    }
    task_reader.task.update(job_id="run-1", executor_id="writer")
    assert task_reader.read(run_context, task_id="t-1") == {
        "error": "Writer does not work in a sandbox, so it has no checkout of its own to read."
    }
    task_reader.task.update(executor_type="team", executor_id="crew")
    assert task_reader.read(run_context, task_id="t-1") == {
        "error": "This Task's executor is not an agent that works in a sandbox: no checkout to read."
    }
    task_reader.task.update(executor_type="agent", executor_id="engineer")
    assert task_reader.read(run_context, task_id="t-1") == {
        "error": "Engineer has not run for this Task, so there are no changes to read."
    }
    assert task_reader.read(run_context, "sync", task_id="t-1") == {
        "error": "Reading a Task's sandbox needs an asynchronous run."
    }
    task_reader.os._company_db = None
    assert task_reader.read(run_context, task_id="t-1") == {
        "error": "Company is not running here, so there is no Task to read."
    }


# ----------------------------------------------------------------- what the agent wrote is never run


@modes
def test_nothing_the_agent_configured_in_its_checkout_runs_on_the_host(reader, saved, mode, tmp_path):
    """A filter, a file-system monitor, a hook and an alternate object store set inside the sandbox are
    all in the saved checkout. Reading it runs none of them and follows none of them."""
    edit(saved)
    marker = tmp_path / "ran"
    (saved.checkout / ".gitattributes").write_text("* filter=mark diff=mark\n")
    with (saved.checkout / ".git" / "config").open("a") as config:
        config.write(
            f'[core]\n\tfsmonitor = "touch {marker}"\n\thooksPath = {saved.checkout}/hooks\n'
            f'[filter "mark"]\n\tclean = "touch {marker}; cat"\n\tsmudge = "touch {marker}; cat"\n'
            f'[diff "mark"]\n\ttextconv = "touch {marker}; cat"\n\tcommand = "touch {marker}"\n'
        )
    (saved.checkout / ".git" / "objects" / "info" / "alternates").write_text(str(tmp_path / "elsewhere") + "\n")
    run_context = person()
    reader.rows.append(saved.row(saved.capture(), session=reader.session(run_context)))
    result = reader.read(run_context, mode, agent_id="engineer")
    assert "+Reviewed." in result["diff"]
    assert not marker.exists()


# ----------------------------------------------------------------- when Super Agent has the tool


def manager_of(tmp_path, agents, registry):
    tmp_path.mkdir()
    db = SqliteDb(db_file=str(tmp_path / "os.db"))
    agent_os = AgentOS(
        id="sandbox-changes",
        db=db,
        agents=agents,
        registry=registry,
        manager=OSManager(model=ScriptedModel(), access_docs=False),
        telemetry=False,
    )
    tools = next(tool for tool in agent_os.manager.tools if isinstance(tool, BackgroundRunTools))
    return db, tools, agent_os.manager.instructions.base


def test_the_tool_exists_only_on_an_agentos_with_a_sandbox(tmp_path, saved):
    writer = Agent(id="writer", name="Writer", model=ScriptedModel())
    db, tools, instructions = manager_of(tmp_path / "plain", [writer], Registry(agents=[writer]))
    assert "read_sandbox_changes" not in tools.functions and "read_sandbox_changes" not in tools.async_functions
    assert SANDBOX_CHANGES_INSTRUCTIONS not in instructions
    db.close()
    engineer = ClaudeAgent(
        id="engineer", db=PostgresDb(db_url=URL), sandbox=GoneSandbox(saved.store), repository=REPOSITORY
    )
    db, tools, instructions = manager_of(tmp_path / "sandboxed", [writer, engineer], Registry(agents=[writer]))
    assert "read_sandbox_changes" in tools.functions and "read_sandbox_changes" in tools.async_functions
    assert SANDBOX_CHANGES_INSTRUCTIONS in instructions
    # The model is told the same about the tool in a synchronous run.
    described = tools.functions["read_sandbox_changes"].entrypoint.__doc__
    assert described == tools.async_functions["read_sandbox_changes"].entrypoint.__doc__
    assert "read_file does not read" in described
    db.close()
    # A sandbox the registry holds for stored agents counts too.
    db, tools, _ = manager_of(
        tmp_path / "registry", [writer], Registry(agents=[writer], sandboxes=[GoneSandbox(saved.store)])
    )
    assert "read_sandbox_changes" in tools.async_functions
    db.close()


def test_a_finished_work_report_may_read_the_changes():
    assert "read_sandbox_changes" in READ_TOOLS
    assert "never read_file" in SANDBOX_CHANGES_INSTRUCTIONS
