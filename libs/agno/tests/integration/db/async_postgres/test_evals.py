"""Integration tests for the Eval related methods of the AsyncPostgresDb class"""

import time
from typing import List

import pytest
import pytest_asyncio

from agno.db.postgres import AsyncPostgresDb
from agno.db.schemas.evals import EvalFilterType, EvalRunRecord, EvalType


@pytest_asyncio.fixture(autouse=True)
async def cleanup_evals(async_postgres_db_real: AsyncPostgresDb):
    """Fixture to clean-up eval rows after each test"""
    yield

    try:
        eval_table = await async_postgres_db_real._get_table("evals")
        async with async_postgres_db_real.async_session_factory() as session:
            await session.execute(eval_table.delete())
            await session.commit()
    except Exception:
        pass  # Ignore cleanup errors


@pytest.fixture
def sample_eval_run() -> EvalRunRecord:
    """Fixture returning a sample EvalRunRecord"""
    return EvalRunRecord(
        run_id="test_eval_run_1",
        eval_type=EvalType.ACCURACY,
        eval_data={"score": 0.85, "feedback": "Good performance"},
        eval_input={"prompt": "Test prompt", "expected": "Expected output"},
        name="Test Evaluation Run",
        agent_id="test_agent_1",
        team_id=None,
        workflow_id=None,
        model_id="gpt-4",
        model_provider="openai",
        evaluated_component_name="Test Agent",
        created_at=int(time.time()),
        updated_at=int(time.time()),
    )


@pytest.fixture
def sample_eval_runs() -> List[EvalRunRecord]:
    """Fixture returning multiple sample EvalRunRecords"""
    runs = []
    for i in range(5):
        runs.append(
            EvalRunRecord(
                run_id=f"test_eval_run_{i}",
                eval_type=EvalType.ACCURACY if i % 2 == 0 else EvalType.RELIABILITY,
                eval_data={"score": 0.8 + (i * 0.02), "feedback": f"Test feedback {i}"},
                eval_input={"prompt": f"Test prompt {i}", "expected": f"Expected output {i}"},
                name=f"Test Evaluation Run {i}",
                agent_id=f"test_agent_{i}" if i % 2 == 0 else None,
                team_id=f"test_team_{i}" if i % 2 == 1 else None,
                workflow_id=None,
                model_id="gpt-4" if i % 3 == 0 else "gpt-3.5-turbo",
                model_provider="openai",
                evaluated_component_name=f"Test Component {i}",
                created_at=int(time.time()) + i,
                updated_at=int(time.time()) + i,
            )
        )
    return runs


@pytest.mark.asyncio
async def test_create_eval_run(async_postgres_db_real: AsyncPostgresDb, sample_eval_run: EvalRunRecord):
    """Test creating an eval run"""
    result = await async_postgres_db_real.create_eval_run(sample_eval_run)

    assert result is not None
    assert result.run_id == "test_eval_run_1"
    assert result.eval_type == EvalType.ACCURACY
    assert result.eval_data["score"] == 0.85
    assert result.name == "Test Evaluation Run"


@pytest.mark.asyncio
async def test_get_eval_run(async_postgres_db_real: AsyncPostgresDb, sample_eval_run: EvalRunRecord):
    """Test getting a single eval run"""
    # First create the eval run
    await async_postgres_db_real.create_eval_run(sample_eval_run)

    # Now get it back
    result = await async_postgres_db_real.get_eval_run("test_eval_run_1")

    assert result is not None
    assert isinstance(result, EvalRunRecord)
    assert result.run_id == "test_eval_run_1"
    assert result.eval_type == EvalType.ACCURACY
    assert result.agent_id == "test_agent_1"
    assert result.eval_data["score"] == 0.85


@pytest.mark.asyncio
async def test_get_eval_run_deserialize_false(async_postgres_db_real: AsyncPostgresDb, sample_eval_run: EvalRunRecord):
    """Test getting an eval run as raw dict"""
    # First create the eval run
    await async_postgres_db_real.create_eval_run(sample_eval_run)

    # Now get it back as dict
    result = await async_postgres_db_real.get_eval_run("test_eval_run_1", deserialize=False)

    assert result is not None
    assert isinstance(result, dict)
    assert result["run_id"] == "test_eval_run_1"
    assert result["eval_type"] == EvalType.ACCURACY
    assert result["agent_id"] == "test_agent_1"


@pytest.mark.asyncio
async def test_get_eval_run_not_found(async_postgres_db_real: AsyncPostgresDb):
    """Test getting eval run that doesn't exist"""
    result = await async_postgres_db_real.get_eval_run("nonexistent_id")

    assert result is None


@pytest.mark.asyncio
async def test_get_eval_runs_all(async_postgres_db_real: AsyncPostgresDb, sample_eval_runs: List[EvalRunRecord]):
    """Test getting all eval runs"""
    # Insert all eval runs
    for run in sample_eval_runs:
        await async_postgres_db_real.create_eval_run(run)

    # Get all runs
    runs = await async_postgres_db_real.get_eval_runs()

    assert len(runs) == 5
    assert all(isinstance(run, EvalRunRecord) for run in runs)


@pytest.mark.asyncio
async def test_get_eval_runs_with_filters(
    async_postgres_db_real: AsyncPostgresDb, sample_eval_runs: List[EvalRunRecord]
):
    """Test getting eval runs with various filters"""
    # Insert all eval runs
    for run in sample_eval_runs:
        await async_postgres_db_real.create_eval_run(run)

    # Filter by agent_id
    agent_runs = await async_postgres_db_real.get_eval_runs(agent_id="test_agent_0")
    assert len(agent_runs) == 1
    assert agent_runs[0].run_id == "test_eval_run_0"

    # Filter by team_id
    team_runs = await async_postgres_db_real.get_eval_runs(team_id="test_team_1")
    assert len(team_runs) == 1
    assert team_runs[0].run_id == "test_eval_run_1"

    # Filter by model_id
    gpt4_runs = await async_postgres_db_real.get_eval_runs(model_id="gpt-4")
    assert len(gpt4_runs) == 2  # runs 0 and 3

    # Filter by eval_type
    agent_type_runs = await async_postgres_db_real.get_eval_runs(eval_type=[EvalType.ACCURACY])
    assert len(agent_type_runs) == 3  # runs 0, 2, 4

    # Filter by filter_type
    agent_filter_runs = await async_postgres_db_real.get_eval_runs(filter_type=EvalFilterType.AGENT)
    assert len(agent_filter_runs) == 3  # runs with agent_id not None


@pytest.mark.asyncio
async def test_get_eval_runs_with_pagination(
    async_postgres_db_real: AsyncPostgresDb, sample_eval_runs: List[EvalRunRecord]
):
    """Test getting eval runs with pagination"""
    # Insert all eval runs
    for run in sample_eval_runs:
        await async_postgres_db_real.create_eval_run(run)

    # Test pagination - get first page
    runs, total_count = await async_postgres_db_real.get_eval_runs(limit=2, page=1, deserialize=False)

    assert len(runs) == 2
    assert total_count == 5

    # Test pagination - get second page
    runs, total_count = await async_postgres_db_real.get_eval_runs(limit=2, page=2, deserialize=False)

    assert len(runs) == 2
    assert total_count == 5


@pytest.mark.asyncio
async def test_delete_eval_run(async_postgres_db_real: AsyncPostgresDb, sample_eval_run: EvalRunRecord):
    """Test deleting a single eval run"""
    # First create the eval run
    await async_postgres_db_real.create_eval_run(sample_eval_run)

    # Verify it exists
    result = await async_postgres_db_real.get_eval_run("test_eval_run_1")
    assert result is not None

    # Delete it
    await async_postgres_db_real.delete_eval_run("test_eval_run_1")

    # Verify it's gone
    result = await async_postgres_db_real.get_eval_run("test_eval_run_1")
    assert result is None


@pytest.mark.asyncio
async def test_delete_eval_runs_bulk(async_postgres_db_real: AsyncPostgresDb, sample_eval_runs: List[EvalRunRecord]):
    """Test deleting multiple eval runs"""
    # Insert all eval runs
    for run in sample_eval_runs:
        await async_postgres_db_real.create_eval_run(run)

    # Verify they exist
    runs = await async_postgres_db_real.get_eval_runs()
    assert len(runs) == 5

    # Delete some of them
    run_ids = ["test_eval_run_0", "test_eval_run_2", "test_eval_run_4"]
    await async_postgres_db_real.delete_eval_runs(run_ids)

    # Verify correct ones are gone
    runs = await async_postgres_db_real.get_eval_runs()
    assert len(runs) == 2
    remaining_ids = [r.run_id for r in runs]
    assert "test_eval_run_1" in remaining_ids
    assert "test_eval_run_3" in remaining_ids


@pytest.mark.asyncio
async def test_rename_eval_run(async_postgres_db_real: AsyncPostgresDb, sample_eval_run: EvalRunRecord):
    """Test renaming an eval run"""
    # First create the eval run
    await async_postgres_db_real.create_eval_run(sample_eval_run)

    # Rename it
    result = await async_postgres_db_real.rename_eval_run(eval_run_id="test_eval_run_1", name="Renamed Evaluation Run")

    assert result is not None
    assert isinstance(result, EvalRunRecord)
    assert result.name == "Renamed Evaluation Run"

    # Verify the change persisted
    retrieved = await async_postgres_db_real.get_eval_run("test_eval_run_1")
    assert retrieved.name == "Renamed Evaluation Run"


@pytest.mark.asyncio
async def test_rename_eval_run_deserialize_false(
    async_postgres_db_real: AsyncPostgresDb, sample_eval_run: EvalRunRecord
):
    """Test renaming an eval run with deserialize=False"""
    # First create the eval run
    await async_postgres_db_real.create_eval_run(sample_eval_run)

    # Rename it with deserialize=False
    result = await async_postgres_db_real.rename_eval_run(
        eval_run_id="test_eval_run_1", name="Renamed Run", deserialize=False
    )

    assert result is not None
    assert isinstance(result, dict)
    assert result["name"] == "Renamed Run"


@pytest.mark.asyncio
async def test_eval_runs_with_multiple_eval_types(async_postgres_db_real: AsyncPostgresDb):
    """Test filtering eval runs by multiple eval types"""
    # Create runs with different eval types
    runs = [
        EvalRunRecord(
            run_id="agent_run",
            eval_type=EvalType.ACCURACY,
            eval_data={"score": 0.8},
            eval_input={"prompt": "test"},
            agent_id="test_agent",
        ),
        EvalRunRecord(
            run_id="team_run",
            eval_type=EvalType.RELIABILITY,
            eval_data={"score": 0.9},
            eval_input={"prompt": "test"},
            team_id="test_team",
        ),
        EvalRunRecord(
            run_id="workflow_run",
            eval_type=EvalType.AGENT_AS_JUDGE,
            eval_data={"score": 0.7},
            eval_input={"prompt": "test"},
            workflow_id="test_workflow",
        ),
    ]

    for run in runs:
        await async_postgres_db_real.create_eval_run(run)

    # Filter by multiple eval types
    filtered_runs = await async_postgres_db_real.get_eval_runs(eval_type=[EvalType.ACCURACY, EvalType.RELIABILITY])

    assert len(filtered_runs) == 2
    run_ids = [r.run_id for r in filtered_runs]
    assert "agent_run" in run_ids
    assert "team_run" in run_ids
    assert "workflow_run" not in run_ids


@pytest.mark.asyncio
async def test_eval_runs_filter_by_component_type(async_postgres_db_real: AsyncPostgresDb):
    """Test filtering eval runs by component type"""
    # Create runs for different component types
    runs = [
        EvalRunRecord(
            run_id="agent_run",
            eval_type=EvalType.ACCURACY,
            eval_data={"score": 0.8},
            eval_input={"prompt": "test"},
            agent_id="test_agent",
        ),
        EvalRunRecord(
            run_id="team_run",
            eval_type=EvalType.RELIABILITY,
            eval_data={"score": 0.9},
            eval_input={"prompt": "test"},
            team_id="test_team",
        ),
        EvalRunRecord(
            run_id="workflow_run",
            eval_type=EvalType.AGENT_AS_JUDGE,
            eval_data={"score": 0.7},
            eval_input={"prompt": "test"},
            workflow_id="test_workflow",
        ),
    ]

    for run in runs:
        await async_postgres_db_real.create_eval_run(run)

    # Filter by agent filter type
    agent_runs = await async_postgres_db_real.get_eval_runs(filter_type=EvalFilterType.AGENT)
    assert len(agent_runs) == 1
    assert agent_runs[0].run_id == "agent_run"

    # Filter by team filter type
    team_runs = await async_postgres_db_real.get_eval_runs(filter_type=EvalFilterType.TEAM)
    assert len(team_runs) == 1
    assert team_runs[0].run_id == "team_run"

    # Filter by workflow filter type
    workflow_runs = await async_postgres_db_real.get_eval_runs(filter_type=EvalFilterType.WORKFLOW)
    assert len(workflow_runs) == 1
    assert workflow_runs[0].run_id == "workflow_run"
