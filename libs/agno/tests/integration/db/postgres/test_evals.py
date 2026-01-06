"""Integration tests for the Eval related methods of the PostgresDb class"""

import time

import pytest

from agno.db.postgres.postgres import PostgresDb
from agno.db.schemas.evals import EvalFilterType, EvalRunRecord, EvalType


@pytest.fixture(autouse=True)
def cleanup_evals(postgres_db_real: PostgresDb):
    """Fixture to clean-up eval rows after each test"""
    yield

    with postgres_db_real.Session() as session:
        try:
            eval_table = postgres_db_real._get_table("evals", create_table_if_not_found=True)
            session.execute(eval_table.delete())
            session.commit()

        except Exception:
            session.rollback()


@pytest.fixture
def sample_eval_run_agent() -> EvalRunRecord:
    """Fixture returning a sample EvalRunRecord for agent evaluation"""
    return EvalRunRecord(
        run_id="test_eval_run_agent_1",
        agent_id="test_agent_1",
        model_id="gpt-4",
        model_provider="openai",
        name="Agent Accuracy Test",
        evaluated_component_name="Test Agent",
        eval_type=EvalType.ACCURACY,
        eval_data={
            "score": 0.85,
            "total_questions": 100,
            "correct_answers": 85,
            "test_duration": 120.5,
            "categories": ["math", "logic", "reasoning"],
            "details": {"math_score": 0.90, "logic_score": 0.80, "reasoning_score": 0.85},
        },
    )


@pytest.fixture
def sample_eval_run_team() -> EvalRunRecord:
    """Fixture returning a sample EvalRunRecord for team evaluation"""
    return EvalRunRecord(
        run_id="test_eval_run_team_1",
        team_id="test_team_1",
        model_id="gpt-4-turbo",
        model_provider="openai",
        name="Team Performance Test",
        evaluated_component_name="Test Team",
        eval_type=EvalType.PERFORMANCE,
        eval_data={
            "response_time": 45.2,
            "throughput": 25.7,
            "success_rate": 0.92,
            "collaboration_score": 0.88,
            "efficiency_metrics": {
                "task_completion_time": 30.5,
                "resource_utilization": 0.75,
                "coordination_overhead": 0.12,
            },
        },
    )


@pytest.fixture
def sample_eval_run_workflow() -> EvalRunRecord:
    """Fixture returning a sample EvalRunRecord for workflow evaluation"""
    return EvalRunRecord(
        run_id="test_eval_run_workflow_1",
        workflow_id="test_workflow_1",
        model_id="claude-3-opus",
        model_provider="anthropic",
        name="Workflow Reliability Test",
        evaluated_component_name="Test Workflow",
        eval_type=EvalType.RELIABILITY,
        eval_data={
            "uptime": 0.999,
            "error_rate": 0.001,
            "recovery_time": 2.5,
            "consistency_score": 0.95,
            "fault_tolerance": {
                "max_failures_handled": 5,
                "recovery_success_rate": 1.0,
                "mean_time_to_recovery": 1.8,
            },
        },
    )


def test_create_eval_run_agent(postgres_db_real: PostgresDb, sample_eval_run_agent: EvalRunRecord):
    """Test creating an eval run for an agent"""
    result = postgres_db_real.create_eval_run(sample_eval_run_agent)

    assert result is not None
    assert isinstance(result, EvalRunRecord)

    # Verify all fields are set correctly
    assert result.run_id == sample_eval_run_agent.run_id
    assert result.agent_id == sample_eval_run_agent.agent_id
    assert result.eval_type == sample_eval_run_agent.eval_type
    assert result.eval_data == sample_eval_run_agent.eval_data
    assert result.name == sample_eval_run_agent.name
    assert result.model_id == sample_eval_run_agent.model_id


def test_create_eval_run_team(postgres_db_real: PostgresDb, sample_eval_run_team: EvalRunRecord):
    """Test creating an eval run for a team"""
    result = postgres_db_real.create_eval_run(sample_eval_run_team)

    assert result is not None
    assert isinstance(result, EvalRunRecord)

    # Verify all fields are set correctly
    assert result.run_id == sample_eval_run_team.run_id
    assert result.team_id == sample_eval_run_team.team_id
    assert result.eval_type == sample_eval_run_team.eval_type
    assert result.eval_data == sample_eval_run_team.eval_data


def test_get_eval_run_agent(postgres_db_real: PostgresDb, sample_eval_run_agent: EvalRunRecord):
    """Test getting an eval run for an agent"""
    postgres_db_real.create_eval_run(sample_eval_run_agent)

    result = postgres_db_real.get_eval_run(sample_eval_run_agent.run_id)

    assert result is not None
    assert isinstance(result, EvalRunRecord)

    # Verify all fields are set correctly
    assert result.run_id == sample_eval_run_agent.run_id
    assert result.agent_id == sample_eval_run_agent.agent_id
    assert result.eval_type == sample_eval_run_agent.eval_type
    assert result.eval_data == sample_eval_run_agent.eval_data


def test_get_eval_run_agent_without_deserialization(postgres_db_real: PostgresDb, sample_eval_run_agent: EvalRunRecord):
    """Test getting an eval run for an agent without deserialization"""
    postgres_db_real.create_eval_run(sample_eval_run_agent)

    result = postgres_db_real.get_eval_run(sample_eval_run_agent.run_id, deserialize=False)

    assert result is not None
    assert isinstance(result, dict)
    assert result["run_id"] == sample_eval_run_agent.run_id
    assert result["agent_id"] == sample_eval_run_agent.agent_id


def test_delete_eval_run_agent(postgres_db_real: PostgresDb, sample_eval_run_agent: EvalRunRecord):
    """Test deleting an eval run for an agent"""
    postgres_db_real.create_eval_run(sample_eval_run_agent)

    # Verify it exists
    eval_run = postgres_db_real.get_eval_run(sample_eval_run_agent.run_id)
    assert eval_run is not None

    # Delete it
    postgres_db_real.delete_eval_run(sample_eval_run_agent.run_id)

    # Verify it's gone
    eval_run = postgres_db_real.get_eval_run(sample_eval_run_agent.run_id)
    assert eval_run is None


def test_delete_multiple_eval_runs_agent(postgres_db_real: PostgresDb):
    """Test deleting multiple eval runs for an agent"""
    # Create multiple eval runs
    eval_runs = []
    run_ids = []
    for i in range(3):
        eval_run = EvalRunRecord(
            run_id=f"test_eval_run_{i}",
            agent_id=f"test_agent_{i}",
            eval_type=EvalType.ACCURACY,
            eval_data={"score": 0.8 + (i * 0.05)},
            name=f"Test Eval {i}",
        )
        eval_runs.append(eval_run)
        run_ids.append(eval_run.run_id)
        postgres_db_real.create_eval_run(eval_run)

    # Verify they exist
    for run_id in run_ids:
        eval_run = postgres_db_real.get_eval_run(run_id)
        assert eval_run is not None

    # Delete first 2
    postgres_db_real.delete_eval_runs(run_ids[:2])

    # Verify deletions
    assert postgres_db_real.get_eval_run(run_ids[0]) is None
    assert postgres_db_real.get_eval_run(run_ids[1]) is None
    assert postgres_db_real.get_eval_run(run_ids[2]) is not None


def test_get_eval_runs_no_filters(postgres_db_real: PostgresDb):
    """Test getting all eval runs without filters"""
    # Create multiple eval runs
    eval_runs = []
    for i in range(3):
        eval_run = EvalRunRecord(
            run_id=f"test_eval_run_{i}",
            agent_id=f"test_agent_{i}",
            eval_type=EvalType.ACCURACY,
            eval_data={"score": 0.8 + (i * 0.05)},
            name=f"Test Eval {i}",
        )
        eval_runs.append(eval_run)
        postgres_db_real.create_eval_run(eval_run)

    result = postgres_db_real.get_eval_runs()

    assert isinstance(result, list)
    assert len(result) == 3
    assert all(isinstance(run, EvalRunRecord) for run in result)


def test_get_eval_runs_with_agent_filter(
    postgres_db_real: PostgresDb, sample_eval_run_agent: EvalRunRecord, sample_eval_run_team: EvalRunRecord
):
    """Test getting eval runs filtered by agent_id"""
    postgres_db_real.create_eval_run(sample_eval_run_agent)
    postgres_db_real.create_eval_run(sample_eval_run_team)

    result = postgres_db_real.get_eval_runs(agent_id="test_agent_1")

    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0].agent_id == "test_agent_1"


def test_get_eval_runs_with_team_filter(
    postgres_db_real: PostgresDb, sample_eval_run_agent: EvalRunRecord, sample_eval_run_team: EvalRunRecord
):
    """Test getting eval runs filtered by team_id"""
    postgres_db_real.create_eval_run(sample_eval_run_agent)
    postgres_db_real.create_eval_run(sample_eval_run_team)

    result = postgres_db_real.get_eval_runs(team_id="test_team_1")

    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0].team_id == "test_team_1"


def test_get_eval_runs_with_workflow_filter(postgres_db_real: PostgresDb, sample_eval_run_workflow: EvalRunRecord):
    """Test getting eval runs filtered by workflow_id"""
    postgres_db_real.create_eval_run(sample_eval_run_workflow)

    result = postgres_db_real.get_eval_runs(workflow_id="test_workflow_1")

    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0].workflow_id == "test_workflow_1"


def test_get_eval_runs_with_model_filter(
    postgres_db_real: PostgresDb, sample_eval_run_agent: EvalRunRecord, sample_eval_run_team: EvalRunRecord
):
    """Test getting eval runs filtered by model_id"""
    postgres_db_real.create_eval_run(sample_eval_run_agent)
    postgres_db_real.create_eval_run(sample_eval_run_team)

    result = postgres_db_real.get_eval_runs(model_id="gpt-4")

    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0].model_id == "gpt-4"


def test_get_eval_runs_with_eval_type_filter(
    postgres_db_real: PostgresDb, sample_eval_run_agent: EvalRunRecord, sample_eval_run_team: EvalRunRecord
):
    """Test getting eval runs filtered by eval_type"""
    postgres_db_real.create_eval_run(sample_eval_run_agent)
    postgres_db_real.create_eval_run(sample_eval_run_team)

    result = postgres_db_real.get_eval_runs(eval_type=[EvalType.ACCURACY])

    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0].eval_type == EvalType.ACCURACY


def test_get_eval_runs_with_filter_type(
    postgres_db_real: PostgresDb,
    sample_eval_run_agent: EvalRunRecord,
    sample_eval_run_team: EvalRunRecord,
    sample_eval_run_workflow: EvalRunRecord,
):
    """Test getting eval runs filtering by component type"""
    postgres_db_real.create_eval_run(sample_eval_run_agent)
    postgres_db_real.create_eval_run(sample_eval_run_team)
    postgres_db_real.create_eval_run(sample_eval_run_workflow)

    # Filter by agent
    agent_results = postgres_db_real.get_eval_runs(filter_type=EvalFilterType.AGENT)
    assert len(agent_results) == 1
    assert agent_results[0].agent_id is not None

    # Filter by team
    team_results = postgres_db_real.get_eval_runs(filter_type=EvalFilterType.TEAM)
    assert len(team_results) == 1
    assert team_results[0].team_id is not None

    # Filter by workflow
    workflow_results = postgres_db_real.get_eval_runs(filter_type=EvalFilterType.WORKFLOW)
    assert len(workflow_results) == 1
    assert workflow_results[0].workflow_id is not None


def test_get_eval_runs_with_pagination(postgres_db_real: PostgresDb):
    """Test getting eval runs with pagination"""
    # Create multiple eval runs
    for i in range(5):
        eval_run = EvalRunRecord(
            run_id=f"test_eval_run_{i}",
            agent_id=f"test_agent_{i}",
            eval_type=EvalType.ACCURACY,
            eval_data={"score": 0.8 + (i * 0.05)},
            name=f"Test Eval {i}",
        )
        postgres_db_real.create_eval_run(eval_run)

    # Test pagination
    page1 = postgres_db_real.get_eval_runs(limit=2, page=1)
    assert isinstance(page1, list)
    assert len(page1) == 2

    page2 = postgres_db_real.get_eval_runs(limit=2, page=2)
    assert isinstance(page2, list)
    assert len(page2) == 2

    # Verify no overlap
    page1_ids = {run.run_id for run in page1}
    page2_ids = {run.run_id for run in page2}
    assert len(page1_ids & page2_ids) == 0


def test_get_eval_runs_with_sorting(postgres_db_real: PostgresDb):
    """Test getting eval runs with sorting"""
    # Create eval runs with different timestamps by spacing them out
    eval_runs = []
    for i in range(3):
        eval_run = EvalRunRecord(
            run_id=f"test_eval_run_{i}",
            agent_id=f"test_agent_{i}",
            eval_type=EvalType.ACCURACY,
            eval_data={"score": 0.8 + (i * 0.05)},
            name=f"Test Eval {i}",
        )
        eval_runs.append(eval_run)
        postgres_db_real.create_eval_run(eval_run)
        time.sleep(0.1)  # Small delay to ensure different timestamps

    # Test default sorting (created_at desc)
    results = postgres_db_real.get_eval_runs()
    assert isinstance(results, list)
    assert len(results) == 3

    # Test explicit sorting by run_id ascending
    results_asc = postgres_db_real.get_eval_runs(sort_by="run_id", sort_order="asc")
    assert isinstance(results_asc, list)
    assert results_asc[0].run_id == "test_eval_run_0"
    assert results_asc[1].run_id == "test_eval_run_1"
    assert results_asc[2].run_id == "test_eval_run_2"


def test_get_eval_runs_without_deserialization(postgres_db_real: PostgresDb, sample_eval_run_agent: EvalRunRecord):
    """Test getting eval runs without deserialization"""
    postgres_db_real.create_eval_run(sample_eval_run_agent)

    result, total_count = postgres_db_real.get_eval_runs(deserialize=False)

    assert isinstance(result, list)
    assert len(result) == 1
    # result[0] is a RowMapping object, which behaves like a dict but isn't exactly a dict
    assert result[0]["run_id"] == sample_eval_run_agent.run_id
    assert total_count == 1


def test_rename_eval_run(postgres_db_real: PostgresDb, sample_eval_run_agent: EvalRunRecord):
    """Test renaming an eval run"""
    postgres_db_real.create_eval_run(sample_eval_run_agent)

    new_name = "Renamed Eval Run"
    result = postgres_db_real.rename_eval_run(sample_eval_run_agent.run_id, new_name)

    assert result is not None
    assert isinstance(result, EvalRunRecord)
    assert result.name == new_name
    assert result.run_id == sample_eval_run_agent.run_id


def test_rename_eval_run_without_deserialization(postgres_db_real: PostgresDb, sample_eval_run_agent: EvalRunRecord):
    """Test renaming an eval run without deserialization"""
    postgres_db_real.create_eval_run(sample_eval_run_agent)

    new_name = "Renamed Eval Run Dict"
    result = postgres_db_real.rename_eval_run(sample_eval_run_agent.run_id, new_name, deserialize=False)

    assert result is not None
    assert isinstance(result, dict)
    assert result["name"] == new_name
    assert result["run_id"] == sample_eval_run_agent.run_id


def test_eval_table_creation_and_structure(postgres_db_real: PostgresDb):
    """Test that the eval table is created with the correct structure"""
    eval_table = postgres_db_real._get_table("evals", create_table_if_not_found=True)

    assert eval_table is not None
    assert eval_table.name == "test_evals"
    assert eval_table.schema == postgres_db_real.db_schema

    # Verify essential columns exist
    column_names = [col.name for col in eval_table.columns]
    expected_columns = [
        "run_id",
        "agent_id",
        "team_id",
        "workflow_id",
        "model_id",
        "model_provider",
        "name",
        "evaluated_component_name",
        "eval_type",
        "eval_data",
        "created_at",
        "updated_at",
    ]
    for col in expected_columns:
        assert col in column_names, f"Missing column: {col}"


def test_comprehensive_eval_run_fields(postgres_db_real: PostgresDb):
    """Test that all EvalRunRecord fields are properly handled"""
    comprehensive_eval = EvalRunRecord(
        run_id="comprehensive_eval_run",
        agent_id="comprehensive_agent",
        model_id="gpt-4-comprehensive",
        model_provider="openai",
        name="Comprehensive Eval Test",
        evaluated_component_name="Comprehensive Agent",
        eval_type=EvalType.RELIABILITY,
        eval_data={
            "primary_score": 0.95,
            "secondary_metrics": {"latency": 150.0, "throughput": 45.2, "error_rate": 0.02},
            "test_conditions": {"environment": "production", "duration_minutes": 60, "concurrent_users": 100},
            "detailed_results": [
                {"test_id": "test_1", "score": 0.98, "category": "accuracy"},
                {"test_id": "test_2", "score": 0.92, "category": "speed"},
                {"test_id": "test_3", "score": 0.95, "category": "reliability"},
            ],
        },
    )

    # Create the eval run
    result = postgres_db_real.create_eval_run(comprehensive_eval)
    assert result is not None

    # Retrieve and verify all fields are preserved
    retrieved = postgres_db_real.get_eval_run(comprehensive_eval.run_id)
    assert retrieved is not None
    assert isinstance(retrieved, EvalRunRecord)

    # Verify all fields
    assert retrieved.run_id == comprehensive_eval.run_id
    assert retrieved.agent_id == comprehensive_eval.agent_id
    assert retrieved.model_id == comprehensive_eval.model_id
    assert retrieved.model_provider == comprehensive_eval.model_provider
    assert retrieved.name == comprehensive_eval.name
    assert retrieved.evaluated_component_name == comprehensive_eval.evaluated_component_name
    assert retrieved.eval_type == comprehensive_eval.eval_type
    assert retrieved.eval_data == comprehensive_eval.eval_data
