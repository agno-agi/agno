"""Keep what the company knows in one file tree, without a model call.

Super Agent and Mini Agent share one tree:

    wiki/                   agreed direction; a person confirms each change
    products/<product-id>/  brief.md (confirmed), status.md and what agents found
    tasks/<task-id>/        what one Task was given and what it produced
    notes/                  Super Agent's own notes

wiki/, products/ and tasks/ are stored in the Company database. notes/ is stored in
the AgentOS database and is shared by everyone who talks to Super Agent, including
when user isolation is on.

This script makes the tool calls Super Agent would make in a chat: it saves a company
page, writes a Product page, a note and a Task file, and then prints what a Task's
input loads. In a chat, save_company_page pauses until the person confirms the page
and the change; here the script is that person.

Prerequisites: Install agno, sqlalchemy, openai and fastapi.
Run: .venvs/demo/bin/python cookbook/05_agent_os/30_company/16_company_file_tree.py
Try: Change a page between the read and the save; the save must be refused.
"""

import asyncio
import json
from tempfile import TemporaryDirectory

from agno.company import CompanyManager
from agno.company.execution import _task_input
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS, CompanyConfig, OSManager
from agno.run import RunContext

if __name__ == "__main__":
    with TemporaryDirectory() as directory:
        db = SqliteDb(db_file=directory + "/company.db")
        model = OpenAIResponses(id="gpt-5.6-luna")
        agent_os = AgentOS(
            db=db,
            manager=OSManager(model=model, access_docs=False),
            company=CompanyConfig(model=model, name="Acme"),
            telemetry=False,
        )
        super_agent = agent_os.manager
        assert super_agent is not None
        files = next(
            tool
            for tool in super_agent.tools
            if getattr(tool, "name", None) == "company_files"
        )
        # Agreed direction is the person's to confirm; every other write does not pause.
        assert files.functions["save_company_page"].requires_confirmation
        assert not files.functions["write_company_file"].requires_confirmation

        manager = CompanyManager(db)
        product = manager.create(name="Documentation", purpose="Help developers")
        project = manager.create_project(product_id=product["id"], name="Release")
        task = manager.create_task(
            product_id=product["id"],
            project_id=project["id"],
            title="Draft release notes",
            brief="Summarize the reviewed changes.",
        )
        product_folder = "products/" + product["id"]
        task_folder = "tasks/" + task["id"]
        # Trusted application code supplies the context; identity is never a model argument.
        context = RunContext(run_id="demo", session_id="planning", user_id="alice")

        def call(tool: str, **arguments):
            function = getattr(files, tool)
            return json.loads(function(**arguments, _agno_run_context=context))

        # Chat step: "Our priority this quarter is the 3.2 release. Save that."
        # A new page is created at version 0, when there is something to put in it.
        call(
            "save_company_page",
            path="wiki/priorities.md",
            expected_version=0,
            new_text="# Priorities\n\n1. Ship the 3.2 release.",
        )
        # Chat step: "The docs are for Python developers. Put that in the Product brief."
        brief = call("read_company_file", path=product_folder + "/brief.md")
        call(
            "save_company_page",
            path=product_folder + "/brief.md",
            expected_version=brief["version"],
            new_text="The docs are written for Python developers.",
        )
        # A save names the version the person saw. A page that changed since is refused.
        try:
            call(
                "save_company_page",
                path=product_folder + "/brief.md",
                expected_version=brief["version"],
                new_text="A change against the old version.",
            )
        except ValueError as exc:
            assert "changed since the person saw it" in str(exc)
            print("Stale save refused")
        else:
            raise AssertionError("A stale save replaced the brief")
        # Agreed direction never changes through the plain write tool.
        try:
            call(
                "write_company_file",
                path="wiki/priorities.md",
                content="Replaced without the person",
                expected_version=1,
            )
        except PermissionError:
            print("Unconfirmed wiki write refused")
        else:
            raise AssertionError("The wiki changed without a confirmation")

        # What agents found about a Product goes under the Product. It is read on request.
        call(
            "write_company_file",
            path=product_folder + "/research.md",
            content="# Research\n\nThe install page has the most exits.\n",
            expected_version=0,
        )
        # What a Task is given, and what it produces, goes in the Task's folder.
        call(
            "write_company_file",
            path=task_folder + "/changes.md",
            content="- Sessions load faster\n- New file tree\n",
        )
        # Super Agent's own notes need no confirmation and no Company permission.
        call(
            "write_company_file",
            path="notes/follow-ups.md",
            content="Ask about the docs search next week.\n",
        )

        print("Top folders:", call("list_company_files")["folders"])
        print("Products:", call("list_company_files", folder="products")["folders"])
        for folder in ("wiki", product_folder, task_folder, "notes"):
            listed = call("list_company_files", folder=folder)["files"]
            print(folder + ":", [row["path"].split("/")[-1] for row in listed])
        found = call("search_company_files", query="install page")["matches"]
        assert [match["path"] for match in found] == [product_folder + "/research.md"]

        # A Task's input carries the Product's brief and status and the company wiki.
        # The queue builds it when the Task starts. Everything else is read on request.
        payload = json.loads(asyncio.run(_task_input(manager, db.get_task(task["id"]))))
        loaded = [page["file"] for page in payload["wiki"]]
        print("A Task's input loads:", loaded)
        assert loaded == [
            product_folder + "/brief.md",
            product_folder + "/status.md",
            "wiki/brief.md",
            "wiki/status.md",
            "wiki/priorities.md",
        ]
        text = json.dumps(payload)
        assert "Python developers" in text and "3.2 release" in text
        assert "most exits" not in text and "Sessions load faster" not in text
        assert "docs search" not in text

        call("delete_company_file", path="notes/follow-ups.md")
        assert call("list_company_files", folder="notes")["files"] == []
        db.close()
        print("Company file tree example passed")
        print("No model call was made")
