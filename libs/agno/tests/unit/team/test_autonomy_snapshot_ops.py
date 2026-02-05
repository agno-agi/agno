from agno.team.autonomy.snapshot_ops import pause_job_snapshot, resume_job_snapshot


def test_pause_and_resume_job_snapshot_resets_running_steps():
    snapshot = {
        "job_id": "job_1",
        "status": "running",
        "steps": [
            {"step_id": "s1", "status": "completed"},
            {"step_id": "s2", "status": "running"},
        ],
    }

    pause_job_snapshot(snapshot, reason="hitl", gate_type="plan_approval", payload={"foo": "bar"}, now=123)
    assert snapshot["status"] == "paused"
    assert snapshot["pause"]["reason"] == "hitl"
    assert snapshot["pause"]["gate_type"] == "plan_approval"
    assert snapshot["pause"]["payload"]["foo"] == "bar"
    assert snapshot["updated_at"] == 123

    resume_job_snapshot(snapshot, now=456)
    assert snapshot["status"] == "running"
    assert snapshot["pause"] is None
    assert snapshot["steps"][1]["status"] == "pending"
    assert snapshot["updated_at"] == 456

