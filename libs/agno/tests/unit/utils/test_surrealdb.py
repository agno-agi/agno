from unittest.mock import AsyncMock, MagicMock

import pytest

from agno.utils.surrealdb import arun_query, run_delete, run_query


class SyncBuilder:
    def __init__(self, statements):
        self.statements = statements
        self.calls = 0

    def first(self):
        self.calls += 1
        return self.statements[0]


class AsyncBuilder:
    def __init__(self, statements):
        self.statements = statements

    async def first(self):
        return self.statements[0]

    def __await__(self):
        async def run():
            return self.statements

        return run().__await__()


class CrudBuilder:
    def __init__(self, value):
        self.value = value
        self.calls = 0

    def execute(self):
        self.calls += 1
        return self.value


def test_run_query_passes_through_an_eager_result():
    client = MagicMock()
    client.query.return_value = [{"id": 1}]

    assert run_query(client, "SELECT 1", {"a": 1}) == [{"id": 1}]
    client.query.assert_called_once_with("SELECT 1", {"a": 1})


def test_run_query_omits_vars_when_not_given():
    client = MagicMock()
    client.query.return_value = None

    run_query(client, "SELECT 1")
    client.query.assert_called_once_with("SELECT 1")


def test_run_query_executes_a_lazy_builder_and_keeps_the_first_statement():
    builder = SyncBuilder([[{"id": 1}], [{"id": 2}]])
    client = MagicMock()
    client.query.return_value = builder

    assert run_query(client, "SELECT 1; SELECT 2;") == [{"id": 1}]
    assert builder.calls == 1


@pytest.mark.asyncio
async def test_arun_query_awaits_an_eager_coroutine():
    client = MagicMock()
    client.query = AsyncMock(return_value=[{"id": 1}])

    assert await arun_query(client, "SELECT 1", {"a": 1}) == [{"id": 1}]
    client.query.assert_awaited_once_with("SELECT 1", {"a": 1})


@pytest.mark.asyncio
async def test_arun_query_returns_the_first_statement_not_the_statement_list():
    client = MagicMock()
    client.query.return_value = AsyncBuilder([[{"id": 1}], [{"id": 2}]])

    assert await arun_query(client, "SELECT 1; SELECT 2;") == [{"id": 1}]


def test_run_delete_passes_through_an_eager_result():
    client = MagicMock()
    client.delete.return_value = {"id": 1}

    assert run_delete(client, "table") == {"id": 1}
    client.delete.assert_called_once_with("table")


def test_run_delete_executes_a_lazy_builder():
    builder = CrudBuilder({"id": 1})
    client = MagicMock()
    client.delete.return_value = builder

    assert run_delete(client, "table") == {"id": 1}
    assert builder.calls == 1
