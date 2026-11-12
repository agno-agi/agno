"""Read routes over the Company file tree: a Task's files and the shared notes."""

import asyncio
import time
from contextlib import ExitStack

import jwt
import pytest
from fastapi.testclient import TestClient

from agno.company.files import LIST_ENTRIES, READ_CHARS, CompanyFiles
from agno.db.sqlite import AsyncSqliteDb, SqliteDb
from agno.os import AgentOS, CompanyConfig
from agno.os.config import AuthorizationConfig
from agno.os.scopes import get_default_scope_mappings, get_required_scopes_for_route

SECRET = "company-files-router-test-key-long-enough"
OS_ID = "company-files-test"
SCOPES = ["products:write", "projects:write", "tasks:read", "tasks:write", "tasks:delete", "wiki:read"]


def headers(user, scopes=None):
    claims = {"sub": user, "aud": OS_ID, "exp": int(time.time()) + 300, "scopes": SCOPES if scopes is None else scopes}
    return {"Authorization": "Bearer " + jwt.encode(claims, SECRET, algorithm="HS256")}


@pytest.fixture(params=[False, True], ids=["sync", "async"])
def make(request, tmp_path):
    """Build an AgentOS with Company on. Returns its client and the tree, which the test writes through."""
    with ExitStack() as stack:
        count = 0

        def build(isolation=None):
            nonlocal count
            count += 1
            db_file = str(tmp_path / f"{count}.db")
            db = (AsyncSqliteDb if request.param else SqliteDb)(db_file=db_file)
            stack.callback((lambda: asyncio.run(db.close())) if request.param else db.close)
            # The tests write through a synchronous database on the same file.
            writer = SqliteDb(db_file=db_file)
            stack.callback(writer.close)
            authorization = {}
            if isolation is not None:
                authorization = {
                    "authorization": True,
                    "authorization_config": AuthorizationConfig(
                        verification_keys=[SECRET], algorithm="HS256", user_isolation=isolation
                    ),
                }
            agent_os = AgentOS(id=OS_ID, db=db, company=CompanyConfig(), telemetry=False, **authorization)
            client = stack.enter_context(TestClient(agent_os.get_app()))
            return client, CompanyFiles(writer, notes_db=writer)

        yield build


def new_task(client, auth=None):
    product = client.post("/company/products", json={"name": "SDK"}, headers=auth).json()
    project = client.post("/company/projects", json={"product_id": product["id"], "name": "Release"}, headers=auth)
    body = {"title": "Report", "product_id": product["id"], "project_id": project.json()["id"]}
    response = client.post("/company/tasks", json=body, headers=auth)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_list_and_read_a_tasks_files(make):
    client, files = make()
    task_id, other = new_task(client), new_task(client)
    written = files.write(f"tasks/{task_id}/report.md", "What the Task found.\n")
    files.write(f"tasks/{task_id}/data/rows.csv", "a,b\n")
    files.write(f"tasks/{other}/report.md", "The other Task.\n")
    url = f"/company/tasks/{task_id}/files"

    listing = client.get(url)
    assert listing.status_code == 200, listing.text
    # Paths are inside the Task's folder, and each one is the path the read route takes.
    assert [row["path"] for row in listing.json()["data"]] == ["data/rows.csv", "report.md"]
    assert listing.json()["meta"]["total_count"] == 2

    page = client.get(url + "/report.md")
    assert page.status_code == 200, page.text
    assert page.json() == {
        "content": "What the Task found.\n",
        "metadata": {
            "path": "report.md",
            "size_bytes": written["size_bytes"],
            "version": 1,
            "updated_at": page.json()["metadata"]["updated_at"],
            "user_id": None,
        },
        "next_offset": None,
    }
    assert client.get(url + "/data/rows.csv").json()["content"] == "a,b\n"
    assert client.get(f"/company/tasks/{other}/files/report.md").json()["content"] == "The other Task.\n"

    # A Task with no files lists none.
    empty = new_task(client)
    assert client.get(f"/company/tasks/{empty}/files").json()["data"] == []
    assert client.get(f"/company/tasks/{empty}/files").json()["meta"]["total_count"] == 0


def test_list_and_read_the_notes(make):
    client, files = make()
    task_id = new_task(client)
    files.write("notes/ideas.md", "An idea.\n")
    files.write("notes/people/alice.md", "Alice leads the SDK.\n")
    files.write(f"tasks/{task_id}/report.md", "Not a note.\n")

    listing = client.get("/company/notes")
    assert listing.status_code == 200, listing.text
    assert [row["path"] for row in listing.json()["data"]] == ["ideas.md", "people/alice.md"]
    page = client.get("/company/notes/people/alice.md")
    assert page.status_code == 200, page.text
    assert page.json()["content"] == "Alice leads the SDK.\n"
    assert page.json()["metadata"]["path"] == "people/alice.md"
    # The wiki routes do not serve the notes.
    assert "ideas.md" not in {row["path"] for row in client.get("/company/wiki").json()["data"]}


def test_a_missing_task_is_the_task_routes_404(make):
    client, files = make()
    task_id = new_task(client)
    files.write(f"tasks/{task_id}/report.md", "Kept.\n")
    missing = client.get("/company/tasks/no-such-task")
    assert missing.status_code == 404
    for url in ["/company/tasks/no-such-task/files", "/company/tasks/no-such-task/files/report.md"]:
        response = client.get(url)
        assert (response.status_code, response.json()) == (404, missing.json())

    # An archived Task is not found on the Task route, and neither are its files.
    assert client.delete(f"/company/tasks/{task_id}").status_code == 204
    assert client.get(f"/company/tasks/{task_id}").status_code == 404
    for url in [f"/company/tasks/{task_id}/files", f"/company/tasks/{task_id}/files/report.md"]:
        response = client.get(url)
        assert (response.status_code, response.json()) == (404, missing.json())
    assert client.post(f"/company/tasks/{task_id}/restore").status_code == 200
    assert client.get(f"/company/tasks/{task_id}/files/report.md").json()["content"] == "Kept.\n"


def test_a_missing_file_is_404(make):
    client, files = make()
    task_id = new_task(client)
    files.write(f"tasks/{task_id}/data/rows.csv", "a,b\n")
    files.write("notes/ideas.md", "An idea.\n")
    for url in [
        f"/company/tasks/{task_id}/files/missing.md",
        # A folder is not a file.
        f"/company/tasks/{task_id}/files/data",
        "/company/notes/missing.md",
        # A file of the same name in another folder of the tree is not served.
        f"/company/tasks/{task_id}/files/ideas.md",
        "/company/notes/data/rows.csv",
    ]:
        response = client.get(url)
        assert (response.status_code, response.json()) == (404, {"detail": "File not found"}), url


def test_a_long_file_is_read_in_parts(make):
    client, files = make()
    task_id = new_task(client)
    content = "".join(str(index % 10) for index in range(READ_CHARS + 25))
    files.write(f"tasks/{task_id}/long.txt", content)
    files.write("notes/long.txt", content)
    for url in [f"/company/tasks/{task_id}/files/long.txt", "/company/notes/long.txt"]:
        first = client.get(url).json()
        assert first["next_offset"] == READ_CHARS
        rest = client.get(url, params={"offset": first["next_offset"]}).json()
        assert rest["next_offset"] is None
        assert first["content"] + rest["content"] == content
        assert client.get(url, params={"offset": -1}).status_code == 422


@pytest.mark.parametrize("folder", ["task", "notes"])
def test_a_folder_with_more_than_one_page_of_files(make, folder):
    client, files = make()
    task_id = new_task(client)
    tree_folder, url = (
        (f"tasks/{task_id}", f"/company/tasks/{task_id}/files")
        if folder == "task"
        else (
            "notes",
            "/company/notes",
        )
    )
    # More files than the tree lists in one of its own pages.
    count = LIST_ENTRIES + 5
    names = [f"{index:04d}.md" for index in range(count)]
    for name in names:
        files.write(f"{tree_folder}/{name}", name)
    files.write("notes/elsewhere.md" if folder == "task" else f"tasks/{task_id}/elsewhere.md", "Another folder.\n")

    def page(limit, number):
        response = client.get(url, params={"limit": limit, "page": number})
        assert response.status_code == 200, response.text
        assert response.json()["meta"]["total_count"] == count
        assert response.json()["meta"]["total_pages"] == (count + limit - 1) // limit
        return [row["path"] for row in response.json()["data"]]

    assert page(20, 1) == names[:20]
    assert page(20, 2) == names[20:40]
    # A page that starts in one page of the tree and ends in the next.
    assert page(150, 2) == names[150:]
    assert page(LIST_ENTRIES, 2) == names[LIST_ENTRIES:]
    assert page(1000, 1) == names
    # Every file is listed once across the pages, and a page past the end is empty.
    assert [name for number in range(1, 5) for name in page(60, number)] == names
    assert page(60, 5) == []
    for params in [{"limit": 0}, {"limit": 1001}, {"page": 0}]:
        assert client.get(url, params=params).status_code == 422


def test_a_page_past_the_end_is_empty_with_the_right_totals(make):
    client, files = make()
    task_id = new_task(client)
    for name in ["a.md", "b.md", "c.md"]:
        files.write(f"tasks/{task_id}/{name}", name)
        files.write(f"notes/{name}", name)
    for url in [f"/company/tasks/{task_id}/files", "/company/notes"]:
        for limit, page, total_pages in [(20, 50, 1), (2, 3, 2), (1, 4, 3), (1000, 10**9, 1)]:
            response = client.get(url, params={"limit": limit, "page": page})
            assert response.status_code == 200, (url, limit, page, response.text)
            assert response.json()["data"] == []
            meta = response.json()["meta"]
            assert (meta["page"], meta["limit"]) == (page, limit)
            assert (meta["total_count"], meta["total_pages"]) == (3, total_pages)
        # The last page that holds files is not empty.
        assert [row["path"] for row in client.get(url, params={"limit": 2, "page": 2}).json()["data"]] == ["c.md"]
    # An empty folder has no pages, and any page of it is empty.
    empty = new_task(client)
    response = client.get(f"/company/tasks/{empty}/files", params={"page": 50})
    assert response.status_code == 200, response.text
    assert response.json()["data"] == []
    assert (response.json()["meta"]["total_count"], response.json()["meta"]["total_pages"]) == (0, 0)


def test_a_caller_without_the_scope_is_refused(make):
    client, files = make(isolation=False)
    task_id = new_task(client, headers("alice"))
    files.write(f"tasks/{task_id}/report.md", "What the Task found.\n")
    files.write("notes/ideas.md", "An idea.\n")
    task_urls = [f"/company/tasks/{task_id}/files", f"/company/tasks/{task_id}/files/report.md"]
    note_urls = ["/company/notes", "/company/notes/ideas.md"]

    for url in [*task_urls, *note_urls]:
        assert client.get(url).status_code == 401, url
        assert client.get(url, headers=headers("bob", [])).status_code == 403, url
    for url in task_urls:
        assert client.get(url, headers=headers("bob", ["wiki:read", "tasks:write"])).status_code == 403, url
        assert client.get(url, headers=headers("bob", ["tasks:read"])).status_code == 200, url
    for url in note_urls:
        assert client.get(url, headers=headers("bob", ["tasks:read", "wiki:write"])).status_code == 403, url
        assert client.get(url, headers=headers("bob", ["wiki:read"])).status_code == 200, url
    # The scope is checked before the Task is looked up.
    assert client.get("/company/tasks/no-such-task/files", headers=headers("bob", ["wiki:read"])).status_code == 403


@pytest.mark.parametrize("isolation", [False, True])
def test_user_isolation_does_not_narrow_the_tree(make, isolation):
    client, files = make(isolation=isolation)
    task_id = new_task(client, headers("alice"))
    files.write(f"tasks/{task_id}/report.md", "What the Task found.\n")
    files.write("notes/ideas.md", "An idea.\n")
    # The Task route serves another person's Task, and so do its files. The notes are one shared folder.
    assert client.get(f"/company/tasks/{task_id}", headers=headers("bob")).status_code == 200
    for user in ["alice", "bob"]:
        listing = client.get(f"/company/tasks/{task_id}/files", headers=headers(user))
        assert [row["path"] for row in listing.json()["data"]] == ["report.md"]
        page = client.get(f"/company/tasks/{task_id}/files/report.md", headers=headers(user))
        assert page.json()["content"] == "What the Task found.\n"
        assert [row["path"] for row in client.get("/company/notes", headers=headers(user)).json()["data"]] == [
            "ideas.md"
        ]
        assert client.get("/company/notes/ideas.md", headers=headers(user)).json()["content"] == "An idea.\n"


def test_isolation_refuses_a_caller_with_no_identity(make):
    client, files = make(isolation=True)
    task_id = new_task(client, headers("alice"))
    files.write(f"tasks/{task_id}/report.md", "What the Task found.\n")
    refused = client.get(f"/company/tasks/{task_id}", headers=headers(""))
    assert refused.status_code == 403
    for url in [
        f"/company/tasks/{task_id}/files",
        f"/company/tasks/{task_id}/files/report.md",
        "/company/notes",
        "/company/notes/ideas.md",
    ]:
        response = client.get(url, headers=headers(""))
        assert (response.status_code, response.json()) == (403, refused.json()), url


def test_the_security_key_guards_the_file_routes(tmp_path):
    from agno.os.settings import AgnoAPISettings

    db = SqliteDb(db_file=str(tmp_path / "key.db"))
    agent_os = AgentOS(db=db, company=CompanyConfig(), settings=AgnoAPISettings(os_security_key="key"), telemetry=False)
    with TestClient(agent_os.get_app()) as client:
        key = {"Authorization": "Bearer key"}
        task_id = new_task(client, key)
        files = CompanyFiles(db, notes_db=db)
        files.write(f"tasks/{task_id}/report.md", "What the Task found.\n")
        files.write("notes/ideas.md", "An idea.\n")
        for url in [
            f"/company/tasks/{task_id}/files",
            f"/company/tasks/{task_id}/files/report.md",
            "/company/notes",
            "/company/notes/ideas.md",
        ]:
            assert client.get(url).status_code == 401, url
            assert client.get(url, headers={"Authorization": "Bearer wrong"}).status_code == 401, url
            assert client.get(url, headers=key).status_code == 200, url

    # Each route checks the key itself, with no AgentOS middleware in front of it.
    from fastapi import FastAPI

    from agno.os.routers.company.files import get_company_files_router

    bare = FastAPI()
    bare.include_router(get_company_files_router(agent_os))
    with TestClient(bare) as client:
        for url in [
            f"/company/tasks/{task_id}/files",
            f"/company/tasks/{task_id}/files/report.md",
            "/company/notes",
            "/company/notes/ideas.md",
        ]:
            assert client.get(url).status_code in (401, 403), url
            assert client.get(url, headers={"Authorization": "Bearer wrong"}).status_code == 401, url
            assert client.get(url, headers=key).status_code == 200, url
    db.close()


@pytest.mark.parametrize(
    "path",
    [
        # Each one is sent undecoded, so the client does not resolve it first.
        "%2e%2e/{other}/secret.md",
        "%2e%2e/%2e%2e/notes/secret.md",
        "%2e%2e/%2e%2e/wiki/brief.md",
        "sub/%2e%2e/%2e%2e/{other}/secret.md",
        "%2e/secret.md",
        "..%2f{other}%2fsecret.md",
        "..%5c{other}%5csecret.md",
        "%2f%2e%2e%2f{other}%2fsecret.md",
        "%00secret.md",
    ],
)
def test_a_path_cannot_leave_its_folder(make, path):
    client, files = make()
    task_id, other = new_task(client), new_task(client)
    files.write(f"tasks/{other}/secret.md", "Another Task's file.\n")
    files.write("notes/secret.md", "A note.\n")
    files.write(f"tasks/{task_id}/own.md", "This Task's file.\n")
    path = path.format(other=other)
    for url in [f"/company/tasks/{task_id}/files/{path}", f"/company/notes/{path}"]:
        response = client.get(url)
        assert response.status_code == 422, (url, response.status_code, response.text)
        assert "content" not in response.json()


def test_a_trailing_slash_is_dropped_before_the_route(make):
    client, files = make()
    task_id = new_task(client)
    files.write(f"tasks/{task_id}/own.md", "This Task's file.\n")
    files.write("notes/own.md", "Own note.\n")
    # AgentOS drops a trailing slash from every request path, so these are the same requests without it.
    for url in [f"/company/tasks/{task_id}/files", "/company/notes"]:
        assert client.get(url + "/").json() == client.get(url).json()
        assert client.get(url + "/own.md/").json() == client.get(url + "/own.md").json()
        assert client.get(url + "/own.md%2f").json() == client.get(url + "/own.md").json()


def test_a_path_that_names_another_folder_stays_inside_its_own(make):
    client, files = make()
    task_id, other = new_task(client), new_task(client)
    files.write(f"tasks/{other}/secret.md", "Another Task's file.\n")
    files.write("notes/secret.md", "A note.\n")
    files.write("notes/own.md", "Own note.\n")
    # The names of other folders are ordinary folder names inside this one.
    for path in [f"tasks/{other}/secret.md", f"company/tasks/{other}/secret.md", "notes/secret.md", "wiki/brief.md"]:
        response = client.get(f"/company/tasks/{task_id}/files/{path}")
        assert (response.status_code, response.json()) == (404, {"detail": "File not found"}), path
    for path in [f"tasks/{other}/secret.md", "company/wiki/brief.md", "wiki/brief.md", "notes/own.md"]:
        response = client.get(f"/company/notes/{path}")
        assert (response.status_code, response.json()) == (404, {"detail": "File not found"}), path
    # A Task ID is one path segment, so another Task's folder is not reachable through it.
    assert client.get(f"/company/tasks/{task_id}%2f..%2f{other}/files/secret.md").status_code == 404
    assert client.get(f"/company/tasks/{other}/files/secret.md").json()["content"] == "Another Task's file.\n"


def matched_row(method, path):
    """The row of the scope table the real matcher picks for a request."""
    rows = {pattern: [pattern] for pattern in get_default_scope_mappings(company=True)}
    return get_required_scopes_for_route(rows, method, path)


@pytest.mark.parametrize(
    "path,row,scopes",
    [
        ("/company/tasks/t1/files", "GET /company/tasks/*/files", ["tasks:read"]),
        ("/company/tasks/t1/files/report.md", "GET /company/tasks/*/files/*", ["tasks:read"]),
        ("/company/tasks/t1/files/data/rows.csv", "GET /company/tasks/*/files/*", ["tasks:read"]),
        ("/company/notes", "GET /company/notes", ["wiki:read"]),
        ("/company/notes/ideas.md", "GET /company/notes/*", ["wiki:read"]),
        ("/company/notes/people/alice.md", "GET /company/notes/*", ["wiki:read"]),
        # A file path that looks like another route keeps its own row.
        ("/company/tasks/t1/files/wiki/brief.md", "GET /company/tasks/*/files/*", ["tasks:read"]),
        ("/company/tasks/t1/files/../../notes/ideas.md", "GET /company/tasks/*/files/*", ["tasks:read"]),
        ("/company/notes/tasks/t1/files/report.md", "GET /company/notes/*", ["wiki:read"]),
        ("/company/notes/../tasks/t1/files/report.md", "GET /company/notes/*", ["wiki:read"]),
        # The rows beside the new ones still match their own routes.
        ("/company/tasks", "GET /company/tasks", ["tasks:read"]),
        ("/company/tasks/t1", "GET /company/tasks/*", ["tasks:read"]),
        ("/company/tasks/t1/runs", "GET /company/tasks/*", ["tasks:read"]),
        ("/company/wiki", "GET /company/wiki", ["wiki:read"]),
        ("/company/wiki/notes/ideas.md", "GET /company/wiki/*", ["wiki:read"]),
        ("/company/products/p1/wiki/files/report.md", "GET /company/products/*/wiki/*", ["wiki:read"]),
    ],
)
def test_each_route_matches_its_own_scope_row(path, row, scopes):
    assert matched_row("GET", path) == [row]
    assert get_required_scopes_for_route(get_default_scope_mappings(company=True), "GET", path) == scopes


def test_the_file_routes_are_read_only(make):
    client, files = make()
    task_id = new_task(client)
    files.write(f"tasks/{task_id}/report.md", "Kept.\n")
    files.write("notes/ideas.md", "Kept.\n")
    for url in [f"/company/tasks/{task_id}/files/report.md", "/company/notes/ideas.md"]:
        for method in ["put", "post", "patch", "delete"]:
            response = getattr(client, method)(url)
            assert response.status_code in (404, 405), (method, url, response.status_code)
        assert client.get(url).json()["content"] == "Kept.\n"
    operations = client.get("/openapi.json").json()["paths"]
    for route in [
        "/company/tasks/{task_id}/files",
        "/company/tasks/{task_id}/files/{path}",
        "/company/notes",
        "/company/notes/{path}",
    ]:
        assert set(operations[route]) == {"get"}, route


@pytest.mark.parametrize("os_async,company_async", [(False, True), (True, False)])
def test_notes_come_from_the_agentos_database(tmp_path, os_async, company_async):
    primary_file, company_file = str(tmp_path / "primary.db"), str(tmp_path / "company.db")
    primary = (AsyncSqliteDb if os_async else SqliteDb)(db_file=primary_file)
    company = (AsyncSqliteDb if company_async else SqliteDb)(db_file=company_file)
    primary_writer, company_writer = SqliteDb(db_file=primary_file), SqliteDb(db_file=company_file)
    files = CompanyFiles(company_writer, notes_db=primary_writer)
    agent_os = AgentOS(db=primary, company=CompanyConfig(db=company), telemetry=False)
    with TestClient(agent_os.get_app()) as client:
        task_id = new_task(client)
        files.write(f"tasks/{task_id}/report.md", "In the Company database.\n")
        files.write("notes/ideas.md", "In the AgentOS database.\n")
        # A note of the same path in the Company database is not the shared notes.
        CompanyFiles(primary_writer, notes_db=company_writer).write("notes/stray.md", "Not served.\n")
        assert [row["path"] for row in client.get("/company/notes").json()["data"]] == ["ideas.md"]
        assert client.get("/company/notes/ideas.md").json()["content"] == "In the AgentOS database.\n"
        assert client.get("/company/notes/stray.md").status_code == 404
        assert client.get(f"/company/tasks/{task_id}/files/report.md").json()["content"] == "In the Company database.\n"
    for db, is_async in [(primary, os_async), (company, company_async)]:
        asyncio.run(db.close()) if is_async else db.close()
    primary_writer.close()
    company_writer.close()


def test_file_routes_without_a_supported_database_report_unavailable():
    from agno.db.in_memory import InMemoryDb

    with TestClient(AgentOS(company=CompanyConfig(), telemetry=False).get_app()) as client:
        for url in ["/company/tasks/t1/files", "/company/tasks/t1/files/a.md", "/company/notes", "/company/notes/a.md"]:
            assert client.get(url).status_code == 503, url
    with TestClient(AgentOS(db=InMemoryDb(), company=CompanyConfig(), telemetry=False).get_app()) as client:
        for url in ["/company/tasks/t1/files", "/company/notes", "/company/notes/a.md"]:
            assert client.get(url).status_code == 503, url
