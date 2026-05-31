"""Unit tests for Google Tasks Tools."""

import json
from unittest.mock import MagicMock, Mock, patch

import pytest
from google.oauth2.credentials import Credentials
from googleapiclient.errors import HttpError

from agno.tools.google.tasks import GoogleTasksTools


@pytest.fixture
def mock_credentials():
    mock_creds = Mock(spec=Credentials)
    mock_creds.valid = True
    mock_creds.expired = False
    mock_creds.to_json.return_value = '{"token": "test_token"}'
    return mock_creds


@pytest.fixture
def mock_tasks_service():
    return MagicMock()


@pytest.fixture
def tasks_tools(mock_credentials, mock_tasks_service):
    with (
        patch("agno.tools.google.tasks.build") as mock_build,
        patch("agno.tools.google.tasks.authenticate", lambda func: func),
    ):
        mock_build.return_value = mock_tasks_service
        tools = GoogleTasksTools()
        tools.creds = mock_credentials
        tools.service = mock_tasks_service
        return tools


@pytest.fixture
def tasks_tools_all(mock_credentials, mock_tasks_service):
    """Instance with ALL tools enabled including destructive ones."""
    with (
        patch("agno.tools.google.tasks.build") as mock_build,
        patch("agno.tools.google.tasks.authenticate", lambda func: func),
    ):
        mock_build.return_value = mock_tasks_service
        tools = GoogleTasksTools(
            delete_task_list=True,
            delete_task=True,
            clear_completed_tasks=True,
        )
        tools.creds = mock_credentials
        tools.service = mock_tasks_service
        return tools


def _http_error(status: int, reason: str) -> HttpError:
    response = Mock()
    response.status = status
    response.reason = reason
    return HttpError(response, b'{"error": {"message": "' + reason.encode() + b'"}}')


class TestGoogleTasksToolsInitialization:
    def test_init_defaults(self):
        tools = GoogleTasksTools()
        assert tools.creds is None
        assert tools.service is None
        assert tools.scopes == GoogleTasksTools.DEFAULT_SCOPES
        assert tools.token_path == "token.json"
        assert tools.oauth_port == 8080

    def test_init_default_tools_registered(self):
        tools = GoogleTasksTools()
        tool_names = [func.name for func in tools.functions.values()]
        expected_defaults = [
            "list_task_lists",
            "get_task_list",
            "list_tasks",
            "get_task",
            "create_task_list",
            "update_task_list",
            "create_task",
            "update_task",
            "complete_task",
            "move_task",
        ]
        for name in expected_defaults:
            assert name in tool_names, f"{name} should be registered by default"
        # Destructive tools are opt-in only
        assert "delete_task_list" not in tool_names
        assert "delete_task" not in tool_names
        assert "clear_completed_tasks" not in tool_names

    def test_init_all_tools_registered(self):
        tools = GoogleTasksTools(
            delete_task_list=True,
            delete_task=True,
            clear_completed_tasks=True,
        )
        tool_names = [func.name for func in tools.functions.values()]
        assert len(tool_names) == 13
        assert "delete_task_list" in tool_names
        assert "delete_task" in tool_names
        assert "clear_completed_tasks" in tool_names

    def test_init_selective_tools(self):
        tools = GoogleTasksTools(
            list_task_lists=True,
            get_task_list=False,
            list_tasks=True,
            get_task=False,
            create_task_list=False,
            update_task_list=False,
            create_task=False,
            update_task=False,
            complete_task=False,
            move_task=False,
        )
        tool_names = [func.name for func in tools.functions.values()]
        assert tool_names == ["list_task_lists", "list_tasks"]

    def test_init_service_account_params(self):
        tools = GoogleTasksTools(
            service_account_path="/path/to/key.json",
            delegated_user="user@example.com",
        )
        assert tools.service_account_path == "/path/to/key.json"
        assert tools.delegated_user == "user@example.com"

    def test_init_login_hint(self):
        tools = GoogleTasksTools(login_hint="user@example.com")
        assert tools.login_hint == "user@example.com"


class TestScopeValidation:
    def test_default_scopes(self):
        tools = GoogleTasksTools()
        assert tools.scopes == GoogleTasksTools.DEFAULT_SCOPES

    def test_custom_scopes_write_validated(self):
        with pytest.raises(ValueError, match="required for write operations"):
            GoogleTasksTools(
                scopes=["https://www.googleapis.com/auth/tasks.readonly"],
                create_task=True,
            )

    def test_read_only_mode_passes(self):
        tools = GoogleTasksTools(
            scopes=["https://www.googleapis.com/auth/tasks.readonly"],
            create_task_list=False,
            update_task_list=False,
            create_task=False,
            update_task=False,
            complete_task=False,
            move_task=False,
        )
        tool_names = [func.name for func in tools.functions.values()]
        assert tool_names == ["list_task_lists", "get_task_list", "list_tasks", "get_task"]

    def test_custom_scopes_read_validated(self):
        with pytest.raises(ValueError, match="required for read operations"):
            GoogleTasksTools(
                scopes=["https://www.googleapis.com/auth/other"],
                list_task_lists=True,
                get_task_list=False,
                list_tasks=False,
                get_task=False,
                create_task_list=False,
                update_task_list=False,
                create_task=False,
                update_task=False,
                complete_task=False,
                move_task=False,
            )

    def test_write_scope_covers_reads(self):
        tools = GoogleTasksTools(scopes=["https://www.googleapis.com/auth/tasks"])
        assert tools.scopes == ["https://www.googleapis.com/auth/tasks"]


class TestListTaskLists:
    def test_list_task_lists_success(self, tasks_tools, mock_tasks_service):
        mock_lists = [
            {"id": "list1", "title": "Work", "kind": "tasks#taskList"},
            {"id": "list2", "title": "Personal", "kind": "tasks#taskList"},
        ]
        mock_tasks_service.tasklists().list().execute.return_value = {"items": mock_lists}

        result = tasks_tools.list_task_lists()
        assert json.loads(result) == mock_lists

    def test_list_task_lists_empty(self, tasks_tools, mock_tasks_service):
        mock_tasks_service.tasklists().list().execute.return_value = {"items": []}
        result = tasks_tools.list_task_lists()
        assert json.loads(result) == {"message": "No task lists found."}

    def test_list_task_lists_http_error(self, tasks_tools, mock_tasks_service):
        mock_tasks_service.tasklists().list().execute.side_effect = _http_error(403, "Forbidden")
        result = tasks_tools.list_task_lists()
        assert "error" in json.loads(result)

    def test_list_task_lists_respects_max_results(self, tasks_tools, mock_tasks_service):
        mock_tasks_service.tasklists().list().execute.return_value = {"items": []}
        tasks_tools.list_task_lists(max_results=500)
        # API caps at 100; we should forward the clamped value
        call_args = mock_tasks_service.tasklists().list.call_args
        assert call_args[1]["maxResults"] == 100


class TestGetTaskList:
    def test_get_task_list_success(self, tasks_tools, mock_tasks_service):
        mock_list = {"id": "list1", "title": "Work"}
        mock_tasks_service.tasklists().get().execute.return_value = mock_list

        result = tasks_tools.get_task_list(task_list_id="list1")
        assert json.loads(result) == mock_list

    def test_get_task_list_not_found(self, tasks_tools, mock_tasks_service):
        mock_tasks_service.tasklists().get().execute.side_effect = _http_error(404, "Not Found")
        result = tasks_tools.get_task_list(task_list_id="missing")
        assert "error" in json.loads(result)


class TestListTasks:
    def test_list_tasks_success(self, tasks_tools, mock_tasks_service):
        mock_tasks = [
            {"id": "t1", "title": "Buy milk", "status": "needsAction"},
            {"id": "t2", "title": "Walk dog", "status": "completed"},
        ]
        mock_tasks_service.tasks().list().execute.return_value = {"items": mock_tasks}

        result = tasks_tools.list_tasks(task_list_id="list1")
        assert json.loads(result) == mock_tasks

    def test_list_tasks_empty(self, tasks_tools, mock_tasks_service):
        mock_tasks_service.tasks().list().execute.return_value = {"items": []}
        result = tasks_tools.list_tasks(task_list_id="list1")
        assert json.loads(result) == {"message": "No tasks found."}

    def test_list_tasks_forwards_filters(self, tasks_tools, mock_tasks_service):
        mock_tasks_service.tasks().list().execute.return_value = {"items": []}
        tasks_tools.list_tasks(
            task_list_id="list1",
            show_completed=False,
            show_hidden=True,
            due_min="2026-01-01T00:00:00Z",
            due_max="2026-12-31T23:59:59Z",
            updated_min="2026-04-01T00:00:00Z",
        )
        call_args = mock_tasks_service.tasks().list.call_args
        assert call_args[1]["tasklist"] == "list1"
        assert call_args[1]["showCompleted"] is False
        assert call_args[1]["showHidden"] is True
        assert call_args[1]["dueMin"] == "2026-01-01T00:00:00Z"
        assert call_args[1]["dueMax"] == "2026-12-31T23:59:59Z"
        assert call_args[1]["updatedMin"] == "2026-04-01T00:00:00Z"

    def test_list_tasks_http_error(self, tasks_tools, mock_tasks_service):
        mock_tasks_service.tasks().list().execute.side_effect = _http_error(500, "Server Error")
        result = tasks_tools.list_tasks(task_list_id="list1")
        assert "error" in json.loads(result)


class TestGetTask:
    def test_get_task_success(self, tasks_tools, mock_tasks_service):
        mock_task = {"id": "t1", "title": "Buy milk"}
        mock_tasks_service.tasks().get().execute.return_value = mock_task

        result = tasks_tools.get_task(task_list_id="list1", task_id="t1")
        assert json.loads(result) == mock_task

    def test_get_task_not_found(self, tasks_tools, mock_tasks_service):
        mock_tasks_service.tasks().get().execute.side_effect = _http_error(404, "Not Found")
        result = tasks_tools.get_task(task_list_id="list1", task_id="missing")
        assert "error" in json.loads(result)


class TestCreateTaskList:
    def test_create_task_list_success(self, tasks_tools, mock_tasks_service):
        mock_list = {"id": "new_list", "title": "Groceries"}
        mock_tasks_service.tasklists().insert().execute.return_value = mock_list

        result = tasks_tools.create_task_list(title="Groceries")
        assert json.loads(result) == mock_list

    def test_create_task_list_sends_title(self, tasks_tools, mock_tasks_service):
        mock_tasks_service.tasklists().insert().execute.return_value = {"id": "x", "title": "X"}
        tasks_tools.create_task_list(title="Groceries")
        call_args = mock_tasks_service.tasklists().insert.call_args
        assert call_args[1]["body"] == {"title": "Groceries"}


class TestUpdateTaskList:
    def test_update_task_list_success(self, tasks_tools, mock_tasks_service):
        mock_tasks_service.tasklists().patch().execute.return_value = {"id": "list1", "title": "Renamed"}

        result = tasks_tools.update_task_list(task_list_id="list1", title="Renamed")
        assert json.loads(result)["title"] == "Renamed"

    def test_update_task_list_uses_patch(self, tasks_tools, mock_tasks_service):
        mock_tasks_service.tasklists().patch().execute.return_value = {}
        tasks_tools.update_task_list(task_list_id="list1", title="New name")
        # Ensure we call patch, not update — patch is safer for partial updates
        assert mock_tasks_service.tasklists().patch.called


class TestDeleteTaskList:
    def test_delete_task_list_success(self, tasks_tools_all, mock_tasks_service):
        mock_tasks_service.tasklists().delete().execute.return_value = None

        result = tasks_tools_all.delete_task_list(task_list_id="list1")
        result_data = json.loads(result)
        assert result_data["success"] is True
        assert "deleted" in result_data["message"]

    def test_delete_task_list_http_error(self, tasks_tools_all, mock_tasks_service):
        mock_tasks_service.tasklists().delete().execute.side_effect = _http_error(404, "Not Found")
        result = tasks_tools_all.delete_task_list(task_list_id="missing")
        assert "error" in json.loads(result)


class TestCreateTask:
    def test_create_task_minimal(self, tasks_tools, mock_tasks_service):
        mock_task = {"id": "new_task", "title": "Buy eggs"}
        mock_tasks_service.tasks().insert().execute.return_value = mock_task

        result = tasks_tools.create_task(task_list_id="list1", title="Buy eggs")
        assert json.loads(result) == mock_task

    def test_create_task_with_all_fields(self, tasks_tools, mock_tasks_service):
        mock_tasks_service.tasks().insert().execute.return_value = {"id": "new_task"}
        tasks_tools.create_task(
            task_list_id="list1",
            title="Submit report",
            notes="Q1 figures included",
            due="2026-04-15T00:00:00Z",
            parent="parent_task_id",
            previous="sibling_task_id",
        )
        call_args = mock_tasks_service.tasks().insert.call_args
        assert call_args[1]["tasklist"] == "list1"
        assert call_args[1]["body"]["title"] == "Submit report"
        assert call_args[1]["body"]["notes"] == "Q1 figures included"
        assert call_args[1]["body"]["due"] == "2026-04-15T00:00:00Z"
        assert call_args[1]["parent"] == "parent_task_id"
        assert call_args[1]["previous"] == "sibling_task_id"

    def test_create_task_omits_none_fields(self, tasks_tools, mock_tasks_service):
        mock_tasks_service.tasks().insert().execute.return_value = {"id": "new_task"}
        tasks_tools.create_task(task_list_id="list1", title="Simple")
        call_args = mock_tasks_service.tasks().insert.call_args
        assert "notes" not in call_args[1]["body"]
        assert "due" not in call_args[1]["body"]
        assert "parent" not in call_args[1]
        assert "previous" not in call_args[1]


class TestUpdateTask:
    def test_update_task_title(self, tasks_tools, mock_tasks_service):
        mock_tasks_service.tasks().patch().execute.return_value = {"id": "t1", "title": "New"}

        result = tasks_tools.update_task(task_list_id="list1", task_id="t1", title="New")
        assert json.loads(result)["title"] == "New"

    def test_update_task_patches_only_provided_fields(self, tasks_tools, mock_tasks_service):
        mock_tasks_service.tasks().patch().execute.return_value = {}
        tasks_tools.update_task(task_list_id="list1", task_id="t1", notes="Updated")
        call_args = mock_tasks_service.tasks().patch.call_args
        assert call_args[1]["body"] == {"notes": "Updated"}
        # Title and due should not be sent
        assert "title" not in call_args[1]["body"]
        assert "due" not in call_args[1]["body"]

    def test_update_task_rejects_empty_body(self, tasks_tools):
        result = tasks_tools.update_task(task_list_id="list1", task_id="t1")
        assert "error" in json.loads(result)

    def test_update_task_rejects_invalid_status(self, tasks_tools):
        result = tasks_tools.update_task(
            task_list_id="list1",
            task_id="t1",
            status="invalid",
        )
        assert "error" in json.loads(result)

    def test_update_task_accepts_valid_statuses(self, tasks_tools, mock_tasks_service):
        mock_tasks_service.tasks().patch().execute.return_value = {}
        result_a = tasks_tools.update_task(task_list_id="list1", task_id="t1", status="completed")
        result_b = tasks_tools.update_task(task_list_id="list1", task_id="t1", status="needsAction")
        assert "error" not in json.loads(result_a)
        assert "error" not in json.loads(result_b)


class TestCompleteTask:
    def test_complete_task_success(self, tasks_tools, mock_tasks_service):
        mock_tasks_service.tasks().patch().execute.return_value = {
            "id": "t1",
            "status": "completed",
        }

        result = tasks_tools.complete_task(task_list_id="list1", task_id="t1")
        assert json.loads(result)["status"] == "completed"

    def test_complete_task_sends_correct_body(self, tasks_tools, mock_tasks_service):
        mock_tasks_service.tasks().patch().execute.return_value = {}
        tasks_tools.complete_task(task_list_id="list1", task_id="t1")
        call_args = mock_tasks_service.tasks().patch.call_args
        assert call_args[1]["body"] == {"status": "completed"}


class TestMoveTask:
    def test_move_task_success(self, tasks_tools, mock_tasks_service):
        mock_moved = {"id": "t1", "position": "00000000000000000001"}
        mock_tasks_service.tasks().move().execute.return_value = mock_moved

        result = tasks_tools.move_task(task_list_id="list1", task_id="t1")
        assert json.loads(result) == mock_moved

    def test_move_task_between_lists(self, tasks_tools, mock_tasks_service):
        mock_tasks_service.tasks().move().execute.return_value = {}
        tasks_tools.move_task(
            task_list_id="list1",
            task_id="t1",
            destination_task_list_id="list2",
        )
        call_args = mock_tasks_service.tasks().move.call_args
        assert call_args[1]["destinationTasklist"] == "list2"

    def test_move_task_with_parent_and_previous(self, tasks_tools, mock_tasks_service):
        mock_tasks_service.tasks().move().execute.return_value = {}
        tasks_tools.move_task(
            task_list_id="list1",
            task_id="t1",
            parent="parent_id",
            previous="sibling_id",
        )
        call_args = mock_tasks_service.tasks().move.call_args
        assert call_args[1]["parent"] == "parent_id"
        assert call_args[1]["previous"] == "sibling_id"


class TestDeleteTask:
    def test_delete_task_success(self, tasks_tools_all, mock_tasks_service):
        mock_tasks_service.tasks().delete().execute.return_value = None

        result = tasks_tools_all.delete_task(task_list_id="list1", task_id="t1")
        result_data = json.loads(result)
        assert result_data["success"] is True

    def test_delete_task_http_error(self, tasks_tools_all, mock_tasks_service):
        mock_tasks_service.tasks().delete().execute.side_effect = _http_error(404, "Not Found")
        result = tasks_tools_all.delete_task(task_list_id="list1", task_id="missing")
        assert "error" in json.loads(result)


class TestClearCompletedTasks:
    def test_clear_completed_success(self, tasks_tools_all, mock_tasks_service):
        mock_tasks_service.tasks().clear().execute.return_value = None

        result = tasks_tools_all.clear_completed_tasks(task_list_id="list1")
        result_data = json.loads(result)
        assert result_data["success"] is True

    def test_clear_completed_http_error(self, tasks_tools_all, mock_tasks_service):
        mock_tasks_service.tasks().clear().execute.side_effect = _http_error(403, "Forbidden")
        result = tasks_tools_all.clear_completed_tasks(task_list_id="list1")
        assert "error" in json.loads(result)
