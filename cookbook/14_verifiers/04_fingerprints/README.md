# 04_fingerprints

Ending runs whose failed attempts change nothing.

## Files

- `unchanged_state_guard.py`: `GitWorktreeFingerprint` with `stop_on_unchanged_state=True` ends the run of an agent that cannot write with stop reason `"unchanged_state"`.
- `callable_fingerprint.py`: `CallableFingerprint` over an in-memory ledger; a failed attempt that changed state keeps the loop going.
