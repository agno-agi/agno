"""Test the PostgresDb class."""

from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from agno.db.postgres.postgres import PostgresDb

# -- Test metrics calculation --


@patch("agno.db.postgres.postgres.select")
def test_get_metrics_calculation_starting_date_no_metrics_records(mock_db_select):
    """Test _get_metrics_calculation_starting_date when:

    - No metrics records exist
    - Session records exist
    """
    db, table, session = MagicMock(), MagicMock(), MagicMock()
    session_record_date = date(2024, 1, 1)
    db.Session.return_value.__enter__.return_value = session
    db.Session.return_value.__exit__.return_value = None
    session.execute.return_value.fetchone.return_value = None
    db.get_first_session_date.return_value = datetime.combine(session_record_date, datetime.min.time()).timestamp()

    result = PostgresDb._get_metrics_calculation_starting_date(db, table)

    assert result == session_record_date


@patch("agno.db.postgres.postgres.select")
def test_get_metrics_calculation_starting_date_no_records(mock_db_select):
    """Test _get_metrics_calculation_starting_date when:

    - No metrics records exist
    - No session records exist
    """
    db, table, session = MagicMock(), MagicMock(), MagicMock()
    db.Session.return_value.__enter__.return_value = session
    db.Session.return_value.__exit__.return_value = None
    session.execute.return_value.fetchone.return_value = None
    db.get_first_session_date.return_value = None

    result = PostgresDb._get_metrics_calculation_starting_date(db, table)

    assert result is None


@patch("time.time")
def test_calculate_date_metrics_completed_flag_past_date(mock_time):
    """Test the completed flag is set to True for past dates"""
    mock_time.return_value = 1234567890
    db = MagicMock(spec=PostgresDb)
    test_date = datetime.now(timezone.utc).date() - timedelta(days=1)
    sessions_data = {}

    result = PostgresDb._calculate_date_metrics(db, test_date, sessions_data)

    assert result["completed"] is True
    assert result["created_at"] == 1234567890


@patch("time.time")
def test_calculate_date_metrics_completed_flag_today(mock_time):
    """Test the completed flag is set to False for today"""
    mock_time.return_value = 1234567890
    db = MagicMock(spec=PostgresDb)
    test_date = datetime.now(timezone.utc).date()
    sessions_data = {}

    result = PostgresDb._calculate_date_metrics(db, test_date, sessions_data)

    assert result["completed"] is False
    assert result["created_at"] == 1234567890


def test_calculate_date_metrics_with_multiple_session_types():
    """Test metrics calculation handles aggregation for multiple session types"""
    db = MagicMock(spec=PostgresDb)
    test_date = date(2024, 1, 1)
    agent_input_tokens, team_input_tokens, workflow_input_tokens = 1, 2, 3
    sessions_data = {
        "agent": [
            {
                "user_id": "user1",
                "runs": [{"run1": "data"}],
                "session_data": {"session_metrics": {"input_tokens": agent_input_tokens}},
            }
        ],
        "team": [
            {
                "user_id": "user2",
                "runs": [{"run1": "data"}],
                "session_data": {"session_metrics": {"input_tokens": team_input_tokens}},
            }
        ],
        "workflow": [
            {
                "user_id": "user3",
                "runs": [{"run1": "data"}],
                "session_data": {"session_metrics": {"input_tokens": workflow_input_tokens}},
            }
        ],
    }

    result = PostgresDb._calculate_date_metrics(db, test_date, sessions_data)

    assert result["users_count"] == 3
    assert result["agent_sessions_count"] == 1
    assert result["team_sessions_count"] == 1
    assert result["workflow_sessions_count"] == 1
    assert result["agent_runs_count"] == 1
    assert result["team_runs_count"] == 1
    assert result["workflow_runs_count"] == 1
    assert result["token_metrics"]["input_tokens"] == agent_input_tokens + team_input_tokens + workflow_input_tokens


def test_calculate_date_metrics_token_metrics():
    """Test all expected token metrics fields are handled when calculating metrics"""
    db = MagicMock(spec=PostgresDb)
    test_date = date(2024, 1, 1)
    sessions_data = {
        "agent": [
            {
                "user_id": "user1",
                "runs": [],
                "session_data": {
                    "session_metrics": {
                        "input_tokens": 1,
                        "output_tokens": 2,
                        "total_tokens": 3,
                        "audio_tokens": 4,
                        "input_audio_tokens": 5,
                        "output_audio_tokens": 6,
                        "cached_tokens": 7,
                        "cache_write_tokens": 8,
                        "reasoning_tokens": 9,
                    }
                },
            }
        ]
    }

    result = PostgresDb._calculate_date_metrics(db, test_date, sessions_data)

    token_metrics = result["token_metrics"]
    assert token_metrics["input_tokens"] == 1
    assert token_metrics["output_tokens"] == 2
    assert token_metrics["total_tokens"] == 3
    assert token_metrics["audio_tokens"] == 4
    assert token_metrics["input_audio_tokens"] == 5
    assert token_metrics["output_audio_tokens"] == 6
    assert token_metrics["cached_tokens"] == 7
    assert token_metrics["cache_write_tokens"] == 8
    assert token_metrics["reasoning_tokens"] == 9


def test_calculate_date_metrics_duplicate_users():
    """Test that duplicate users are counted only once"""
    db = MagicMock(spec=PostgresDb)
    test_date = date(2024, 1, 1)
    sessions_data = {
        "agent": [{"user_id": "user1", "runs": [], "session_data": {"session_metrics": {}}}],
        "team": [
            {
                "user_id": "user1",  # Same user
                "runs": [],
                "session_data": {"session_metrics": {}},
            }
        ],
        "workflow": [{"user_id": "user2", "runs": [], "session_data": {"session_metrics": {}}}],
    }

    result = PostgresDb._calculate_date_metrics(db, test_date, sessions_data)

    assert result["users_count"] == 2  # user1 and user2
    assert result["agent_sessions_count"] == 1
    assert result["team_sessions_count"] == 1
    assert result["workflow_sessions_count"] == 1


def test_get_dates_to_calculate_metrics():
    """Test happy path for _get_dates_to_calculate_metrics_for"""
    db = MagicMock(spec=PostgresDb)
    starting_date = datetime.now(timezone.utc).date() - timedelta(days=2)

    result = PostgresDb._get_dates_to_calculate_metrics_for(db, starting_date)

    expected = [
        datetime.now(timezone.utc).date() - timedelta(days=2),
        datetime.now(timezone.utc).date() - timedelta(days=1),
        datetime.now(timezone.utc).date(),
    ]
    assert result == expected


def test_get_dates_to_calculate_metrics_if_starting_date_is_today():
    """Test _get_dates_to_calculate_metrics_for if starting_date is today"""
    db = MagicMock(spec=PostgresDb)
    starting_date = datetime.now(timezone.utc).date()

    result = PostgresDb._get_dates_to_calculate_metrics_for(db, starting_date)

    assert result == [datetime.now(timezone.utc).date()]
