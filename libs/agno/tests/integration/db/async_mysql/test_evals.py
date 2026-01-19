"""Integration tests for AsyncMySQLDb eval methods"""

import time

import pytest

from agno.db.schemas.evals import EvalRunRecord, EvalType


@pytest.mark.asyncio
async def test_create_and_get_eval_run(async_mysql_db_real):
    """Test creating and retrieving an eval run"""
    eval_run = EvalRunRecord(
        run_id="test-eval-1",
        name="Test Eval",
        eval_type=EvalType.ACCURACY,
        agent_id="test-agent",
        model_id="gpt-4",
        eval_data={"score": 0.9, "accuracy": "high"},
        eval_input={"prompt": "test prompt"},
        created_at=int(time.time()),
        updated_at=int(time.time()),
    )

    # Create eval run
    result = await async_mysql_db_real.create_eval_run(eval_run)
    assert result is not None
    assert result.run_id == "test-eval-1"

    # Get eval run back
    retrieved = await async_mysql_db_real.get_eval_run("test-eval-1")
    assert retrieved is not None
    assert retrieved.name == "Test Eval"
    assert retrieved.eval_type == EvalType.ACCURACY


@pytest.mark.asyncio
async def test_get_eval_runs_with_filters(async_mysql_db_real):
    """Test getting eval runs with various filters"""
    # Create multiple eval runs
    for i in range(3):
        eval_run = EvalRunRecord(
            run_id=f"test-filter-eval-{i}",
            name=f"Eval {i}",
            eval_type=EvalType.ACCURACY if i % 2 == 0 else EvalType.RELIABILITY,
            agent_id=f"agent-{i % 2}",
            eval_data={"score": 0.8 + i * 0.05},
            eval_input={"test": f"input-{i}"},
            created_at=int(time.time()),
            updated_at=int(time.time()),
        )
        await async_mysql_db_real.create_eval_run(eval_run)

    # Get all eval runs
    eval_runs = await async_mysql_db_real.get_eval_runs()
    assert len(eval_runs) >= 3

    # Filter by agent_id
    agent_evals = await async_mysql_db_real.get_eval_runs(agent_id="agent-0")
    assert len(agent_evals) >= 1

    # Filter by eval_type
    accuracy_evals = await async_mysql_db_real.get_eval_runs(eval_type=[EvalType.ACCURACY])
    assert len(accuracy_evals) >= 2


@pytest.mark.asyncio
async def test_delete_eval_run(async_mysql_db_real):
    """Test deleting an eval run"""
    eval_run = EvalRunRecord(
        run_id="test-delete-eval",
        name="To be deleted",
        eval_type=EvalType.ACCURACY,
        eval_data={"score": 0.75},
        eval_input={"test": "delete"},
        created_at=int(time.time()),
        updated_at=int(time.time()),
    )

    # Create and then delete
    await async_mysql_db_real.create_eval_run(eval_run)
    await async_mysql_db_real.delete_eval_run("test-delete-eval")

    # Verify it's gone
    retrieved = await async_mysql_db_real.get_eval_run("test-delete-eval")
    assert retrieved is None


@pytest.mark.asyncio
async def test_delete_multiple_eval_runs(async_mysql_db_real):
    """Test deleting multiple eval runs"""
    # Create multiple eval runs
    run_ids = []
    for i in range(3):
        eval_run = EvalRunRecord(
            run_id=f"test-bulk-delete-eval-{i}",
            name=f"Eval {i}",
            eval_type=EvalType.ACCURACY,
            eval_data={"score": 0.8},
            eval_input={"test": f"bulk-{i}"},
            created_at=int(time.time()),
            updated_at=int(time.time()),
        )
        await async_mysql_db_real.create_eval_run(eval_run)
        run_ids.append(eval_run.run_id)

    # Delete all at once
    await async_mysql_db_real.delete_eval_runs(run_ids)

    # Verify all are gone
    for run_id in run_ids:
        retrieved = await async_mysql_db_real.get_eval_run(run_id)
        assert retrieved is None


@pytest.mark.asyncio
async def test_rename_eval_run(async_mysql_db_real):
    """Test renaming an eval run"""
    eval_run = EvalRunRecord(
        run_id="test-rename-eval",
        name="Original Name",
        eval_type=EvalType.ACCURACY,
        eval_data={"score": 0.85},
        eval_input={"test": "rename"},
        created_at=int(time.time()),
        updated_at=int(time.time()),
    )

    await async_mysql_db_real.create_eval_run(eval_run)

    # Rename the eval run
    renamed = await async_mysql_db_real.rename_eval_run(eval_run_id="test-rename-eval", name="New Name")

    assert renamed is not None
    assert renamed.name == "New Name"


@pytest.mark.asyncio
async def test_get_eval_runs_pagination(async_mysql_db_real):
    """Test getting eval runs with pagination"""
    # Create multiple eval runs
    for i in range(5):
        eval_run = EvalRunRecord(
            run_id=f"test-pagination-eval-{i}",
            name=f"Eval {i}",
            eval_type=EvalType.ACCURACY,
            eval_data={"score": 0.7 + i * 0.05},
            eval_input={"test": f"page-{i}"},
            created_at=int(time.time()),
            updated_at=int(time.time()),
        )
        await async_mysql_db_real.create_eval_run(eval_run)

    # Get with pagination
    page1, total = await async_mysql_db_real.get_eval_runs(limit=2, page=1, deserialize=False)
    assert len(page1) <= 2
    assert total >= 5
