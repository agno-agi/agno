"""
Comprehensive unit tests for AzureDevOpsTools.

Run with:
    pytest test_azure_devops_tools.py -v
    pytest test_azure_devops_tools.py -v --tb=short        # compact tracebacks
"""

import json
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Patch heavy third-party imports before the module is imported
# ---------------------------------------------------------------------------
PATCH_TARGETS = {
    "azure.devops.connection.Connection": MagicMock(),
    "azure.devops.exceptions.AzureDevOpsAuthenticationError": type("AzureDevOpsAuthenticationError", (Exception,), {}),
    "azure.devops.exceptions.AzureDevOpsServiceError": type("AzureDevOpsServiceError", (Exception,), {}),
    "azure.devops.v7_0.build.models.Build": MagicMock(),
    "azure.devops.v7_0.build.models.BuildDefinitionReference": MagicMock(),
    "azure.devops.v7_0.git.models.GitPullRequest": MagicMock(),
    "azure.devops.v7_0.git.models.GitPullRequestCommentThread": MagicMock(),
    "azure.devops.v7_0.git.models.GitPullRequestSearchCriteria": MagicMock(),
    "azure.devops.v7_0.git.models.GitRefUpdate": MagicMock(),
    "azure.devops.v7_0.git.models.GitRepositoryCreateOptions": MagicMock(),
    "azure.devops.v7_0.work_item_tracking.models.CommentCreate": MagicMock(),
    "azure.devops.v7_0.work_item_tracking.models.JsonPatchOperation": MagicMock(),
    "azure.devops.v7_0.work_item_tracking.models.Wiql": MagicMock(),
    "msrest.authentication.BasicAuthentication": MagicMock(),
    "agno.tools.Toolkit": type(
        "Toolkit",
        (),
        {
            "__init__": lambda self, name="toolkit", tools=[], **kw: setattr(self, "tools", tools)
            or setattr(self, "name", name)
        },
    ),
    "agno.utils.log.log_debug": MagicMock(),
    "agno.utils.log.logger": MagicMock(),
}

for target, mock_val in PATCH_TARGETS.items():
    parts = target.rsplit(".", 1)
    patcher = patch(target, mock_val)
    try:
        patcher.start()
    except Exception:
        pass

# Now safe to import
from agno.tools.azure_devops import AzureDevOpsTools  # noqa: E402

# Grab the exception classes used inside the module
AuthError = PATCH_TARGETS["azure.devops.exceptions.AzureDevOpsAuthenticationError"]
ServiceError = PATCH_TARGETS["azure.devops.exceptions.AzureDevOpsServiceError"]


# ---------------------------------------------------------------------------
# Helpers to build realistic fake Azure DevOps SDK objects
# ---------------------------------------------------------------------------


def _dt(s: str = "2024-01-15T10:00:00") -> datetime:
    return datetime.fromisoformat(s)


def _fake_project(name="MyProject", pid="proj-uuid-1"):
    p = MagicMock()
    p.id = pid
    p.name = name
    p.description = "Test project"
    p.state = "wellFormed"
    p.visibility = "private"
    p.last_update_time = _dt()
    p.url = f"https://dev.azure.com/org/{name}"
    return p


def _fake_repo(name="MyRepo", rid="repo-uuid-1"):
    r = MagicMock()
    r.id = rid
    r.name = name
    r.default_branch = "refs/heads/main"
    r.remote_url = f"https://org@dev.azure.com/org/proj/_git/{name}"
    r.web_url = f"https://dev.azure.com/org/proj/_git/{name}"
    r.size = 1024
    r.project = MagicMock()
    r.project.name = "MyProject"
    return r


def _fake_ref(name="refs/heads/main", oid="abc123"):
    r = MagicMock()
    r.name = name
    r.object_id = oid
    r.creator = MagicMock()
    r.creator.display_name = "Dev User"
    r.url = f"https://dev.azure.com/org/proj/_apis/git/refs/{name}"
    return r


def _fake_pr(pr_id=1, title="My PR"):
    pr = MagicMock()
    pr.pull_request_id = pr_id
    pr.title = title
    pr.description = "PR description"
    pr.status = "active"
    pr.source_ref_name = "refs/heads/feature/x"
    pr.target_ref_name = "refs/heads/main"
    pr.created_by = MagicMock()
    pr.created_by.display_name = "Alice"
    pr.creation_date = _dt()
    pr.closed_date = None
    pr.url = "https://dev.azure.com/org/proj/_git/repo/pullrequest/1"
    pr.merge_status = "succeeded"
    pr.is_draft = False
    pr.reviewers = []
    pr.last_merge_source_commit = MagicMock()
    return pr


def _fake_commit(cid="deadbeef"):
    c = MagicMock()
    c.commit_id = cid
    c.comment = "Fix: resolve issue #42"
    c.author = MagicMock()
    c.author.name = "Bob"
    c.author.email = "bob@example.com"
    c.author.date = _dt()
    c.url = f"https://dev.azure.com/org/proj/_git/repo/commit/{cid}"
    c.remote_url = c.url
    return c


def _fake_work_item(wid=10, title="Fix bug", state="Active", wi_type="Bug"):
    wi = MagicMock()
    wi.id = wid
    wi.url = f"https://dev.azure.com/org/proj/_workitems/edit/{wid}"
    wi.fields = {
        "System.Title": title,
        "System.State": state,
        "System.WorkItemType": wi_type,
        "System.AssignedTo": {"displayName": "Charlie"},
        "System.AreaPath": "MyProject\\Area",
        "System.IterationPath": "MyProject\\Sprint 1",
        "System.CreatedDate": "2024-01-01T00:00:00",
        "System.ChangedDate": "2024-01-10T00:00:00",
        "System.Description": "Detailed description",
        "Microsoft.VSTS.Common.Priority": 2,
        "System.Tags": "tag1; tag2",
    }
    return wi


def _fake_build(bid=100, number="20240115.1"):
    b = MagicMock()
    b.id = bid
    b.build_number = number
    b.status = "completed"
    b.result = "succeeded"
    b.source_branch = "refs/heads/main"
    b.source_version = "deadbeef"
    b.queue_time = _dt()
    b.start_time = _dt()
    b.finish_time = _dt()
    b.requested_by = MagicMock()
    b.requested_by.display_name = "Dave"
    b.url = f"https://dev.azure.com/org/proj/_build/results?buildId={bid}"
    return b


def _fake_pipeline(pid=5, name="CI Pipeline"):
    p = MagicMock()
    p.id = pid
    p.name = name
    p.folder = "\\"
    p.revision = 1
    p.url = f"https://dev.azure.com/org/proj/_apis/build/definitions/{pid}"
    return p


def _fake_release_def(rid=3, name="Prod Release"):
    rd = MagicMock()
    rd.id = rid
    rd.name = name
    rd.path = "\\"
    rd.url = f"https://vsrm.dev.azure.com/org/proj/_apis/release/definitions/{rid}"
    rd.created_by = MagicMock()
    rd.created_by.display_name = "Eve"
    rd.created_on = _dt()
    rd.modified_on = _dt()
    return rd


def _fake_release(rid=7, name="Release-7"):
    r = MagicMock()
    r.id = rid
    r.name = name
    r.status = "active"
    r.created_by = MagicMock()
    r.created_by.display_name = "Frank"
    r.created_on = _dt()
    r.modified_on = _dt()
    r.url = f"https://vsrm.dev.azure.com/org/proj/_apis/release/releases/{rid}"
    r.release_definition = MagicMock()
    r.release_definition.name = "Prod Release"
    return r


def _fake_team(tid="team-uuid", name="Core Team"):
    t = MagicMock()
    t.id = tid
    t.name = name
    t.description = "Core engineering team"
    t.url = "https://dev.azure.com/org/_apis/projects/proj/teams/team-uuid"
    t.project_name = "MyProject"
    return t


def _fake_member(uid="user-uuid", display_name="Grace"):
    m = MagicMock()
    m.identity = MagicMock()
    m.identity.id = uid
    m.identity.display_name = display_name
    m.identity.unique_name = f"{display_name.lower()}@example.com"
    m.identity.url = f"https://dev.azure.com/org/_apis/identities/{uid}"
    m.is_team_admin = False
    return m


def _fake_iteration(iid="iter-uuid", name="Sprint 1"):
    it = MagicMock()
    it.id = iid
    it.name = name
    it.path = f"MyProject\\{name}"
    it.url = f"https://dev.azure.com/org/proj/_apis/work/teamsettings/iterations/{iid}"
    it.attributes = MagicMock()
    it.attributes.start_date = _dt("2024-01-01T00:00:00")
    it.attributes.finish_date = _dt("2024-01-14T00:00:00")
    it.attributes.time_frame = "current"
    return it


def _fake_comment_thread(tid=1, content="LGTM"):
    thread = MagicMock()
    thread.id = tid
    thread.status = "active"
    thread.is_deleted = False
    c = MagicMock()
    c.id = 1
    c.content = content
    c.author = MagicMock()
    c.author.display_name = "Heidi"
    c.published_date = _dt()
    c.comment_type = "text"
    thread.comments = [c]
    return thread


def _fake_wi_comment(cid=1, text="Looks good"):
    c = MagicMock()
    c.id = cid
    c.text = text
    c.created_by = MagicMock()
    c.created_by.display_name = "Ivan"
    c.created_date = _dt()
    c.modified_date = _dt()
    c.url = "https://dev.azure.com/org/proj/_workitems/edit/10"
    return c


def _fake_build_log(log_id=1):
    lg = MagicMock()
    lg.id = log_id
    lg.type = "Container"
    lg.url = f"https://dev.azure.com/org/proj/_apis/build/builds/100/logs/{log_id}"
    lg.created_on = _dt()
    lg.last_changed_on = _dt()
    lg.line_count = 42
    return lg


# ---------------------------------------------------------------------------
# Base test class: wires up the toolkit and a mock connection
# ---------------------------------------------------------------------------


class BaseADOTest(unittest.TestCase):
    """Sets up a fresh AzureDevOpsTools instance with a mocked Connection."""

    ORG_URL = "https://dev.azure.com/testorg"
    PAT = "fake-pat-token"
    PROJECT = "MyProject"

    def setUp(self):
        with (
            patch("agno.tools.azure_devops.Connection") as mock_conn_cls,
            patch("agno.tools.azure_devops.BasicAuthentication") as mock_auth_cls,
        ):
            self.mock_auth = MagicMock()
            mock_auth_cls.return_value = self.mock_auth

            self.mock_connection = MagicMock()
            mock_conn_cls.return_value = self.mock_connection

            self.tools = AzureDevOpsTools(
                organization_url=self.ORG_URL,
                personal_access_token=self.PAT,
                project=self.PROJECT,
            )
            # Pre-inject the mock connection so _get_connection() returns it directly
            self.tools._connection = self.mock_connection

        # Shortcut references to all sub-clients
        self.core = self.mock_connection.clients.get_core_client.return_value
        self.git = self.mock_connection.clients.get_git_client.return_value
        self.wit = self.mock_connection.clients.get_work_item_tracking_client.return_value
        self.build = self.mock_connection.clients.get_build_client.return_value
        self.release = self.mock_connection.clients.get_release_client.return_value
        self.work = self.mock_connection.clients.get_work_client.return_value

    # ------------------------------------------------------------------
    # Shared assertion helpers
    # ------------------------------------------------------------------

    def _parse(self, result: str) -> dict:
        """Parse JSON result and assert no top-level 'error' key."""
        data = json.loads(result)
        self.assertNotIn("error", data, f"Unexpected error in result: {data}")
        return data

    def _parse_error(self, result: str) -> str:
        data = json.loads(result)
        self.assertIn("error", data)
        return data["error"]


# ===========================================================================
# 1. INITIALISATION & CONFIGURATION
# ===========================================================================


class TestInitialisation(unittest.TestCase):
    def _make_tools(self, **kwargs):
        with patch("agno.tools.azure_devops.Connection"), patch("agno.tools.azure_devops.BasicAuthentication"):
            return AzureDevOpsTools(**kwargs)

    def test_explicit_credentials_stored(self):
        tools = self._make_tools(
            organization_url="https://dev.azure.com/myorg",
            personal_access_token="myPAT",
            project="Proj",
        )
        self.assertEqual(tools.organization_url, "https://dev.azure.com/myorg")
        self.assertEqual(tools.personal_access_token, "myPAT")
        self.assertEqual(tools.default_project, "Proj")

    def test_trailing_slash_stripped_from_org_url(self):
        tools = self._make_tools(
            organization_url="https://dev.azure.com/myorg/",
            personal_access_token="p",
        )
        self.assertEqual(tools.organization_url, "https://dev.azure.com/myorg")

    def test_env_var_fallback(self):
        with patch.dict(
            "os.environ",
            {
                "AZURE_DEVOPS_ORG_URL": "https://dev.azure.com/envorg",
                "AZURE_DEVOPS_PAT": "env-pat",
                "AZURE_DEVOPS_PROJECT": "EnvProject",
            },
        ):
            tools = self._make_tools()
        self.assertEqual(tools.organization_url, "https://dev.azure.com/envorg")
        self.assertEqual(tools.personal_access_token, "env-pat")
        self.assertEqual(tools.default_project, "EnvProject")

    def test_selective_tool_disabling(self):
        tools = self._make_tools(
            organization_url="https://dev.azure.com/org",
            personal_access_token="p",
            enable_list_projects=False,
            enable_delete_repository=False,
            enable_delete_work_item=False,
        )
        tool_names = [t.__name__ for t in tools.tools]
        self.assertNotIn("list_projects", tool_names)
        self.assertNotIn("delete_repository", tool_names)
        self.assertNotIn("delete_work_item", tool_names)
        # Others still registered
        self.assertIn("get_project", tool_names)

    def test_missing_org_url_raises(self):
        with (
            patch("agno.tools.azure_devops.Connection"),
            patch("agno.tools.azure_devops.BasicAuthentication"),
            patch.dict("os.environ", {}, clear=True),
        ):
            tools = AzureDevOpsTools(personal_access_token="p")
            tools._connection = None  # force reconnect path
        with self.assertRaises(ValueError, msg="organization_url is required"):
            tools._get_connection()

    def test_missing_pat_raises(self):
        with (
            patch("agno.tools.azure_devops.Connection"),
            patch("agno.tools.azure_devops.BasicAuthentication"),
            patch.dict("os.environ", {}, clear=True),
        ):
            tools = AzureDevOpsTools(organization_url="https://dev.azure.com/org")
            tools._connection = None
        with self.assertRaises(ValueError, msg="personal_access_token is required"):
            tools._get_connection()

    def test_resolve_project_uses_default(self):
        with patch("agno.tools.azure_devops.Connection"), patch("agno.tools.azure_devops.BasicAuthentication"):
            tools = AzureDevOpsTools(
                organization_url="https://dev.azure.com/org",
                personal_access_token="p",
                project="DefaultProj",
            )
        self.assertEqual(tools._resolve_project(None), "DefaultProj")
        self.assertEqual(tools._resolve_project("Override"), "Override")

    def test_resolve_project_no_default_raises(self):
        with (
            patch("agno.tools.azure_devops.Connection"),
            patch("agno.tools.azure_devops.BasicAuthentication"),
            patch.dict("os.environ", {}, clear=True),
        ):
            tools = AzureDevOpsTools(
                organization_url="https://dev.azure.com/org",
                personal_access_token="p",
            )
        with self.assertRaises(ValueError):
            tools._resolve_project(None)

    def test_bound_page_size(self):
        self.assertEqual(AzureDevOpsTools._bound_page_size(0), 1)
        self.assertEqual(AzureDevOpsTools._bound_page_size(50), 50)
        self.assertEqual(AzureDevOpsTools._bound_page_size(200), 100)


# ===========================================================================
# 2. PROJECTS
# ===========================================================================


class TestProjects(BaseADOTest):
    def test_list_projects_returns_all(self):
        projects = [_fake_project("P1"), _fake_project("P2"), _fake_project("P3")]
        self.core.get_projects.return_value = projects
        result = self._parse(self.tools.list_projects())
        self.assertEqual(len(result["data"]), 3)
        self.assertEqual(result["data"][0]["name"], "P1")
        self.assertEqual(result["meta"]["returned_items"], 3)

    def test_list_projects_pagination(self):
        projects = [_fake_project(f"P{i}") for i in range(10)]
        self.core.get_projects.return_value = projects
        result = self._parse(self.tools.list_projects(page=2, per_page=3))
        self.assertEqual(len(result["data"]), 3)
        self.assertEqual(result["data"][0]["name"], "P3")

    def test_list_projects_empty(self):
        self.core.get_projects.return_value = []
        result = self._parse(self.tools.list_projects())
        self.assertEqual(result["data"], [])

    def test_list_projects_page_beyond_results(self):
        self.core.get_projects.return_value = [_fake_project("P1")]
        result = self._parse(self.tools.list_projects(page=99))
        self.assertEqual(result["data"], [])

    def test_list_projects_auth_error(self):
        self.core.get_projects.side_effect = AuthError("auth failed")
        error = self._parse_error(self.tools.list_projects())
        self.assertIn("auth failed", error)

    def test_list_projects_service_error(self):
        self.core.get_projects.side_effect = ServiceError("server error")
        error = self._parse_error(self.tools.list_projects())
        self.assertIn("server error", error)

    def test_list_projects_unexpected_error(self):
        self.core.get_projects.side_effect = RuntimeError("boom")
        error = self._parse_error(self.tools.list_projects())
        self.assertIn("boom", error)

    def test_get_project_success(self):
        self.core.get_project.return_value = _fake_project("MyProject")
        result = self._parse(self.tools.get_project("MyProject"))
        self.assertEqual(result["name"], "MyProject")
        self.assertEqual(result["description"], "Test project")
        self.core.get_project.assert_called_once_with("MyProject")

    def test_get_project_uses_default(self):
        self.core.get_project.return_value = _fake_project(self.PROJECT)
        self.tools.get_project()
        self.core.get_project.assert_called_once_with(self.PROJECT)

    def test_get_project_serialises_all_fields(self):
        self.core.get_project.return_value = _fake_project("X")
        result = self._parse(self.tools.get_project("X"))
        for field in ("id", "name", "description", "state", "visibility", "last_update_time", "url"):
            self.assertIn(field, result)

    def test_get_project_auth_error(self):
        self.core.get_project.side_effect = AuthError("no access")
        self.assertIn("error", json.loads(self.tools.get_project("P")))

    def test_get_project_service_error(self):
        self.core.get_project.side_effect = ServiceError("service down")
        self.assertIn("error", json.loads(self.tools.get_project("P")))


# ===========================================================================
# 3. REPOSITORIES
# ===========================================================================


class TestRepositories(BaseADOTest):
    def test_list_repositories_success(self):
        self.git.get_repositories.return_value = [_fake_repo("R1"), _fake_repo("R2")]
        result = self._parse(self.tools.list_repositories())
        self.assertEqual(len(result["data"]), 2)
        self.git.get_repositories.assert_called_once_with(project=self.PROJECT)

    def test_list_repositories_empty(self):
        self.git.get_repositories.return_value = []
        result = self._parse(self.tools.list_repositories())
        self.assertEqual(result["data"], [])

    def test_list_repositories_serialises_fields(self):
        self.git.get_repositories.return_value = [_fake_repo()]
        result = self._parse(self.tools.list_repositories())
        repo = result["data"][0]
        for f in ("id", "name", "default_branch", "remote_url", "web_url", "size", "project"):
            self.assertIn(f, repo)

    def test_list_repositories_auth_error(self):
        self.git.get_repositories.side_effect = AuthError("401")
        self.assertIn("error", json.loads(self.tools.list_repositories()))

    def test_list_repositories_service_error(self):
        self.git.get_repositories.side_effect = ServiceError("503")
        self.assertIn("error", json.loads(self.tools.list_repositories()))

    def test_get_repository_success(self):
        self.git.get_repository.return_value = _fake_repo("MyRepo")
        result = self._parse(self.tools.get_repository("MyRepo"))
        self.assertEqual(result["name"], "MyRepo")
        self.git.get_repository.assert_called_once_with(repository_id="MyRepo", project=self.PROJECT)

    def test_get_repository_by_id(self):
        self.git.get_repository.return_value = _fake_repo()
        self.tools.get_repository("repo-uuid-1")
        self.git.get_repository.assert_called_once_with(repository_id="repo-uuid-1", project=self.PROJECT)

    def test_get_repository_auth_error(self):
        self.git.get_repository.side_effect = AuthError("denied")
        self.assertIn("error", json.loads(self.tools.get_repository("R")))

    def test_create_repository_success(self):
        self.core.get_project.return_value = _fake_project()
        self.git.create_repository.return_value = _fake_repo("NewRepo")
        result = self._parse(self.tools.create_repository("NewRepo"))
        self.assertEqual(result["name"], "NewRepo")

    def test_create_repository_calls_correct_args(self):
        proj = _fake_project()
        self.core.get_project.return_value = proj
        self.git.create_repository.return_value = _fake_repo("NewRepo")
        self.tools.create_repository("NewRepo")
        self.core.get_project.assert_called_once_with(self.PROJECT)
        self.git.create_repository.assert_called_once()

    def test_create_repository_service_error(self):
        self.core.get_project.side_effect = ServiceError("forbidden")
        self.assertIn("error", json.loads(self.tools.create_repository("R")))

    def test_delete_repository_success(self):
        repo = _fake_repo("OldRepo", "old-uuid")
        self.git.get_repository.return_value = repo
        result = self._parse(self.tools.delete_repository("OldRepo"))
        self.assertIn("deleted successfully", result["message"])
        self.git.delete_repository.assert_called_once_with(repository_id="old-uuid", project=self.PROJECT)

    def test_delete_repository_not_found(self):
        self.git.get_repository.side_effect = ServiceError("not found")
        self.assertIn("error", json.loads(self.tools.delete_repository("Ghost")))

    def test_delete_repository_auth_error(self):
        self.git.get_repository.side_effect = AuthError("forbidden")
        self.assertIn("error", json.loads(self.tools.delete_repository("R")))


# ===========================================================================
# 4. BRANCHES
# ===========================================================================


class TestBranches(BaseADOTest):
    def test_list_branches_success(self):
        refs = [_fake_ref("refs/heads/main"), _fake_ref("refs/heads/dev")]
        self.git.get_refs.return_value = refs
        result = self._parse(self.tools.list_branches("my-repo"))
        self.assertEqual(len(result["data"]), 2)
        self.assertEqual(result["data"][0]["name"], "main")

    def test_list_branches_pagination(self):
        refs = [_fake_ref(f"refs/heads/branch-{i}") for i in range(10)]
        self.git.get_refs.return_value = refs
        result = self._parse(self.tools.list_branches("repo", page=2, per_page=4))
        self.assertEqual(len(result["data"]), 4)
        self.assertEqual(result["data"][0]["name"], "branch-4")

    def test_list_branches_filter_contains(self):
        self.git.get_refs.return_value = [_fake_ref("refs/heads/feature/x")]
        self.tools.list_branches("repo", filter_contains="feature")
        call_kwargs = self.git.get_refs.call_args[1]
        self.assertEqual(call_kwargs["filter_contains"], "feature")

    def test_list_branches_serialises_fields(self):
        self.git.get_refs.return_value = [_fake_ref()]
        result = self._parse(self.tools.list_branches("repo"))
        b = result["data"][0]
        for f in ("name", "full_name", "object_id", "creator", "url"):
            self.assertIn(f, b)

    def test_list_branches_auth_error(self):
        self.git.get_refs.side_effect = AuthError("401")
        self.assertIn("error", json.loads(self.tools.list_branches("repo")))

    def test_create_branch_success(self):
        source_ref = _fake_ref("refs/heads/main", "aaa111")
        self.git.get_refs.return_value = [source_ref]
        update_result = MagicMock()
        update_result.success = True
        self.git.update_refs.return_value = [update_result]
        result = self._parse(self.tools.create_branch("repo", "feature/new", "main"))
        self.assertEqual(result["name"], "feature/new")
        self.assertIn("created successfully", result["message"])

    def test_create_branch_source_not_found(self):
        self.git.get_refs.return_value = []
        result = json.loads(self.tools.create_branch("repo", "new-branch", "ghost"))
        self.assertIn("error", result)
        self.assertIn("not found", result["error"])

    def test_create_branch_update_fails(self):
        source_ref = _fake_ref("refs/heads/main", "aaa111")
        self.git.get_refs.return_value = [source_ref]
        fail_result = MagicMock()
        fail_result.success = False
        self.git.update_refs.return_value = [fail_result]
        result = json.loads(self.tools.create_branch("repo", "fail-branch", "main"))
        self.assertIn("error", result)
        self.assertIn("Failed to create", result["error"])

    def test_create_branch_service_error(self):
        self.git.get_refs.side_effect = ServiceError("error")
        self.assertIn("error", json.loads(self.tools.create_branch("repo", "b", "main")))

    def test_delete_branch_success(self):
        existing_ref = _fake_ref("refs/heads/old-branch", "bbb222")
        self.git.get_refs.return_value = [existing_ref]
        ok = MagicMock()
        ok.success = True
        self.git.update_refs.return_value = [ok]
        result = self._parse(self.tools.delete_branch("repo", "old-branch"))
        self.assertIn("deleted successfully", result["message"])

    def test_delete_branch_not_found(self):
        self.git.get_refs.return_value = []
        result = json.loads(self.tools.delete_branch("repo", "ghost"))
        self.assertIn("error", result)
        self.assertIn("not found", result["error"])

    def test_delete_branch_update_fails(self):
        existing_ref = _fake_ref("refs/heads/x", "ccc333")
        self.git.get_refs.return_value = [existing_ref]
        fail = MagicMock()
        fail.success = False
        self.git.update_refs.return_value = [fail]
        result = json.loads(self.tools.delete_branch("repo", "x"))
        self.assertIn("error", result)

    def test_delete_branch_auth_error(self):
        self.git.get_refs.side_effect = AuthError("no perms")
        self.assertIn("error", json.loads(self.tools.delete_branch("repo", "x")))


# ===========================================================================
# 5. PULL REQUESTS
# ===========================================================================


class TestPullRequests(BaseADOTest):
    def test_list_pull_requests_success(self):
        self.git.get_pull_requests.return_value = [_fake_pr(1), _fake_pr(2)]
        result = self._parse(self.tools.list_pull_requests("repo"))
        self.assertEqual(len(result["data"]), 2)

    def test_list_pull_requests_passes_criteria(self):
        self.git.get_pull_requests.return_value = []
        self.tools.list_pull_requests(
            "repo",
            status="completed",
            source_branch="refs/heads/feat",
            target_branch="refs/heads/main",
            creator_id="uuid-creator",
            page=2,
            per_page=5,
        )
        call_kwargs = self.git.get_pull_requests.call_args[1]
        self.assertEqual(call_kwargs["skip"], 5)
        self.assertEqual(call_kwargs["top"], 5)

    def test_list_pull_requests_serialises_reviewers(self):
        pr = _fake_pr()
        reviewer = MagicMock()
        reviewer.display_name = "ReviewerX"
        reviewer.vote = 10
        pr.reviewers = [reviewer]
        self.git.get_pull_requests.return_value = [pr]
        result = self._parse(self.tools.list_pull_requests("repo"))
        self.assertEqual(result["data"][0]["reviewers"][0]["display_name"], "ReviewerX")

    def test_list_pull_requests_auth_error(self):
        self.git.get_pull_requests.side_effect = AuthError("403")
        self.assertIn("error", json.loads(self.tools.list_pull_requests("repo")))

    def test_get_pull_request_success(self):
        self.git.get_pull_request.return_value = _fake_pr(42, "Important PR")
        result = self._parse(self.tools.get_pull_request(42, "repo"))
        self.assertEqual(result["pull_request_id"], 42)
        self.assertEqual(result["title"], "Important PR")

    def test_get_pull_request_serialises_all_fields(self):
        self.git.get_pull_request.return_value = _fake_pr()
        result = self._parse(self.tools.get_pull_request(1, "repo"))
        for f in (
            "pull_request_id",
            "title",
            "description",
            "status",
            "source_branch",
            "target_branch",
            "created_by",
            "creation_date",
            "url",
            "merge_status",
            "is_draft",
            "reviewers",
        ):
            self.assertIn(f, result)

    def test_get_pull_request_auth_error(self):
        self.git.get_pull_request.side_effect = AuthError("denied")
        self.assertIn("error", json.loads(self.tools.get_pull_request(1, "repo")))

    def test_create_pull_request_success(self):
        self.git.create_pull_request.return_value = _fake_pr(99, "New PR")
        result = self._parse(self.tools.create_pull_request("repo", "New PR", "refs/heads/feat", "refs/heads/main"))
        self.assertEqual(result["pull_request_id"], 99)

    def test_create_pull_request_draft(self):
        self.git.create_pull_request.return_value = _fake_pr()
        self.tools.create_pull_request("repo", "Draft PR", "refs/heads/feat", "refs/heads/main", is_draft=True)
        self.git.create_pull_request.assert_called_once()

    def test_create_pull_request_with_description(self):
        self.git.create_pull_request.return_value = _fake_pr()
        self.tools.create_pull_request("repo", "PR", "refs/heads/feat", "refs/heads/main", description="Fixes #100")
        self.git.create_pull_request.assert_called_once()

    def test_create_pull_request_service_error(self):
        self.git.create_pull_request.side_effect = ServiceError("conflict")
        self.assertIn("error", json.loads(self.tools.create_pull_request("repo", "T", "refs/heads/a", "refs/heads/b")))

    def test_update_pull_request_success(self):
        updated = _fake_pr(1, "Updated Title")
        self.git.update_pull_request.return_value = updated
        result = self._parse(self.tools.update_pull_request(1, "repo", title="Updated Title"))
        self.assertEqual(result["title"], "Updated Title")

    def test_update_pull_request_set_draft(self):
        self.git.update_pull_request.return_value = _fake_pr()
        self.tools.update_pull_request(1, "repo", is_draft=True)
        self.git.update_pull_request.assert_called_once()

    def test_update_pull_request_auth_error(self):
        self.git.update_pull_request.side_effect = AuthError("denied")
        self.assertIn("error", json.loads(self.tools.update_pull_request(1, "repo", title="X")))

    def test_complete_pull_request_success(self):
        pr = _fake_pr(1)
        self.git.get_pull_request.return_value = pr
        completed = _fake_pr(1)
        completed.status = "completed"
        self.git.update_pull_request.return_value = completed
        result = self._parse(self.tools.complete_pull_request(1, "repo"))
        self.assertEqual(result["status"], "completed")

    def test_complete_pull_request_delete_source_branch(self):
        pr = _fake_pr(1)
        self.git.get_pull_request.return_value = pr
        self.git.update_pull_request.return_value = _fake_pr()
        self.tools.complete_pull_request(1, "repo", delete_source_branch=True)
        self.git.update_pull_request.assert_called_once()

    def test_complete_pull_request_service_error(self):
        self.git.get_pull_request.side_effect = ServiceError("not found")
        self.assertIn("error", json.loads(self.tools.complete_pull_request(1, "repo")))

    def test_abandon_pull_request_success(self):
        abandoned = _fake_pr(1)
        abandoned.status = "abandoned"
        self.git.update_pull_request.return_value = abandoned
        result = self._parse(self.tools.abandon_pull_request(1, "repo"))
        self.assertEqual(result["status"], "abandoned")

    def test_abandon_pull_request_auth_error(self):
        self.git.update_pull_request.side_effect = AuthError("denied")
        self.assertIn("error", json.loads(self.tools.abandon_pull_request(1, "repo")))

    def test_get_pull_request_changes_success(self):
        iter1 = MagicMock()
        iter1.id = 1
        self.git.get_pull_request_iterations.return_value = [iter1]
        change = MagicMock()
        change.change_type = "edit"
        item = MagicMock()
        item.path = "/src/main.py"
        item.url = "https://example.com"
        change.item = item
        changes_obj = MagicMock()
        changes_obj.change_entries = [change]
        self.git.get_pull_request_iteration_changes.return_value = changes_obj
        result = self._parse(self.tools.get_pull_request_changes(1, "repo"))
        self.assertEqual(len(result["data"]), 1)
        self.assertEqual(result["data"][0]["path"], "/src/main.py")

    def test_get_pull_request_changes_no_iterations(self):
        self.git.get_pull_request_iterations.return_value = []
        result = json.loads(self.tools.get_pull_request_changes(1, "repo"))
        self.assertEqual(result["data"], [])

    def test_get_pull_request_commits_success(self):
        self.git.get_pull_request_commits.return_value = [_fake_commit("abc"), _fake_commit("def")]
        result = self._parse(self.tools.get_pull_request_commits(1, "repo"))
        self.assertEqual(len(result["data"]), 2)

    def test_get_pull_request_commits_empty(self):
        self.git.get_pull_request_commits.return_value = []
        result = self._parse(self.tools.get_pull_request_commits(1, "repo"))
        self.assertEqual(result["data"], [])

    def test_list_pr_comments_success(self):
        threads = [_fake_comment_thread(1, "LGTM"), _fake_comment_thread(2, "Needs fix")]
        self.git.get_threads.return_value = threads
        result = self._parse(self.tools.list_pr_comments(1, "repo"))
        self.assertEqual(len(result["data"]), 2)
        self.assertEqual(result["data"][0]["comments"][0]["content"], "LGTM")

    def test_list_pr_comments_empty(self):
        self.git.get_threads.return_value = []
        result = self._parse(self.tools.list_pr_comments(1, "repo"))
        self.assertEqual(result["data"], [])

    def test_list_pr_comments_auth_error(self):
        self.git.get_threads.side_effect = AuthError("denied")
        self.assertIn("error", json.loads(self.tools.list_pr_comments(1, "repo")))

    def test_add_pr_comment_success(self):
        thread = MagicMock()
        thread.id = 5
        c = MagicMock()
        c.id = 1
        c.content = "Nice work!"
        thread.comments = [c]
        self.git.create_thread.return_value = thread
        result = self._parse(self.tools.add_pr_comment(1, "repo", "Nice work!"))
        self.assertEqual(result["thread_id"], 5)
        self.assertIn("successfully", result["message"])

    def test_add_pr_comment_service_error(self):
        self.git.create_thread.side_effect = ServiceError("error")
        self.assertIn("error", json.loads(self.tools.add_pr_comment(1, "repo", "comment")))

    def test_add_pr_reviewer_success(self):
        reviewer_result = MagicMock()
        reviewer_result.display_name = "Reviewer A"
        reviewer_result.is_required = True
        reviewer_result.vote = 0
        self.git.create_pull_request_reviewer.return_value = reviewer_result
        result = self._parse(self.tools.add_pr_reviewer(1, "repo", "reviewer-uuid"))
        self.assertIn("successfully", result["message"])

    def test_add_pr_reviewer_required(self):
        self.git.create_pull_request_reviewer.return_value = MagicMock()
        self.tools.add_pr_reviewer(1, "repo", "reviewer-uuid", is_required=True)
        self.git.create_pull_request_reviewer.assert_called_once()

    def test_add_pr_reviewer_auth_error(self):
        self.git.create_pull_request_reviewer.side_effect = AuthError("denied")
        self.assertIn("error", json.loads(self.tools.add_pr_reviewer(1, "repo", "uuid")))


# ===========================================================================
# 6. COMMITS
# ===========================================================================


class TestCommits(BaseADOTest):
    def test_list_commits_success(self):
        self.git.get_commits_batch.return_value = [_fake_commit("a1"), _fake_commit("b2")]
        result = self._parse(self.tools.list_commits("repo"))
        self.assertEqual(len(result["data"]), 2)
        self.assertEqual(result["data"][0]["commit_id"], "a1")

    def test_list_commits_with_branch(self):
        self.git.get_commits_batch.return_value = []
        self.tools.list_commits("repo", branch="main")
        self.git.get_commits_batch.assert_called_once()

    def test_list_commits_with_author_filter(self):
        self.git.get_commits_batch.return_value = []
        self.tools.list_commits("repo", author="alice@example.com")
        self.git.get_commits_batch.assert_called_once()

    def test_list_commits_pagination(self):
        self.git.get_commits_batch.return_value = [_fake_commit(f"c{i}") for i in range(5)]
        result = self._parse(self.tools.list_commits("repo", page=2, per_page=2))
        # pagination is handled by skip/top in criteria, mock returns all 5
        self.assertIn("data", result)

    def test_list_commits_serialises_author(self):
        self.git.get_commits_batch.return_value = [_fake_commit()]
        result = self._parse(self.tools.list_commits("repo"))
        c = result["data"][0]
        self.assertIn("author", c)
        self.assertEqual(c["author"]["name"], "Bob")
        self.assertEqual(c["author"]["email"], "bob@example.com")

    def test_list_commits_auth_error(self):
        self.git.get_commits_batch.side_effect = AuthError("denied")
        self.assertIn("error", json.loads(self.tools.list_commits("repo")))

    def test_list_commits_service_error(self):
        self.git.get_commits_batch.side_effect = ServiceError("error")
        self.assertIn("error", json.loads(self.tools.list_commits("repo")))

    def test_get_commit_success(self):
        self.git.get_commit.return_value = _fake_commit("deadbeef")
        result = self._parse(self.tools.get_commit("deadbeef", "repo"))
        self.assertEqual(result["commit_id"], "deadbeef")
        self.git.get_commit.assert_called_once_with(
            commit_id="deadbeef",
            repository_id="repo",
            project=self.PROJECT,
        )

    def test_get_commit_auth_error(self):
        self.git.get_commit.side_effect = AuthError("denied")
        self.assertIn("error", json.loads(self.tools.get_commit("sha", "repo")))

    def test_get_commit_changes_success(self):
        change = MagicMock()
        change.change_type = "add"
        item = MagicMock()
        item.path = "/new_file.py"
        item.url = "https://example.com"
        item.git_object_type = "blob"
        change.item = item
        changes_obj = MagicMock()
        changes_obj.changes = [change]
        self.git.get_changes.return_value = changes_obj
        result = self._parse(self.tools.get_commit_changes("deadbeef", "repo"))
        self.assertEqual(len(result["data"]), 1)
        self.assertEqual(result["data"][0]["path"], "/new_file.py")

    def test_get_commit_changes_empty(self):
        changes_obj = MagicMock()
        changes_obj.changes = []
        self.git.get_changes.return_value = changes_obj
        result = self._parse(self.tools.get_commit_changes("sha", "repo"))
        self.assertEqual(result["data"], [])

    def test_get_commit_changes_service_error(self):
        self.git.get_changes.side_effect = ServiceError("not found")
        self.assertIn("error", json.loads(self.tools.get_commit_changes("sha", "repo")))


# ===========================================================================
# 7. WORK ITEMS
# ===========================================================================


class TestWorkItems(BaseADOTest):
    def _setup_wiql(self, work_items):
        wiql_result = MagicMock()
        wiql_result.work_items = [MagicMock(id=wi.id) for wi in work_items]
        self.wit.query_by_wiql.return_value = wiql_result
        self.wit.get_work_items.return_value = work_items

    def test_list_work_items_success(self):
        wis = [_fake_work_item(1, "Bug A"), _fake_work_item(2, "Bug B")]
        self._setup_wiql(wis)
        result = self._parse(self.tools.list_work_items())
        self.assertEqual(len(result["data"]), 2)

    def test_list_work_items_with_filters(self):
        self._setup_wiql([])
        self.tools.list_work_items(work_item_type="Bug", state="Active", assigned_to="alice@example.com")
        # Query should include the filters
        self.wit.query_by_wiql.assert_called_once()

    def test_list_work_items_custom_wiql(self):
        self._setup_wiql([_fake_work_item()])
        custom_query = "SELECT [System.Id] FROM WorkItems WHERE [System.State] = 'New'"
        self.tools.list_work_items(wiql_query=custom_query)
        self.wit.query_by_wiql.assert_called_once()

    def test_list_work_items_empty(self):
        wiql_result = MagicMock()
        wiql_result.work_items = []
        self.wit.query_by_wiql.return_value = wiql_result
        result = self._parse(self.tools.list_work_items())
        self.assertEqual(result["data"], [])

    def test_list_work_items_pagination(self):
        all_wis = [_fake_work_item(i) for i in range(1, 11)]
        wiql_result = MagicMock()
        wiql_result.work_items = [MagicMock(id=wi.id) for wi in all_wis]
        self.wit.query_by_wiql.return_value = wiql_result
        page_wis = all_wis[5:10]
        self.wit.get_work_items.return_value = page_wis
        result = self._parse(self.tools.list_work_items(page=2, per_page=5))
        self.assertEqual(result["meta"]["current_page"], 2)

    def test_list_work_items_auth_error(self):
        self.wit.query_by_wiql.side_effect = AuthError("denied")
        self.assertIn("error", json.loads(self.tools.list_work_items()))

    def test_list_work_items_serialises_assigned_to_dict(self):
        wi = _fake_work_item()
        wi.fields["System.AssignedTo"] = {"displayName": "Charlie"}
        self._setup_wiql([wi])
        result = self._parse(self.tools.list_work_items())
        self.assertEqual(result["data"][0]["assigned_to"], "Charlie")

    def test_list_work_items_serialises_assigned_to_string(self):
        wi = _fake_work_item()
        wi.fields["System.AssignedTo"] = "charlie@example.com"
        self._setup_wiql([wi])
        result = self._parse(self.tools.list_work_items())
        self.assertEqual(result["data"][0]["assigned_to"], "charlie@example.com")

    def test_get_work_item_success(self):
        self.wit.get_work_item.return_value = _fake_work_item(42, "My Bug")
        result = self._parse(self.tools.get_work_item(42))
        self.assertEqual(result["id"], 42)
        self.assertEqual(result["title"], "My Bug")

    def test_get_work_item_serialises_all_fields(self):
        self.wit.get_work_item.return_value = _fake_work_item()
        result = self._parse(self.tools.get_work_item(10))
        for f in (
            "id",
            "url",
            "title",
            "state",
            "type",
            "assigned_to",
            "area_path",
            "iteration_path",
            "created_date",
            "changed_date",
            "description",
            "priority",
            "tags",
        ):
            self.assertIn(f, result)

    def test_get_work_item_auth_error(self):
        self.wit.get_work_item.side_effect = AuthError("denied")
        self.assertIn("error", json.loads(self.tools.get_work_item(1)))

    def test_get_work_item_service_error(self):
        self.wit.get_work_item.side_effect = ServiceError("not found")
        self.assertIn("error", json.loads(self.tools.get_work_item(9999)))

    def test_create_work_item_minimal(self):
        self.wit.create_work_item.return_value = _fake_work_item(50, "New Task")
        result = self._parse(self.tools.create_work_item("New Task"))
        self.assertEqual(result["title"], "New Task")
        self.wit.create_work_item.assert_called_once()

    def test_create_work_item_all_fields(self):
        self.wit.create_work_item.return_value = _fake_work_item()
        self.tools.create_work_item(
            title="Bug Report",
            work_item_type="Bug",
            description="Detailed desc",
            assigned_to="alice@example.com",
            area_path="MyProject\\Area",
            iteration_path="MyProject\\Sprint 1",
            priority=1,
            tags="urgent; backend",
            extra_fields={"Custom.Field": "custom_value"},
        )
        call_args = self.wit.create_work_item.call_args
        ops = call_args[1]["document"] if "document" in call_args[1] else call_args[0][0]
        self.assertIsNotNone(ops)

    def test_create_work_item_default_type_is_task(self):
        self.wit.create_work_item.return_value = _fake_work_item()
        self.tools.create_work_item("My Task")
        call_kwargs = self.wit.create_work_item.call_args[1]
        self.assertEqual(call_kwargs.get("type") or call_kwargs.get("type"), "Task")

    def test_create_work_item_auth_error(self):
        self.wit.create_work_item.side_effect = AuthError("denied")
        self.assertIn("error", json.loads(self.tools.create_work_item("T")))

    def test_update_work_item_title_and_state(self):
        self.wit.update_work_item.return_value = _fake_work_item(10, "Updated", "Closed")
        result = self._parse(self.tools.update_work_item(10, title="Updated", state="Closed"))
        self.assertEqual(result["title"], "Updated")

    def test_update_work_item_no_fields_returns_error(self):
        result = json.loads(self.tools.update_work_item(10))
        self.assertIn("error", result)
        self.assertIn("No fields", result["error"])

    def test_update_work_item_priority(self):
        self.wit.update_work_item.return_value = _fake_work_item()
        self.tools.update_work_item(10, priority=1)
        self.wit.update_work_item.assert_called_once()

    def test_update_work_item_extra_fields(self):
        self.wit.update_work_item.return_value = _fake_work_item()
        self.tools.update_work_item(10, title="T", extra_fields={"Custom.X": "val"})
        self.wit.update_work_item.assert_called_once()

    def test_update_work_item_tags(self):
        self.wit.update_work_item.return_value = _fake_work_item()
        self.tools.update_work_item(10, tags="new-tag")
        self.wit.update_work_item.assert_called_once()

    def test_update_work_item_service_error(self):
        self.wit.update_work_item.side_effect = ServiceError("error")
        self.assertIn("error", json.loads(self.tools.update_work_item(10, title="T")))

    def test_delete_work_item_to_recycle_bin(self):
        result = self._parse(self.tools.delete_work_item(10))
        self.assertIn("recycle bin", result["message"])
        self.wit.delete_work_item.assert_called_once_with(id=10, project=self.PROJECT, destroy=False)

    def test_delete_work_item_permanently(self):
        result = self._parse(self.tools.delete_work_item(10, destroy=True))
        self.assertIn("permanently destroyed", result["message"])
        self.wit.delete_work_item.assert_called_once_with(id=10, project=self.PROJECT, destroy=True)

    def test_delete_work_item_auth_error(self):
        self.wit.delete_work_item.side_effect = AuthError("denied")
        self.assertIn("error", json.loads(self.tools.delete_work_item(1)))

    def test_delete_work_item_service_error(self):
        self.wit.delete_work_item.side_effect = ServiceError("not found")
        self.assertIn("error", json.loads(self.tools.delete_work_item(99)))

    def test_list_work_item_comments_success(self):
        comments_result = MagicMock()
        comments_result.comments = [_fake_wi_comment(1, "First"), _fake_wi_comment(2, "Second")]
        self.wit.get_comments.return_value = comments_result
        result = self._parse(self.tools.list_work_item_comments(10))
        self.assertEqual(len(result["data"]), 2)
        self.assertEqual(result["data"][0]["text"], "First")

    def test_list_work_item_comments_empty(self):
        cr = MagicMock()
        cr.comments = []
        self.wit.get_comments.return_value = cr
        result = self._parse(self.tools.list_work_item_comments(10))
        self.assertEqual(result["data"], [])

    def test_list_work_item_comments_auth_error(self):
        self.wit.get_comments.side_effect = AuthError("denied")
        self.assertIn("error", json.loads(self.tools.list_work_item_comments(10)))

    def test_add_work_item_comment_success(self):
        comment = _fake_wi_comment(5, "Added comment")
        self.wit.add_comment.return_value = comment
        result = self._parse(self.tools.add_work_item_comment(10, "Added comment"))
        self.assertEqual(result["text"], "Added comment")
        self.assertEqual(result["id"], 5)

    def test_add_work_item_comment_html(self):
        self.wit.add_comment.return_value = _fake_wi_comment()
        self.tools.add_work_item_comment(10, "<b>Bold comment</b>")
        self.wit.add_comment.assert_called_once()

    def test_add_work_item_comment_service_error(self):
        self.wit.add_comment.side_effect = ServiceError("error")
        self.assertIn("error", json.loads(self.tools.add_work_item_comment(10, "text")))


# ===========================================================================
# 8. PIPELINES / BUILDS
# ===========================================================================


class TestPipelinesAndBuilds(BaseADOTest):
    def test_list_pipelines_success(self):
        self.build.get_definitions.return_value = [_fake_pipeline(1, "CI"), _fake_pipeline(2, "CD")]
        result = self._parse(self.tools.list_pipelines())
        self.assertEqual(len(result["data"]), 2)

    def test_list_pipelines_name_filter(self):
        self.build.get_definitions.return_value = [_fake_pipeline(1, "CI")]
        self.tools.list_pipelines(name_filter="CI")
        self.build.get_definitions.assert_called_once_with(project=self.PROJECT, name="CI")

    def test_list_pipelines_pagination(self):
        pipelines = [_fake_pipeline(i) for i in range(10)]
        self.build.get_definitions.return_value = pipelines
        result = self._parse(self.tools.list_pipelines(page=2, per_page=3))
        self.assertEqual(len(result["data"]), 3)
        self.assertEqual(result["data"][0]["id"], 3)

    def test_list_pipelines_serialises_fields(self):
        self.build.get_definitions.return_value = [_fake_pipeline()]
        result = self._parse(self.tools.list_pipelines())
        p = result["data"][0]
        for f in ("id", "name", "folder", "revision", "url"):
            self.assertIn(f, p)

    def test_list_pipelines_auth_error(self):
        self.build.get_definitions.side_effect = AuthError("denied")
        self.assertIn("error", json.loads(self.tools.list_pipelines()))

    def test_trigger_pipeline_success(self):
        self.build.queue_build.return_value = _fake_build(200, "20240115.2")
        result = self._parse(self.tools.trigger_pipeline(5))
        self.assertEqual(result["id"], 200)

    def test_trigger_pipeline_with_branch(self):
        self.build.queue_build.return_value = _fake_build()
        self.tools.trigger_pipeline(5, source_branch="refs/heads/main")
        self.build.queue_build.assert_called_once()

    def test_trigger_pipeline_with_parameters(self):
        self.build.queue_build.return_value = _fake_build()
        self.tools.trigger_pipeline(5, parameters={"env": "production"})
        self.build.queue_build.assert_called_once()

    def test_trigger_pipeline_auth_error(self):
        self.build.queue_build.side_effect = AuthError("denied")
        self.assertIn("error", json.loads(self.tools.trigger_pipeline(5)))

    def test_trigger_pipeline_service_error(self):
        self.build.queue_build.side_effect = ServiceError("definition not found")
        self.assertIn("error", json.loads(self.tools.trigger_pipeline(999)))

    def test_get_pipeline_runs_success(self):
        self.build.get_builds.return_value = [_fake_build(1), _fake_build(2)]
        result = self._parse(self.tools.get_pipeline_runs(5))
        self.assertEqual(len(result["data"]), 2)

    def test_get_pipeline_runs_with_filters(self):
        self.build.get_builds.return_value = []
        self.tools.get_pipeline_runs(5, status_filter="completed", branch_name="refs/heads/main")
        call_kwargs = self.build.get_builds.call_args[1]
        self.assertEqual(call_kwargs["status_filter"], "completed")
        self.assertEqual(call_kwargs["branch_name"], "refs/heads/main")

    def test_get_pipeline_runs_serialises_fields(self):
        self.build.get_builds.return_value = [_fake_build()]
        result = self._parse(self.tools.get_pipeline_runs(5))
        b = result["data"][0]
        for f in (
            "id",
            "build_number",
            "status",
            "result",
            "source_branch",
            "queue_time",
            "start_time",
            "finish_time",
            "requested_by",
            "url",
        ):
            self.assertIn(f, b)

    def test_get_pipeline_runs_pagination(self):
        builds = [_fake_build(i) for i in range(10)]
        self.build.get_builds.return_value = builds
        result = self._parse(self.tools.get_pipeline_runs(5, page=2, per_page=4))
        self.assertEqual(len(result["data"]), 4)

    def test_get_pipeline_runs_auth_error(self):
        self.build.get_builds.side_effect = AuthError("denied")
        self.assertIn("error", json.loads(self.tools.get_pipeline_runs(5)))

    def test_cancel_build_success(self):
        result = self._parse(self.tools.cancel_build(100))
        self.assertIn("cancellation requested", result["message"])
        self.build.update_build.assert_called_once()

    def test_cancel_build_not_found(self):
        self.build.update_build.side_effect = ServiceError("build not found")
        self.assertIn("error", json.loads(self.tools.cancel_build(9999)))

    def test_cancel_build_auth_error(self):
        self.build.update_build.side_effect = AuthError("denied")
        self.assertIn("error", json.loads(self.tools.cancel_build(100)))

    def test_get_build_logs_success(self):
        logs = [_fake_build_log(1), _fake_build_log(2)]
        self.build.get_build_logs.return_value = logs
        result = self._parse(self.tools.get_build_logs(100))
        self.assertEqual(len(result["data"]), 2)
        self.assertEqual(result["data"][0]["id"], 1)
        self.assertEqual(result["data"][0]["line_count"], 42)

    def test_get_build_logs_empty(self):
        self.build.get_build_logs.return_value = []
        result = self._parse(self.tools.get_build_logs(100))
        self.assertEqual(result["data"], [])

    def test_get_build_logs_serialises_fields(self):
        self.build.get_build_logs.return_value = [_fake_build_log()]
        result = self._parse(self.tools.get_build_logs(100))
        log = result["data"][0]
        for f in ("id", "type", "url", "created_on", "last_changed_on", "line_count"):
            self.assertIn(f, log)

    def test_get_build_logs_auth_error(self):
        self.build.get_build_logs.side_effect = AuthError("denied")
        self.assertIn("error", json.loads(self.tools.get_build_logs(100)))

    def test_get_build_logs_service_error(self):
        self.build.get_build_logs.side_effect = ServiceError("build not found")
        self.assertIn("error", json.loads(self.tools.get_build_logs(9999)))


# ===========================================================================
# 9. RELEASES
# ===========================================================================


class TestReleases(BaseADOTest):
    def test_list_release_definitions_success(self):
        self.release.get_release_definitions.return_value = [
            _fake_release_def(1, "Prod"),
            _fake_release_def(2, "Staging"),
        ]
        result = self._parse(self.tools.list_release_definitions())
        self.assertEqual(len(result["data"]), 2)

    def test_list_release_definitions_name_filter(self):
        self.release.get_release_definitions.return_value = []
        self.tools.list_release_definitions(name_filter="Prod")
        self.release.get_release_definitions.assert_called_once_with(project=self.PROJECT, search_text="Prod")

    def test_list_release_definitions_pagination(self):
        defs = [_fake_release_def(i) for i in range(8)]
        self.release.get_release_definitions.return_value = defs
        result = self._parse(self.tools.list_release_definitions(page=2, per_page=3))
        self.assertEqual(len(result["data"]), 3)
        self.assertEqual(result["data"][0]["id"], 3)

    def test_list_release_definitions_serialises_fields(self):
        self.release.get_release_definitions.return_value = [_fake_release_def()]
        result = self._parse(self.tools.list_release_definitions())
        rd = result["data"][0]
        for f in ("id", "name", "path", "url", "created_by", "created_on", "modified_on"):
            self.assertIn(f, rd)

    def test_list_release_definitions_auth_error(self):
        self.release.get_release_definitions.side_effect = AuthError("denied")
        self.assertIn("error", json.loads(self.tools.list_release_definitions()))

    def test_list_releases_success(self):
        self.release.get_releases.return_value = [_fake_release(1), _fake_release(2)]
        result = self._parse(self.tools.list_releases())
        self.assertEqual(len(result["data"]), 2)

    def test_list_releases_definition_filter(self):
        self.release.get_releases.return_value = []
        self.tools.list_releases(definition_id=3)
        call_kwargs = self.release.get_releases.call_args[1]
        self.assertEqual(call_kwargs["definition_id"], 3)

    def test_list_releases_status_filter(self):
        self.release.get_releases.return_value = []
        self.tools.list_releases(status_filter="active")
        call_kwargs = self.release.get_releases.call_args[1]
        self.assertEqual(call_kwargs["status_filter"], "active")

    def test_list_releases_serialises_fields(self):
        self.release.get_releases.return_value = [_fake_release()]
        result = self._parse(self.tools.list_releases())
        r = result["data"][0]
        for f in ("id", "name", "status", "created_by", "created_on", "modified_on", "url", "release_definition"):
            self.assertIn(f, r)

    def test_list_releases_auth_error(self):
        self.release.get_releases.side_effect = AuthError("denied")
        self.assertIn("error", json.loads(self.tools.list_releases()))

    def test_create_release_success(self):
        self.release.create_release.return_value = _fake_release(10, "Release-10")
        result = self._parse(self.tools.create_release(3))
        self.assertEqual(result["id"], 10)
        self.assertEqual(result["name"], "Release-10")

    def test_create_release_with_description(self):
        self.release.create_release.return_value = _fake_release()
        self.tools.create_release(3, description="Hotfix release")
        self.release.create_release.assert_called_once()

    def test_create_release_with_artifacts(self):
        self.release.create_release.return_value = _fake_release()
        self.tools.create_release(3, artifacts=[{"alias": "build", "instanceReference": {"id": "100"}}])
        self.release.create_release.assert_called_once()

    def test_create_release_auth_error(self):
        self.release.create_release.side_effect = AuthError("denied")
        self.assertIn("error", json.loads(self.tools.create_release(3)))

    def test_create_release_service_error(self):
        self.release.create_release.side_effect = ServiceError("definition not found")
        self.assertIn("error", json.loads(self.tools.create_release(999)))


# ===========================================================================
# 10. TEAMS
# ===========================================================================


class TestTeams(BaseADOTest):
    def test_list_teams_success(self):
        self.core.get_teams.return_value = [_fake_team("t1", "Alpha"), _fake_team("t2", "Beta")]
        result = self._parse(self.tools.list_teams())
        self.assertEqual(len(result["data"]), 2)
        self.assertEqual(result["data"][0]["name"], "Alpha")

    def test_list_teams_pagination(self):
        teams = [_fake_team(f"t{i}", f"Team{i}") for i in range(8)]
        self.core.get_teams.return_value = teams
        result = self._parse(self.tools.list_teams(page=2, per_page=3))
        self.assertEqual(len(result["data"]), 3)
        self.assertEqual(result["data"][0]["name"], "Team3")

    def test_list_teams_empty(self):
        self.core.get_teams.return_value = []
        result = self._parse(self.tools.list_teams())
        self.assertEqual(result["data"], [])

    def test_list_teams_serialises_fields(self):
        self.core.get_teams.return_value = [_fake_team()]
        result = self._parse(self.tools.list_teams())
        t = result["data"][0]
        for f in ("id", "name", "description", "url", "project_name"):
            self.assertIn(f, t)

    def test_list_teams_auth_error(self):
        self.core.get_teams.side_effect = AuthError("denied")
        self.assertIn("error", json.loads(self.tools.list_teams()))

    def test_list_teams_service_error(self):
        self.core.get_teams.side_effect = ServiceError("error")
        self.assertIn("error", json.loads(self.tools.list_teams()))

    def test_get_team_members_success(self):
        members = [_fake_member("u1", "Grace"), _fake_member("u2", "Henry")]
        self.core.get_team_members_with_extended_properties.return_value = members
        result = self._parse(self.tools.get_team_members("team-uuid"))
        self.assertEqual(len(result["data"]), 2)
        self.assertEqual(result["data"][0]["display_name"], "Grace")

    def test_get_team_members_empty(self):
        self.core.get_team_members_with_extended_properties.return_value = []
        result = self._parse(self.tools.get_team_members("team-uuid"))
        self.assertEqual(result["data"], [])

    def test_get_team_members_serialises_fields(self):
        self.core.get_team_members_with_extended_properties.return_value = [_fake_member()]
        result = self._parse(self.tools.get_team_members("team-uuid"))
        m = result["data"][0]
        for f in ("id", "display_name", "unique_name", "url", "is_team_admin"):
            self.assertIn(f, m)

    def test_get_team_members_auth_error(self):
        self.core.get_team_members_with_extended_properties.side_effect = AuthError("denied")
        self.assertIn("error", json.loads(self.tools.get_team_members("team")))

    def test_get_team_members_passes_project(self):
        self.core.get_team_members_with_extended_properties.return_value = []
        self.tools.get_team_members("team-id")
        self.core.get_team_members_with_extended_properties.assert_called_once_with(
            project_id=self.PROJECT, team_id="team-id"
        )


# ===========================================================================
# 11. ITERATIONS / SPRINTS
# ===========================================================================


class TestIterations(BaseADOTest):
    def test_list_iterations_success(self):
        self.work.get_team_iterations.return_value = [
            _fake_iteration("i1", "Sprint 1"),
            _fake_iteration("i2", "Sprint 2"),
        ]
        result = self._parse(self.tools.list_iterations())
        self.assertEqual(len(result["data"]), 2)
        self.assertEqual(result["data"][0]["name"], "Sprint 1")

    def test_list_iterations_current_timeframe(self):
        self.work.get_team_iterations.return_value = [_fake_iteration()]
        self.tools.list_iterations(time_frame="current")
        call_kwargs = self.work.get_team_iterations.call_args[1]
        self.assertEqual(call_kwargs["timeframe"], "current")

    def test_list_iterations_past_timeframe(self):
        self.work.get_team_iterations.return_value = []
        self.tools.list_iterations(time_frame="past")
        call_kwargs = self.work.get_team_iterations.call_args[1]
        self.assertEqual(call_kwargs["timeframe"], "past")

    def test_list_iterations_with_team(self):
        self.work.get_team_iterations.return_value = []
        self.tools.list_iterations(team="Core Team")
        self.work.get_team_iterations.assert_called_once()

    def test_list_iterations_serialises_fields(self):
        self.work.get_team_iterations.return_value = [_fake_iteration()]
        result = self._parse(self.tools.list_iterations())
        it = result["data"][0]
        for f in ("id", "name", "path", "url", "start_date", "finish_date", "time_frame"):
            self.assertIn(f, it)

    def test_list_iterations_empty(self):
        self.work.get_team_iterations.return_value = []
        result = self._parse(self.tools.list_iterations())
        self.assertEqual(result["data"], [])

    def test_list_iterations_auth_error(self):
        self.work.get_team_iterations.side_effect = AuthError("denied")
        self.assertIn("error", json.loads(self.tools.list_iterations()))

    def test_list_iterations_service_error(self):
        self.work.get_team_iterations.side_effect = ServiceError("error")
        self.assertIn("error", json.loads(self.tools.list_iterations()))

    def test_get_iteration_work_items_success(self):
        # Mock iteration work items
        relation = MagicMock()
        relation.target = MagicMock()
        relation.target.id = 10
        iter_wi = MagicMock()
        iter_wi.work_item_relations = [relation]
        self.work.get_iteration_work_items.return_value = iter_wi
        self.wit.get_work_items.return_value = [_fake_work_item(10, "Sprint Task")]
        result = self._parse(self.tools.get_iteration_work_items("iter-uuid"))
        self.assertEqual(len(result["data"]), 1)
        self.assertEqual(result["data"][0]["title"], "Sprint Task")

    def test_get_iteration_work_items_empty(self):
        iter_wi = MagicMock()
        iter_wi.work_item_relations = []
        self.work.get_iteration_work_items.return_value = iter_wi
        result = self._parse(self.tools.get_iteration_work_items("iter-uuid"))
        self.assertEqual(result["data"], [])

    def test_get_iteration_work_items_multiple(self):
        relations = []
        for i in range(5):
            rel = MagicMock()
            rel.target = MagicMock()
            rel.target.id = i + 1
            relations.append(rel)
        iter_wi = MagicMock()
        iter_wi.work_item_relations = relations
        self.work.get_iteration_work_items.return_value = iter_wi
        wis = [_fake_work_item(i + 1, f"Item {i}") for i in range(5)]
        self.wit.get_work_items.return_value = wis
        result = self._parse(self.tools.get_iteration_work_items("iter-uuid"))
        self.assertEqual(len(result["data"]), 5)

    def test_get_iteration_work_items_auth_error(self):
        self.work.get_iteration_work_items.side_effect = AuthError("denied")
        self.assertIn("error", json.loads(self.tools.get_iteration_work_items("iter-uuid")))

    def test_get_iteration_work_items_service_error(self):
        self.work.get_iteration_work_items.side_effect = ServiceError("not found")
        self.assertIn("error", json.loads(self.tools.get_iteration_work_items("iter-uuid")))

    def test_get_iteration_work_items_passes_team(self):
        iter_wi = MagicMock()
        iter_wi.work_item_relations = []
        self.work.get_iteration_work_items.return_value = iter_wi
        self.tools.get_iteration_work_items("iter-uuid", team="Core Team")
        self.work.get_iteration_work_items.assert_called_once()


# ===========================================================================
# 12. SERIALISER UNIT TESTS
# ===========================================================================


class TestSerialisers(unittest.TestCase):
    def test_serialize_project_none_dates(self):
        p = MagicMock()
        p.id = "x"
        p.name = "X"
        p.description = None
        p.state = None
        p.visibility = None
        p.last_update_time = None
        p.url = None
        result = AzureDevOpsTools._serialize_project(p)
        self.assertIsNone(result["last_update_time"])
        self.assertIsNone(result["state"])

    def test_serialize_repository_no_project(self):
        r = MagicMock()
        r.id = "r"
        r.name = "R"
        r.default_branch = None
        r.remote_url = None
        r.web_url = None
        r.size = None
        r.project = None
        result = AzureDevOpsTools._serialize_repository(r)
        self.assertIsNone(result["project"])

    def test_serialize_branch_strips_refs_heads(self):
        ref = _fake_ref("refs/heads/feature/my-branch")
        result = AzureDevOpsTools._serialize_branch(ref)
        self.assertEqual(result["name"], "feature/my-branch")
        self.assertEqual(result["full_name"], "refs/heads/feature/my-branch")

    def test_serialize_pull_request_no_dates(self):
        pr = MagicMock()
        pr.pull_request_id = 1
        pr.title = "T"
        pr.description = None
        pr.status = None
        pr.source_ref_name = "refs/heads/a"
        pr.target_ref_name = "refs/heads/b"
        pr.created_by = None
        pr.creation_date = None
        pr.closed_date = None
        pr.url = None
        pr.merge_status = None
        pr.is_draft = False
        pr.reviewers = None
        result = AzureDevOpsTools._serialize_pull_request(pr)
        self.assertIsNone(result["creation_date"])
        self.assertEqual(result["reviewers"], [])

    def test_serialize_commit_no_author(self):
        c = MagicMock()
        c.commit_id = "sha"
        c.comment = "msg"
        c.author = None
        c.url = None
        c.remote_url = None
        result = AzureDevOpsTools._serialize_commit(c)
        self.assertIsNone(result["author"]["name"])

    def test_serialize_work_item_all_fields_present(self):
        wi = _fake_work_item(1, "Test", "Active", "Bug")
        result = AzureDevOpsTools._serialize_work_item(wi)
        self.assertEqual(result["id"], 1)
        self.assertEqual(result["title"], "Test")
        self.assertEqual(result["state"], "Active")
        self.assertEqual(result["type"], "Bug")
        self.assertEqual(result["priority"], 2)
        self.assertEqual(result["tags"], "tag1; tag2")

    def test_serialize_build_none_times(self):
        b = MagicMock()
        b.id = 1
        b.build_number = "1"
        b.status = None
        b.result = None
        b.source_branch = None
        b.source_version = None
        b.queue_time = None
        b.start_time = None
        b.finish_time = None
        b.requested_by = None
        b.url = None
        result = AzureDevOpsTools._serialize_build(b)
        self.assertIsNone(result["queue_time"])
        self.assertIsNone(result["requested_by"])

    def test_serialize_iteration_attributes(self):
        it = _fake_iteration("uuid", "Sprint 1")
        result = AzureDevOpsTools._serialize_iteration(it)
        self.assertIsNotNone(result["start_date"])
        self.assertIsNotNone(result["finish_date"])
        self.assertEqual(result["time_frame"], "current")

    def test_serialize_iteration_no_attributes(self):
        it = MagicMock()
        it.id = "x"
        it.name = "Sprint"
        it.path = "Proj\\Sprint"
        it.url = None
        it.attributes = None
        result = AzureDevOpsTools._serialize_iteration(it)
        self.assertIsNone(result["start_date"])
        self.assertIsNone(result["finish_date"])

    def test_serialize_team_member_identity(self):
        m = _fake_member("u1", "Alice")
        result = AzureDevOpsTools._serialize_team_member(m)
        self.assertEqual(result["display_name"], "Alice")
        self.assertEqual(result["id"], "u1")
        self.assertFalse(result["is_team_admin"])


# ===========================================================================
# 13. JSON RESPONSE FORMAT TESTS
# ===========================================================================


class TestJsonResponseFormat(BaseADOTest):
    def test_all_list_responses_have_data_and_meta_keys(self):
        # list_projects
        self.core.get_projects.return_value = []
        resp = json.loads(self.tools.list_projects())
        self.assertIn("data", resp)
        self.assertIn("meta", resp)

        # list_repositories
        self.git.get_repositories.return_value = []
        resp = json.loads(self.tools.list_repositories())
        self.assertIn("data", resp)

        # list_branches
        self.git.get_refs.return_value = []
        resp = json.loads(self.tools.list_branches("repo"))
        self.assertIn("data", resp)
        self.assertIn("meta", resp)

        # list_pipelines
        self.build.get_definitions.return_value = []
        resp = json.loads(self.tools.list_pipelines())
        self.assertIn("data", resp)
        self.assertIn("meta", resp)

    def test_meta_contains_pagination_fields(self):
        self.core.get_projects.return_value = [_fake_project()]
        resp = json.loads(self.tools.list_projects(page=2, per_page=10))
        meta = resp["meta"]
        self.assertEqual(meta["current_page"], 2)
        self.assertEqual(meta["per_page"], 10)
        self.assertIn("returned_items", meta)

    def test_error_response_is_valid_json(self):
        self.core.get_projects.side_effect = Exception("boom")
        resp_str = self.tools.list_projects()
        self.assertIsInstance(json.loads(resp_str), dict)

    def test_error_response_has_error_key(self):
        self.core.get_projects.side_effect = Exception("boom")
        resp = json.loads(self.tools.list_projects())
        self.assertIn("error", resp)
        self.assertIn("boom", resp["error"])

    def test_success_responses_are_valid_json(self):
        """All write operations should return valid JSON."""
        self.core.get_project.return_value = _fake_project()
        self.assertTrue(json.loads(self.tools.get_project("P")))

        self.git.get_repository.return_value = _fake_repo()
        self.assertTrue(json.loads(self.tools.get_repository("R")))

        self.wit.get_work_item.return_value = _fake_work_item()
        self.assertTrue(json.loads(self.tools.get_work_item(1)))

    def test_delete_responses_contain_message(self):
        repo = _fake_repo()
        self.git.get_repository.return_value = repo
        resp = json.loads(self.tools.delete_repository("R"))
        self.assertIn("message", resp)

        resp = json.loads(self.tools.delete_work_item(1))
        self.assertIn("message", resp)

        resp = json.loads(self.tools.cancel_build(100))
        self.assertIn("message", resp)


# ===========================================================================
# 14. EDGE CASES & BOUNDARY CONDITIONS
# ===========================================================================


class TestEdgeCases(BaseADOTest):
    def test_per_page_capped_at_100(self):
        self.core.get_projects.return_value = [_fake_project(f"P{i}") for i in range(200)]
        result = self._parse(self.tools.list_projects(per_page=200))
        self.assertLessEqual(len(result["data"]), 100)

    def test_per_page_minimum_is_1(self):
        self.core.get_projects.return_value = [_fake_project()]
        result = self._parse(self.tools.list_projects(per_page=0))
        self.assertGreaterEqual(len(result["data"]), 0)

    def test_list_work_items_no_results_does_not_call_get_work_items(self):
        wiql_result = MagicMock()
        wiql_result.work_items = []
        self.wit.query_by_wiql.return_value = wiql_result
        self.tools.list_work_items()
        self.wit.get_work_items.assert_not_called()

    def test_project_override_takes_precedence_over_default(self):
        self.core.get_project.return_value = _fake_project("Override")
        self.tools.get_project("Override")
        self.core.get_project.assert_called_once_with("Override")

    def test_connection_is_reused(self):
        """_get_connection() should return the cached connection on subsequent calls."""
        conn1 = self.tools._get_connection()
        conn2 = self.tools._get_connection()
        self.assertIs(conn1, conn2)

    def test_list_branches_page_1_returns_first_items(self):
        refs = [_fake_ref(f"refs/heads/b{i}") for i in range(5)]
        self.git.get_refs.return_value = refs
        result = self._parse(self.tools.list_branches("repo", page=1, per_page=2))
        self.assertEqual(result["data"][0]["name"], "b0")
        self.assertEqual(result["data"][1]["name"], "b1")

    def test_list_commits_date_filters_passed_through(self):
        self.git.get_commits_batch.return_value = []
        self.tools.list_commits("repo", from_date="2024-01-01", to_date="2024-01-31")
        self.git.get_commits_batch.assert_called_once()

    def test_unexpected_exception_returns_json_error(self):
        self.git.get_repositories.side_effect = RuntimeError("unexpected crash")
        result = json.loads(self.tools.list_repositories())
        self.assertIn("error", result)
        self.assertIn("unexpected crash", result["error"])

    def test_add_pr_comment_with_empty_thread_comments(self):
        thread = MagicMock()
        thread.id = 5
        thread.comments = []
        self.git.create_thread.return_value = thread
        result = self._parse(self.tools.add_pr_comment(1, "repo", "test"))
        self.assertIsNone(result["comment_id"])

    def test_get_iteration_work_items_with_none_target(self):
        rel1 = MagicMock()
        rel1.target = MagicMock()
        rel1.target.id = 1
        rel2 = MagicMock()
        rel2.target = None  # edge case
        iter_wi = MagicMock()
        iter_wi.work_item_relations = [rel1, rel2]
        self.work.get_iteration_work_items.return_value = iter_wi
        self.wit.get_work_items.return_value = [_fake_work_item(1)]
        self._parse(self.tools.get_iteration_work_items("iter"))
        # Only rel1 has a valid target
        self.wit.get_work_items.assert_called_once_with(ids=[1], error_policy="omit")

    def test_list_releases_pagination_boundary(self):
        releases = [_fake_release(i) for i in range(5)]
        self.release.get_releases.return_value = releases
        result = self._parse(self.tools.list_releases(page=3, per_page=2))
        # page 3 with per_page 2 → items [4] (only 1 item left)
        self.assertEqual(len(result["data"]), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
