from __future__ import annotations

from typing import Any, Dict, List, Optional

SESSION_STATE_JOBS_KEY = "agno.autonomy.jobs"
SESSION_STATE_LATEST_JOB_ID_KEY = "agno.autonomy.latest_job_id"


def get_jobs_from_session_state(session_state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    jobs = session_state.get(SESSION_STATE_JOBS_KEY)
    if jobs is None or not isinstance(jobs, dict):
        jobs = {}
        session_state[SESSION_STATE_JOBS_KEY] = jobs
    return jobs  # type: ignore[return-value]


def list_job_ids_from_session_state(session_state: Dict[str, Any]) -> List[str]:
    jobs = session_state.get(SESSION_STATE_JOBS_KEY)
    if not isinstance(jobs, dict):
        return []
    return [k for k in jobs.keys() if isinstance(k, str)]


def get_latest_job_id_from_session_state(session_state: Dict[str, Any]) -> Optional[str]:
    latest = session_state.get(SESSION_STATE_LATEST_JOB_ID_KEY)
    if isinstance(latest, str) and latest.strip():
        return latest
    return None


def get_job_snapshot_from_session_state(session_state: Dict[str, Any], job_id: str) -> Optional[Dict[str, Any]]:
    jobs = session_state.get(SESSION_STATE_JOBS_KEY)
    if not isinstance(jobs, dict):
        return None
    snapshot = jobs.get(job_id)
    return snapshot if isinstance(snapshot, dict) else None


def put_job_snapshot_in_session_state(session_state: Dict[str, Any], snapshot: Dict[str, Any]) -> None:
    job_id = snapshot.get("job_id")
    if not isinstance(job_id, str) or not job_id.strip():
        raise ValueError("Job snapshot must include a non-empty 'job_id'")

    jobs = get_jobs_from_session_state(session_state)
    jobs[job_id] = snapshot
    session_state[SESSION_STATE_LATEST_JOB_ID_KEY] = job_id

