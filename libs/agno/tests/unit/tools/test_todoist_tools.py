"""Unit tests for TodoistTools class."""

import json
from unittest.mock import Mock, patch

import pytest

from agno.tools.todoist import TodoistTools


@pytest.fixture
def mock_todoist_api():
    """Create a mock Todoist API client."""
    with patch("agno.tools.todoist.TodoistAPI") as mock_api:
        mock_client = Mock()
        mock_api.return_value = mock_client
        return mock_client


@pytest.fixture
def todoist_tools(mock_todoist_api):
    """Create TodoistTools instance with mocked API."""
    with patch.dict("os.environ", {"TODOIST_API_TOKEN": "test_token"}):
        tools = TodoistTools()
        tools.api = mock_todoist_api
        return tools


def test_init_with_api_token():
    """Test initialization with provided API token."""
    with patch("agno.tools.todoist.TodoistAPI") as mock_api:
        with patch("os.getenv") as mock_getenv:
            mock_getenv.return_value = "test_token"
            TodoistTools()
            mock_api.assert_called_once_with("test_token")


def test_init_with_env_var():
    """Test initialization with environment variable."""
    with patch("agno.tools.todoist.TodoistAPI") as mock_api:
        with patch("os.getenv") as mock_getenv:
            mock_getenv.return_value = "env_token"
            TodoistTools()
            mock_api.assert_called_once_with("env_token")


def test_init_without_token():
    """Test initialization without API token."""
    with patch.dict("os.environ", clear=True):
        with pytest.raises(ValueError, match="TODOIST_API_TOKEN not set"):
            TodoistTools()


def test_init_with_selective_tools():
    """Test initialization with only selected tools."""
    with patch.dict("os.environ", {"TODOIST_API_TOKEN": "test_token"}):
        tools = TodoistTools(
            create_task=True,
            get_task=False,
            update_task=True,
            close_task=False,
            delete_task=False,
            get_active_tasks=True,
            get_projects=False,
        )

        assert "create_task" in [func.name for func in tools.functions.values()]
        assert "get_task" not in [func.name for func in tools.functions.values()]
        assert "update_task" in [func.name for func in tools.functions.values()]
        assert "close_task" not in [func.name for func in tools.functions.values()]


def test_create_task_success(todoist_tools, mock_todoist_api):
    """Test successful task creation."""
    mock_task = Mock()
    mock_task.id = "123"
    mock_task.content = "Test Task"
    mock_task.description = "Test Description"
    mock_task.project_id = "project_1"
    mock_task.section_id = "section_1"
    mock_task.parent_id = None
    mock_task.order = 1
    mock_task.priority = 4
    mock_task.url = "https://todoist.com/task/123"
    mock_task.comment_count = 0
    mock_task.creator_id = "user_1"
    mock_task.created_at = "2024-01-01T10:00:00Z"
    mock_task.labels = ["test_label"]
    mock_task.due = Mock(date="2024-01-02", string="tomorrow at 10:00", datetime="2024-01-02T10:00:00Z", timezone="UTC")

    mock_todoist_api.add_task.return_value = mock_task

    result = todoist_tools.create_task(
        content="Test Task", project_id="project_1", due_string="tomorrow at 10:00", priority=4, labels=["test_label"]
    )

    result_data = json.loads(result)
    assert result_data["id"] == "123"
    assert result_data["content"] == "Test Task"
    assert result_data["priority"] == 4
    assert result_data["due"]["string"] == "tomorrow at 10:00"


def test_get_task_success(todoist_tools, mock_todoist_api):
    """Test successful task retrieval."""
    mock_task = Mock()
    mock_task.id = "123"
    mock_task.content = "Test Task"
    mock_task.description = "Test Description"
    mock_task.project_id = "project_1"
    mock_task.section_id = None
    mock_task.parent_id = None
    mock_task.order = 1
    mock_task.priority = 1
    mock_task.url = "https://todoist.com/task/123"
    mock_task.comment_count = 0
    mock_task.creator_id = "user_1"
    mock_task.created_at = "2024-01-01T10:00:00Z"
    mock_task.labels = []
    mock_task.due = None

    mock_todoist_api.get_task.return_value = mock_task

    result = todoist_tools.get_task("123")
    result_data = json.loads(result)

    assert result_data["id"] == "123"
    mock_todoist_api.get_task.assert_called_once_with("123")


def test_update_task_success(todoist_tools, mock_todoist_api):
    """Test successful task update."""
    mock_todoist_api.update_task.return_value = True

    result = todoist_tools.update_task("123", content="Updated Task")
    result_data = json.loads(result)

    assert result_data["success"] is True
    mock_todoist_api.update_task.assert_called_once_with(task_id="123", content="Updated Task")


def test_close_task_success(todoist_tools, mock_todoist_api):
    """Test successful task closure."""
    mock_todoist_api.complete_task.return_value = True

    result = todoist_tools.close_task("123")
    result_data = json.loads(result)

    assert result_data["success"] is True
    mock_todoist_api.complete_task.assert_called_once_with("123")


def test_delete_task_success(todoist_tools, mock_todoist_api):
    """Test successful task deletion."""
    mock_todoist_api.delete_task.return_value = True

    result = todoist_tools.delete_task("123")
    result_data = json.loads(result)

    assert result_data["success"] is True
    mock_todoist_api.delete_task.assert_called_once_with("123")


def test_get_active_tasks_success(todoist_tools, mock_todoist_api):
    """Test successful retrieval of active tasks."""
    mock_task1 = Mock()
    mock_task1.id = "123"
    mock_task1.content = "Task 1"
    mock_task1.description = "Description 1"
    mock_task1.project_id = "project_1"
    mock_task1.section_id = None
    mock_task1.parent_id = None
    mock_task1.order = 1
    mock_task1.priority = 1
    mock_task1.url = "https://todoist.com/task/123"
    mock_task1.comment_count = 0
    mock_task1.creator_id = "user_1"
    mock_task1.created_at = "2024-01-01T10:00:00Z"
    mock_task1.labels = []
    mock_task1.due = None

    mock_task2 = Mock()
    mock_task2.id = "456"
    mock_task2.content = "Task 2"
    mock_task2.description = "Description 2"
    mock_task2.project_id = "project_1"
    mock_task2.section_id = None
    mock_task2.parent_id = None
    mock_task2.order = 1
    mock_task2.priority = 1
    mock_task2.url = "https://todoist.com/task/456"
    mock_task2.comment_count = 0
    mock_task2.creator_id = "user_1"
    mock_task2.created_at = "2024-01-01T10:00:00Z"
    mock_task2.labels = []
    mock_task2.due = None

    mock_todoist_api.get_tasks.return_value = [mock_task1, mock_task2]

    result = todoist_tools.get_active_tasks()
    result_data = json.loads(result)

    assert len(result_data) == 2
    assert result_data[0]["id"] == "123"
    assert result_data[1]["id"] == "456"


def test_get_projects_success(todoist_tools, mock_todoist_api):
    """Test successful retrieval of projects."""
    mock_project1 = Mock()
    mock_project1.__dict__ = {"id": "1", "name": "Project 1"}
    mock_project2 = Mock()
    mock_project2.__dict__ = {"id": "2", "name": "Project 2"}

    mock_todoist_api.get_projects.return_value = [mock_project1, mock_project2]

    result = todoist_tools.get_projects()
    result_data = json.loads(result)

    assert len(result_data) == 2
    assert result_data[0]["id"] == "1"
    assert result_data[1]["name"] == "Project 2"


def test_error_handling(todoist_tools, mock_todoist_api):
    """Test error handling in various methods."""
    mock_todoist_api.add_task.side_effect = Exception("API Error")
    result = todoist_tools.create_task(content="Test Task")
    assert json.loads(result)["error"] == "API Error"

    mock_todoist_api.get_task.side_effect = Exception("Not Found")
    result = todoist_tools.get_task("123")
    assert json.loads(result)["error"] == "Not Found"

    mock_todoist_api.get_tasks.side_effect = Exception("API Error")
    result = todoist_tools.get_active_tasks()
    assert json.loads(result)["error"] == "API Error"


def test_create_task_with_due_date(todoist_tools, mock_todoist_api):
    """Test creating a task with due date."""
    mock_due = Mock()
    mock_due.date = "2024-01-02"
    mock_due.string = "tomorrow at 10:00"
    mock_due.datetime = "2024-01-02T10:00:00Z"
    mock_due.timezone = "UTC"

    mock_task = Mock()
    mock_task.id = "123"
    mock_task.content = "Test Task"
    mock_task.description = None
    mock_task.project_id = None
    mock_task.section_id = None
    mock_task.parent_id = None
    mock_task.order = 1
    mock_task.priority = 1
    mock_task.url = "https://todoist.com/task/123"
    mock_task.comment_count = 0
    mock_task.creator_id = "user_1"
    mock_task.created_at = "2024-01-01T10:00:00Z"
    mock_task.labels = []
    mock_task.due = mock_due

    mock_todoist_api.add_task.return_value = mock_task

    result = todoist_tools.create_task(content="Test Task", due_string="tomorrow at 10:00")

    result_data = json.loads(result)
    assert result_data["due"]["date"] == "2024-01-02"
    assert result_data["due"]["string"] == "tomorrow at 10:00"


def test_create_task_with_labels(todoist_tools, mock_todoist_api):
    """Test creating a task with labels."""
    mock_task = Mock()
    mock_task.id = "123"
    mock_task.content = "Test Task"
    mock_task.description = None
    mock_task.project_id = None
    mock_task.section_id = None
    mock_task.parent_id = None
    mock_task.order = 1
    mock_task.priority = 1
    mock_task.url = "https://todoist.com/task/123"
    mock_task.comment_count = 0
    mock_task.creator_id = "user_1"
    mock_task.created_at = "2024-01-01T10:00:00Z"
    mock_task.labels = ["work", "important"]
    mock_task.due = None

    mock_todoist_api.add_task.return_value = mock_task

    result = todoist_tools.create_task(content="Test Task", labels=["work", "important"])

    result_data = json.loads(result)
    assert "work" in result_data["labels"]
    assert "important" in result_data["labels"]
