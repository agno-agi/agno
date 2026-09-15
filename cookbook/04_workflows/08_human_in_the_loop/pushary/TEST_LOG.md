# Pushary workflow check log

### check_run.py

**Status:** PASS

**Description:** Python 3.12.12, Agno 3.0.9, Pushary 2.1.1, SQLAlchemy 2.0.53. Ran `.venvs/demo/bin/python cookbook/04_workflows/08_human_in_the_loop/pushary/check_run.py` on 2026-09-15.

**Result:** Real native HumanReview pause, SQLite reload in fresh workers and native continuation passed. Checks also passed for pending/refused/expired/cancelled decisions, changed identities and order, duplicate workers, lost permit response, expiry after permit use, process crash after the effect and direct native-confirm bypass. Only the Pushary HTTP transport was simulated. The deliberate bypass emits an expected permission warning and releases no order. No live phone delivery or model-provider execution was tested.
