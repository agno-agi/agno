from __future__ import annotations

from unittest.mock import MagicMock

import pytest

pytest.importorskip("boto3")

from agno.db.dynamo.utils import create_table_if_not_exists


class _ResourceNotFound(Exception):
    pass


class _ClientError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


def _client() -> MagicMock:
    client = MagicMock()
    client.exceptions.ResourceNotFoundException = _ResourceNotFound
    return client


def test_existing_table_is_not_reported_as_created() -> None:
    client = _client()

    assert create_table_if_not_exists(client, "sessions", {"TableName": "sessions"}) is False
    client.create_table.assert_not_called()


def test_creator_waits_for_table_and_reports_ownership() -> None:
    client = _client()
    client.describe_table.side_effect = _ResourceNotFound()

    assert create_table_if_not_exists(client, "sessions", {"TableName": "sessions"}) is True
    client.create_table.assert_called_once_with(TableName="sessions")
    client.get_waiter.return_value.wait.assert_called_once_with(TableName="sessions")


def test_resource_in_use_race_loser_waits_but_does_not_claim_creation() -> None:
    client = _client()
    client.describe_table.side_effect = _ResourceNotFound()
    client.create_table.side_effect = _ClientError("ResourceInUseException")

    assert create_table_if_not_exists(client, "sessions", {"TableName": "sessions"}) is False
    client.get_waiter.return_value.wait.assert_called_once_with(TableName="sessions")


def test_real_creation_failure_propagates() -> None:
    client = _client()
    client.describe_table.side_effect = _ResourceNotFound()
    client.create_table.side_effect = _ClientError("AccessDeniedException")

    with pytest.raises(_ClientError):
        create_table_if_not_exists(client, "sessions", {"TableName": "sessions"})
    client.get_waiter.assert_not_called()
