import gc
import warnings
from unittest.mock import Mock

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from agno.db.postgres import AsyncPostgresDb
from agno.session.workflow import WorkflowSession
from agno.workflow.workflow import Workflow


@pytest.fixture
def workflow_with_async_postgres_db() -> Workflow:
    engine = Mock(spec=AsyncEngine)
    db = AsyncPostgresDb(
        db_engine=engine,
        db_schema="test_schema",
        session_table="test_sessions",
    )
    return Workflow(id="test-workflow", db=db, session_id="test-session")


def _assert_raises_without_unawaited_warning(callable_to_test):
    # Flush coroutines abandoned by earlier tests first: the collect inside the
    # capture window would otherwise surface their warnings and blame this test.
    gc.collect()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", RuntimeWarning)
        with pytest.raises(ValueError, match="Cannot use sync .* with an async database"):
            callable_to_test()
        gc.collect()

    assert not [
        warning
        for warning in caught
        if warning.category is RuntimeWarning and "was never awaited" in str(warning.message)
    ]


@pytest.mark.parametrize(
    "method_name",
    [
        "get_session",
        "read_or_create_session",
        "_read_session",
    ],
)
def test_sync_workflow_session_reads_reject_async_postgres_db_without_leaking_coroutines(
    workflow_with_async_postgres_db: Workflow, method_name: str
):
    method = getattr(workflow_with_async_postgres_db, method_name)

    _assert_raises_without_unawaited_warning(lambda: method(session_id="test-session"))


@pytest.mark.parametrize(
    "method_name",
    [
        "save_session",
        "_upsert_session",
    ],
)
def test_sync_workflow_session_writes_reject_async_postgres_db_without_leaking_coroutines(
    workflow_with_async_postgres_db: Workflow, method_name: str
):
    method = getattr(workflow_with_async_postgres_db, method_name)
    session = WorkflowSession(
        session_id="test-session",
        workflow_id="test-workflow",
        session_data={},
    )

    _assert_raises_without_unawaited_warning(lambda: method(session=session))


def test_sync_workflow_delete_session_rejects_async_postgres_db_without_leaking_coroutines(
    workflow_with_async_postgres_db: Workflow,
):
    _assert_raises_without_unawaited_warning(
        lambda: workflow_with_async_postgres_db.delete_session(session_id="test-session")
    )


def test_sync_workflow_get_run_rejects_async_postgres_db_without_leaking_coroutines(
    workflow_with_async_postgres_db: Workflow,
):
    _assert_raises_without_unawaited_warning(lambda: workflow_with_async_postgres_db.get_run(run_id="test-run"))
