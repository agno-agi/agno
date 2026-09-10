# Basics

- `verify_done.py` — a callable verifier as the definition of done; the evidence report drives a continuation inside the same run.
- `unverified.py` — a run whose checks never pass ends `RunStatus.unverified`; the record persists with the run row.
- `streamed.py` — `VerificationStarted` / `VerificationCompleted` events render the loop live.
