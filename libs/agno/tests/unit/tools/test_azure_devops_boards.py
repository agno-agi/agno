"""Unit tests for AzureDevOpsBoardsTools."""

import json
from unittest.mock import Mock

import pytest

from agno.tools.azure_devops.boards import AzureDevOpsBoardsTools


def _field(reference_name, name):
    field = Mock()
    field.reference_name = reference_name
    field.name = name
    return field


@pytest.fixture
def boards_tools():
    tools = AzureDevOpsBoardsTools(
        organization_url="https://dev.azure.com/org",
        personal_access_token="pat",
        project="MyProject",
    )
    tools._clients["wit"] = Mock()
    tools._clients["work"] = Mock()
    tools._clients["core"] = Mock()
    return tools


def test_init_registers_all_tools():
    tools = AzureDevOpsBoardsTools(
        organization_url="https://dev.azure.com/org", personal_access_token="pat", project="P"
    )
    names = {func.name for func in tools.functions.values()}
    assert names == {
        "search_tasks",
        "get_task",
        "create_task",
        "update_task",
        "add_parent_child_link",
        "get_task_comment",
        "add_task_comment",
        "get_sprints",
        "get_fields",
    }


def test_init_selective_tools():
    tools = AzureDevOpsBoardsTools(
        organization_url="https://dev.azure.com/org",
        personal_access_token="pat",
        project="P",
        enable_create_task=False,
        enable_update_task=False,
    )
    names = {func.name for func in tools.functions.values()}
    assert "create_task" not in names
    assert "search_tasks" in names


def test_async_variants_registered():
    tools = AzureDevOpsBoardsTools(
        organization_url="https://dev.azure.com/org", personal_access_token="pat", project="P"
    )
    async_names = {func.name for func in tools.async_functions.values()}
    assert "create_task" in async_names


def test_get_fields_success(boards_tools):
    boards_tools._clients["wit"].get_fields.return_value = [
        _field("System.Title", "Title"),
        _field("System.State", "State"),
    ]
    result = json.loads(boards_tools.get_fields())
    assert result["fields"]["System.Title"] == "Title"


def test_get_sprints_success(boards_tools):
    iteration = Mock()
    iteration.name = "Sprint 1"
    iteration.path = "MyProject\\Sprint 1"
    iteration.attributes = Mock(time_frame="current")
    boards_tools._clients["work"].get_team_iterations.return_value = [iteration]

    result = json.loads(boards_tools.get_sprints())
    assert result["sprints"][0]["name"] == "Sprint 1"
    assert result["sprints"][0]["is_current"] is True


def test_get_task_single_success(boards_tools):
    boards_tools._clients["wit"].get_fields.return_value = [_field("System.Title", "Title")]
    work_item = Mock()
    work_item.id = 42
    work_item.fields = {"System.Title": "My task"}
    work_item.relations = []
    boards_tools._clients["wit"].get_work_item.return_value = work_item

    result = json.loads(boards_tools.get_task("42"))
    assert "Work Item 42" in result["result"]
    assert "My task" in result["result"]


def test_create_task_success(boards_tools):
    boards_tools._clients["wit"].get_fields.return_value = [_field("System.Title", "Title")]
    created = Mock()
    created.id = 100
    created.fields = {"System.Title": "New task"}
    created.relations = []
    boards_tools._clients["wit"].create_work_item.return_value = created

    result = json.loads(boards_tools.create_task(title="New task", work_item_type="Task"))
    assert "Work Item 100" in result["result"]


def test_create_task_requires_title(boards_tools):
    boards_tools._clients["wit"].get_fields.return_value = []
    result = json.loads(boards_tools.create_task(title="", work_item_type="Task"))
    assert "error" in result


def test_add_task_comment_success(boards_tools):
    new_comment = Mock()
    new_comment.text = "Nice work"
    new_comment.created_by = Mock(display_name="Jane")
    new_comment.created_date = None
    boards_tools._clients["wit"].add_comment.return_value = new_comment

    result = json.loads(boards_tools.add_task_comment("42", "Nice work"))
    assert "Nice work" in result["result"]
    assert "Jane" in result["result"]


def test_get_task_comment_empty(boards_tools):
    comments = Mock()
    comments.comments = []
    boards_tools._clients["wit"].get_comments.return_value = comments

    result = json.loads(boards_tools.get_task_comment("42"))
    assert result["comments"] == []


def test_search_tasks_no_results(boards_tools):
    query_result = Mock()
    query_result.work_items = []
    boards_tools._clients["wit"].query_by_wiql.return_value = query_result

    result = json.loads(boards_tools.search_tasks())
    assert result["results"] == []


def test_update_task_requires_field(boards_tools):
    boards_tools._clients["wit"].get_fields.return_value = []
    result = json.loads(boards_tools.update_task("42"))
    assert "error" in result


def test_create_task_invalid_assignee_hint(boards_tools):
    boards_tools._clients["wit"].get_fields.return_value = [_field("System.Title", "Title")]
    boards_tools._clients["wit"].create_work_item.side_effect = Exception("unknown identity found")

    team = Mock()
    team.id = "team-1"
    boards_tools._clients["core"].get_teams.return_value = [team]
    member = Mock()
    member.identity = Mock(display_name="Jane Doe")
    boards_tools._clients["core"].get_team_members_with_extended_properties.return_value = [member]

    result = json.loads(boards_tools.create_task(title="X", work_item_type="Task", assigned_to="ghost"))
    assert "Jane Doe" in result["valid_assignees"]


@pytest.mark.asyncio
async def test_aget_fields_success(boards_tools):
    boards_tools._clients["wit"].get_fields.return_value = [_field("System.Title", "Title")]
    result = json.loads(await boards_tools.aget_fields())
    assert result["fields"]["System.Title"] == "Title"
