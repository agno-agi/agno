import pytest

from agno.team.autonomy.session_store import (
    SESSION_STATE_JOBS_KEY,
    SESSION_STATE_LATEST_JOB_ID_KEY,
    get_job_snapshot_from_session_state,
    get_jobs_from_session_state,
    get_latest_job_id_from_session_state,
    list_job_ids_from_session_state,
    put_job_snapshot_in_session_state,
)


def test_get_jobs_from_session_state_initializes_container():
    session_state = {}
    jobs = get_jobs_from_session_state(session_state)
    assert jobs == {}
    assert SESSION_STATE_JOBS_KEY in session_state
    assert session_state[SESSION_STATE_JOBS_KEY] == {}


def test_put_and_get_job_snapshot_roundtrip():
    session_state = {}
    snapshot = {"job_id": "job_1", "goal": "do something", "status": "pending"}

    put_job_snapshot_in_session_state(session_state, snapshot)

    assert session_state[SESSION_STATE_LATEST_JOB_ID_KEY] == "job_1"
    assert get_latest_job_id_from_session_state(session_state) == "job_1"

    restored = get_job_snapshot_from_session_state(session_state, "job_1")
    assert restored is not None
    assert restored["goal"] == "do something"


def test_list_job_ids_from_session_state():
    session_state = {}
    put_job_snapshot_in_session_state(session_state, {"job_id": "job_a"})
    put_job_snapshot_in_session_state(session_state, {"job_id": "job_b"})

    job_ids = list_job_ids_from_session_state(session_state)
    assert set(job_ids) == {"job_a", "job_b"}


def test_put_job_snapshot_requires_job_id():
    session_state = {}
    with pytest.raises(ValueError):
        put_job_snapshot_in_session_state(session_state, {"goal": "missing job_id"})
