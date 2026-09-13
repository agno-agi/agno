"""Unit tests for RedmineTools class."""

import json
from unittest.mock import MagicMock, patch

import pytest
from redminelib.exceptions import ResourceNotFoundError

from agno.tools.redmine import RedmineTools


def _named(name):
    """Build a mock Redmine resource whose str() returns the given name."""
    resource = MagicMock()
    resource.__str__.return_value = name
    return resource


def _resource(name, resource_id):
    """Build a mock Redmine resource exposing .name and .id (trackers, statuses, priorities)."""
    resource = MagicMock()
    resource.name = name
    resource.id = resource_id
    return resource


def _journal(notes):
    """Build a mock Redmine journal (comment) carrying the given notes."""
    journal = MagicMock()
    journal.notes = notes
    return journal


def _issue(issue_id=1, subject="Test issue", assignee=None):
    """Build a mock Redmine issue with sensible defaults for serialization tests."""
    issue = MagicMock()
    issue.id = issue_id
    issue.subject = subject
    issue.description = "A description"
    issue.project = _named("Website")
    issue.tracker = _named("Feature")
    issue.status = _named("New")
    issue.priority = _named("Normal")
    issue.author = _named("Redmine Admin")
    issue.assigned_to = _named(assignee) if assignee else None
    issue.done_ratio = 0
    issue.fixed_version = None
    issue.parent = None
    issue.estimated_hours = None
    issue.journals = []
    return issue


@pytest.fixture
def mock_redmine():
    """Create a mock Redmine client."""
    trackers = [_resource("Bug", 1), _resource("Feature", 2), _resource("Support", 3)]
    statuses = [_resource("New", 1), _resource("In Progress", 2), _resource("Closed", 5)]
    priorities = [_resource("Low", 1), _resource("Normal", 2), _resource("High", 3)]
    activities = [_resource("Design", 8), _resource("Development", 9)]
    for activity in activities:
        activity.is_default = False
    with patch("agno.tools.redmine.Redmine") as mock_redmine_class:
        mock_client = MagicMock()
        mock_client.tracker.all.return_value = trackers
        mock_client.issue_status.all.return_value = statuses
        mock_client.enumeration.filter.side_effect = lambda resource: (
            priorities if resource == "issue_priorities" else activities
        )
        mock_redmine_class.return_value = mock_client
        yield mock_client


@pytest.fixture
def redmine_tools(mock_redmine):
    """Create RedmineTools instance with mocked dependencies."""
    with patch.dict(
        "os.environ",
        {
            "REDMINE_SERVER_URL": "https://redmine.example.com",
            "REDMINE_TOKEN": "test_token",
        },
    ):
        tools = RedmineTools()
        tools.redmine = mock_redmine
        return tools


# Initialization Tests
def test_init_with_token():
    """Test initialization with an API token."""
    with (
        patch.dict(
            "os.environ",
            {"REDMINE_SERVER_URL": "https://redmine.example.com", "REDMINE_TOKEN": "test_token"},
        ),
        patch("agno.tools.redmine.Redmine") as mock_redmine_class,
    ):
        tools = RedmineTools()
        assert tools.server_url == "https://redmine.example.com"
        assert tools.token == "test_token"
        mock_redmine_class.assert_called_once_with(
            url="https://redmine.example.com", key="test_token", raise_attr_exception=False
        )


def test_init_with_username_password():
    """Test initialization with username and password."""
    with (
        patch.dict("os.environ", {}, clear=True),
        patch("agno.tools.redmine.Redmine") as mock_redmine_class,
    ):
        RedmineTools(server_url="https://redmine.example.com", username="user", password="pass")
        mock_redmine_class.assert_called_once_with(
            url="https://redmine.example.com", username="user", password="pass", raise_attr_exception=False
        )


def test_init_without_server_url_raises():
    """Test that a missing server url raises a ValueError."""
    with patch.dict("os.environ", {}, clear=True):
        with pytest.raises(ValueError, match="server URL not provided"):
            RedmineTools()


def test_enable_flags_register_selected_tools():
    """Test that enable_* flags only register the requested tools."""
    with patch("agno.tools.redmine.Redmine"):
        tools = RedmineTools(
            server_url="https://redmine.example.com",
            enable_get_issue=True,
            enable_create_issue=False,
            enable_update_issue=False,
            enable_search_issues=False,
            enable_add_comment=False,
            enable_log_time=False,
            enable_list_projects=False,
            enable_list_users=False,
            enable_list_project_members=False,
            enable_list_versions=False,
        )
        registered = {func.name for func in tools.functions.values()}
        assert registered == {"get_issue"}


def test_all_flag_registers_every_tool():
    """Test that all=True registers every tool."""
    with patch("agno.tools.redmine.Redmine"):
        tools = RedmineTools(server_url="https://redmine.example.com", all=True)
        registered = {func.name for func in tools.functions.values()}
        assert registered == {
            "get_issue",
            "create_issue",
            "update_issue",
            "search_issues",
            "add_comment",
            "log_time",
            "list_projects",
            "list_users",
            "list_project_members",
            "list_versions",
        }


# get_issue Tests
def test_get_issue_success(redmine_tools, mock_redmine):
    """Test retrieving an issue returns serialized primitives as a JSON string."""
    mock_redmine.issue.get.return_value = _issue(issue_id=1, subject="Implement search")
    result = redmine_tools.get_issue("1")
    assert isinstance(result, str)
    data = json.loads(result)
    assert data["id"] == 1
    assert data["project"] == "Website"
    assert data["tracker"] == "Feature"
    assert data["assignee"] == "Unassigned"
    assert data["subject"] == "Implement search"
    assert "comments" not in data
    mock_redmine.issue.get.assert_called_once_with(1)


def test_get_issue_returns_planning_fields(redmine_tools, mock_redmine):
    """Test that version, parent id and estimated hours are returned in the issue details."""
    issue = _issue(issue_id=1)
    issue.fixed_version = _named("Sprint 1")
    issue.parent = MagicMock(id=44)
    issue.estimated_hours = 6.0
    mock_redmine.issue.get.return_value = issue
    data = json.loads(redmine_tools.get_issue("1"))
    assert data["version"] == "Sprint 1"
    assert data["parent_id"] == 44
    assert data["estimated_hours"] == 6.0


def test_get_issue_include_comments(redmine_tools, mock_redmine):
    """Test that include_comments requests journals and returns non-empty notes."""
    issue = _issue(issue_id=1)
    issue.journals = [_journal("first note"), _journal(""), _journal("second note")]
    mock_redmine.issue.get.return_value = issue
    result = redmine_tools.get_issue("1", include_comments=True)
    data = json.loads(result)
    assert data["comments"] == ["first note", "second note"]
    mock_redmine.issue.get.assert_called_once_with(1, include="journals")


def test_get_issue_invalid_id(redmine_tools, mock_redmine):
    """Test that a non-numeric id returns a clean JSON error, not a raw Python message."""
    result = redmine_tools.get_issue("abc")
    data = json.loads(result)
    assert data["error"] == "Invalid issue id: 'abc'"
    mock_redmine.issue.get.assert_not_called()


def test_get_issue_not_found(redmine_tools, mock_redmine):
    """Test that a missing issue returns a JSON error rather than raising."""
    mock_redmine.issue.get.side_effect = ResourceNotFoundError()
    result = redmine_tools.get_issue("999")
    data = json.loads(result)
    assert "error" in data


# create_issue Tests
def test_create_issue_resolves_tracker_and_priority(redmine_tools, mock_redmine):
    """Test that tracker and priority names are resolved to ids regardless of locale."""
    mock_redmine.issue.create.return_value = MagicMock(id=42)
    result = redmine_tools.create_issue("website", "Login broken", "fix it", tracker="Bug", priority="High")
    data = json.loads(result)
    assert data["id"] == 42
    assert data["url"] == "https://redmine.example.com/issues/42"
    _, kwargs = mock_redmine.issue.create.call_args
    assert kwargs["tracker_id"] == 1
    assert kwargs["priority_id"] == 3
    assert "assigned_to_id" not in kwargs


def test_create_issue_unknown_tracker(redmine_tools, mock_redmine):
    """Test that an unknown tracker name returns a helpful error listing valid trackers."""
    result = redmine_tools.create_issue("website", "x", "y", tracker="Nonexistent")
    data = json.loads(result)
    assert "Unknown tracker" in data["error"]
    mock_redmine.issue.create.assert_not_called()


def test_create_issue_without_tracker_or_assignee(redmine_tools, mock_redmine):
    """Test that a minimal issue can be created without a tracker or assignee."""
    mock_redmine.issue.create.return_value = MagicMock(id=7)
    result = redmine_tools.create_issue("website", "Minimal", "desc")
    data = json.loads(result)
    assert data["id"] == 7
    _, kwargs = mock_redmine.issue.create.call_args
    assert "tracker_id" not in kwargs
    assert "assigned_to_id" not in kwargs


def test_create_issue_with_dates(redmine_tools, mock_redmine):
    """Test that start and due dates are passed through to the created issue."""
    mock_redmine.issue.create.return_value = MagicMock(id=9)
    redmine_tools.create_issue("website", "Dated", "desc", start_date="2026-08-01", due_date="2026-08-15")
    _, kwargs = mock_redmine.issue.create.call_args
    assert kwargs["start_date"] == "2026-08-01"
    assert kwargs["due_date"] == "2026-08-15"


def test_create_issue_with_planning_fields(redmine_tools, mock_redmine):
    """Test that version, parent (subtask) and estimated hours are passed through."""
    mock_redmine.issue.create.return_value = MagicMock(id=9)
    redmine_tools.create_issue("website", "Subtask", "desc", version_id=1, parent_issue_id=44, estimated_hours=6.0)
    _, kwargs = mock_redmine.issue.create.call_args
    assert kwargs["fixed_version_id"] == 1
    assert kwargs["parent_issue_id"] == 44
    assert kwargs["estimated_hours"] == 6.0


# update_issue Tests
def test_update_issue_resolves_status_and_priority(redmine_tools, mock_redmine):
    """Test that update resolves status/priority names and passes through numeric fields."""
    result = redmine_tools.update_issue("5", status="In Progress", priority="High", done_ratio=40)
    data = json.loads(result)
    assert data["status"] == "success"
    args, kwargs = mock_redmine.issue.update.call_args
    assert args[0] == 5
    assert kwargs["status_id"] == 2
    assert kwargs["priority_id"] == 3
    assert kwargs["done_ratio"] == 40


def test_update_issue_planning_fields(redmine_tools, mock_redmine):
    """Test that update passes version, parent and estimated hours through."""
    redmine_tools.update_issue("5", version_id=1, parent_issue_id=44, estimated_hours=10.0)
    _, kwargs = mock_redmine.issue.update.call_args
    assert kwargs["fixed_version_id"] == 1
    assert kwargs["parent_issue_id"] == 44
    assert kwargs["estimated_hours"] == 10.0


def test_update_issue_unknown_status(redmine_tools, mock_redmine):
    """Test that an unknown status returns a helpful error and does not update."""
    result = redmine_tools.update_issue("5", status="Bogus")
    data = json.loads(result)
    assert "Unknown status" in data["error"]
    mock_redmine.issue.update.assert_not_called()


def test_update_issue_no_fields(redmine_tools, mock_redmine):
    """Test that updating with no fields returns an error and does not call the API."""
    result = redmine_tools.update_issue("5")
    data = json.loads(result)
    assert "No fields" in data["error"]
    mock_redmine.issue.update.assert_not_called()


# search_issues Tests
def test_search_issues_success(redmine_tools, mock_redmine):
    """Test that search serializes results, including unassigned issues, as a JSON string."""
    mock_redmine.issue.filter.return_value = [
        _issue(issue_id=1, subject="Implement search", assignee=None),
        _issue(issue_id=2, subject="Advanced search", assignee="Jane Doe"),
    ]
    result = redmine_tools.search_issues("search")
    data = json.loads(result)
    assert len(data) == 2
    assert data[0]["assignee"] == "Unassigned"
    assert data[1]["assignee"] == "Jane Doe"
    mock_redmine.issue.filter.assert_called_once_with(subject="~search", status_id="*", limit=50)


def test_search_issues_with_filters(redmine_tools, mock_redmine):
    """Test that project, status and assignee filters are passed to the server."""
    mock_redmine.issue.filter.return_value = []
    redmine_tools.search_issues(pattern="bug", project_id="website", status="open", assigned_to_id=5)
    _, kwargs = mock_redmine.issue.filter.call_args
    assert kwargs["subject"] == "~bug"
    assert kwargs["project_id"] == "website"
    assert kwargs["status_id"] == "open"
    assert kwargs["assigned_to_id"] == 5


def test_search_issues_status_name_resolved(redmine_tools, mock_redmine):
    """Test that a named status is resolved to its id in the filter."""
    mock_redmine.issue.filter.return_value = []
    redmine_tools.search_issues(status="In Progress")
    _, kwargs = mock_redmine.issue.filter.call_args
    assert kwargs["status_id"] == 2


def test_search_issues_tracker_filter_and_output(redmine_tools, mock_redmine):
    """Test that a tracker filter is resolved server-side and tracker is returned in results."""
    mock_redmine.issue.filter.return_value = [_issue(issue_id=1, subject="Bug one")]
    result = redmine_tools.search_issues(tracker="Bug")
    _, kwargs = mock_redmine.issue.filter.call_args
    assert kwargs["tracker_id"] == 1
    assert json.loads(result)[0]["tracker"] == "Feature"


def test_search_issues_error_shape_is_dict(redmine_tools, mock_redmine):
    """Test that a search failure returns a dict-shaped error, consistent with other methods."""
    mock_redmine.issue.filter.side_effect = Exception("boom")
    result = redmine_tools.search_issues("x")
    data = json.loads(result)
    assert isinstance(data, dict)
    assert "error" in data


# add_comment Tests
def test_add_comment_success(redmine_tools, mock_redmine):
    """Test adding a comment updates the issue notes and returns success."""
    result = redmine_tools.add_comment("1", "Looks good")
    data = json.loads(result)
    assert data["status"] == "success"
    assert data["issue_id"] == "1"
    mock_redmine.issue.update.assert_called_once_with(1, notes="Looks good", private_notes=False)


def test_add_comment_private(redmine_tools, mock_redmine):
    """Test that a private comment is flagged as a private note."""
    redmine_tools.add_comment("1", "internal only", private_notes=True)
    mock_redmine.issue.update.assert_called_once_with(1, notes="internal only", private_notes=True)


def test_add_comment_empty_is_rejected(redmine_tools, mock_redmine):
    """Test that a blank comment is rejected instead of reporting a false success."""
    for blank in ("", "   "):
        result = redmine_tools.add_comment("1", blank)
        data = json.loads(result)
        assert data["error"] == "comment cannot be empty"
    mock_redmine.issue.update.assert_not_called()


def test_add_comment_error(redmine_tools, mock_redmine):
    """Test that a failed comment update returns a JSON error."""
    mock_redmine.issue.update.side_effect = ResourceNotFoundError()
    result = redmine_tools.add_comment("999", "ghost")
    data = json.loads(result)
    assert "error" in data


# log_time Tests
def test_log_time_success(redmine_tools, mock_redmine):
    """Test that logging time resolves the activity name and passes fields through."""
    mock_redmine.time_entry.create.return_value = MagicMock(id=5)
    result = redmine_tools.log_time("1", 2.5, activity="Development", comment="coding", spent_on="2026-07-12")
    data = json.loads(result)
    assert data["id"] == 5
    assert data["hours"] == 2.5
    _, kwargs = mock_redmine.time_entry.create.call_args
    assert kwargs["issue_id"] == 1
    assert kwargs["hours"] == 2.5
    assert kwargs["activity_id"] == 9
    assert kwargs["comments"] == "coding"
    assert kwargs["spent_on"] == "2026-07-12"


def test_log_time_unknown_activity(redmine_tools, mock_redmine):
    """Test that an unknown activity name returns a helpful error and logs nothing."""
    result = redmine_tools.log_time("1", 1.0, activity="Nonexistent")
    data = json.loads(result)
    assert "Unknown activity" in data["error"]
    mock_redmine.time_entry.create.assert_not_called()


def test_log_time_requires_activity_without_default(redmine_tools, mock_redmine):
    """Test that omitting the activity on an instance with no default returns a helpful error."""
    result = redmine_tools.log_time("1", 2.0)
    data = json.loads(result)
    assert "activity is required" in data["error"]
    assert "design" in data["error"]
    mock_redmine.time_entry.create.assert_not_called()


def test_log_time_rejects_non_positive_hours(redmine_tools, mock_redmine):
    """Test that zero or negative hours are rejected before any API call."""
    for bad in (0, -3):
        result = redmine_tools.log_time("1", bad, activity="Design")
        assert json.loads(result)["error"] == "hours must be greater than 0"
    mock_redmine.time_entry.create.assert_not_called()


# List Tests
def test_list_projects(redmine_tools, mock_redmine):
    """Test that projects are listed with id, identifier and name."""
    project = MagicMock()
    project.id, project.identifier, project.name = 2, "website", "Website"
    mock_redmine.project.all.return_value = [project]
    data = json.loads(redmine_tools.list_projects())
    assert data == [{"id": 2, "identifier": "website", "name": "Website"}]


def test_list_users(redmine_tools, mock_redmine):
    """Test that users are listed with id, name and login for assignee resolution."""
    user = MagicMock()
    user.id, user.firstname, user.lastname, user.login = 5, "Laura", "Melo", "laura"
    mock_redmine.user.all.return_value = [user]
    data = json.loads(redmine_tools.list_users())
    assert data == [{"id": 5, "name": "Laura Melo", "login": "laura"}]


def test_list_project_members(redmine_tools, mock_redmine):
    """Test that project members are listed, skipping group memberships without a user."""
    user_membership = MagicMock()
    user_membership.user = _named("Laura Melo")
    user_membership.user.id = 5
    group_membership = MagicMock()
    group_membership.user = None
    mock_redmine.project_membership.filter.return_value = [user_membership, group_membership]
    data = json.loads(redmine_tools.list_project_members("website"))
    assert data == [{"id": 5, "name": "Laura Melo"}]
    mock_redmine.project_membership.filter.assert_called_once_with(project_id="website")


def test_list_versions(redmine_tools, mock_redmine):
    """Test that project versions (sprints/milestones) are listed for id resolution."""
    version = MagicMock()
    version.id, version.name, version.status = 1, "Sprint 1", "open"
    mock_redmine.version.filter.return_value = [version]
    data = json.loads(redmine_tools.list_versions("website"))
    assert data == [{"id": 1, "name": "Sprint 1", "status": "open"}]
    mock_redmine.version.filter.assert_called_once_with(project_id="website")
