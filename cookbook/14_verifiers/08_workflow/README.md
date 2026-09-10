# Workflow

- `verify_step.py` — `Verify` as a workflow step: run agents, verify, continue. On failure the segment from `on_fail` re-runs with the evidence report attached to its input; rounds exhausted, the step ends `success=False` with the record on its `StepOutput` for the workflow's conditional machinery to route. With `stop_when_unverified=True` an unverified end halts the pipeline outright instead of continuing to the next step.
