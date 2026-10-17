"""Exercise issue field handling through PyGithub's real request construction."""

import json
from unittest.mock import patch

import pytest
from github.Issue import Issue
from github.Repository import Repository

from agno.tools.github import GithubTools


@pytest.fixture
def issue_client():
    tools = GithubTools(access_token="test-token")
    requester = tools.g._Github__requester
    data = {
        "id": 42,
        "number": 42,
        "title": "Existing title",
        "body": "Existing body",
        "url": "https://api.github.com/repos/test-org/test-repo/issues/42",
        "html_url": "https://github.com/test-org/test-repo/issues/42",
        "state": "open",
        "created_at": "2026-01-01T00:00:00Z",
        "user": {"login": "test-user"},
    }
    repo = Repository(requester, {}, {"url": "https://api.github.com/repos/test-org/test-repo"}, completed=True)
    issue = Issue(requester, {}, data, completed=True)
    with (
        patch.object(tools.g, "get_repo", return_value=repo),
        patch.object(repo, "get_issue", return_value=issue),
        patch.object(requester, "requestJsonAndCheck", return_value=({}, data)) as request,
    ):
        yield tools, request
    tools.g.close()


@pytest.mark.parametrize("fields", [{}, {"body": None}, {"body": ""}, {"body": "Issue description"}])
def test_create_issue_optional_body(issue_client, fields):
    tools, request = issue_client

    result = json.loads(tools.create_issue("test-org/test-repo", "New issue", **fields))

    assert result["number"] == 42
    assert result["user"] == "test-user"
    request.assert_called_once()
    assert request.call_args.args == ("POST", "https://api.github.com/repos/test-org/test-repo/issues")
    expected = {"title": "New issue"}
    if fields.get("body") is not None:
        expected["body"] = fields["body"]
    assert request.call_args.kwargs["input"] == expected


@pytest.mark.parametrize(
    "fields",
    [
        {"title": "New title"},
        {"body": "New body"},
        {"title": "New title", "body": "New body"},
        {"title": None, "body": "New body"},
        {"title": "New title", "body": None},
        {"title": "", "body": "New body"},
        {"body": ""},
    ],
)
def test_edit_issue_optional_fields(issue_client, fields):
    tools, request = issue_client

    result = json.loads(tools.edit_issue("test-org/test-repo", 42, **fields))

    assert result == {"message": "Issue #42 updated."}
    request.assert_called_once()
    assert request.call_args.args == ("PATCH", "https://api.github.com/repos/test-org/test-repo/issues/42")
    payload = request.call_args.kwargs["input"]
    for field in ("title", "body"):
        if fields.get(field) is None:
            assert field not in payload
        else:
            assert payload[field] == fields[field]
