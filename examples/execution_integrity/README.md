# Execution Integrity Example

This is an optional example demonstrating tamper-evident execution traces.

## Run
python3 demo.py
python3 verify_export.py execution_log.json

Expected:
- Verification before tamper: True
- Verification after tamper: False
- EXPORT_VERIFY: PASS

No dependencies. No changes to core logic.
