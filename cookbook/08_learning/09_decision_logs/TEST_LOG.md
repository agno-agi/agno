# Test Log: 09_decision_logs

> Tested 2026-07-25 against gpt-5.5 (OpenAIResponses), branch feat/entity-memory-revamp.
> Decision logging is AGENTIC-only in 2.8.4; the old 02_decision_log_always.py showcased
> the deleted contentless-row extraction and is replaced by 02_record_outcomes.py.

### 01_basic_decision_log.py

**Status:** PENDING

**Description:** Basic log_decision / search_decisions flow.

**Result:** Not re-run in this pass (unchanged API surface; the store default is now
AGENTIC, which this file already used implicitly through LearningMachine).

---

### 02_record_outcomes.py

**Status:** PASS

**Description:** log_decision in one session, record_outcome in a later one.

**Result:** The Postgres-vs-DynamoDB recommendation was logged with full reasoning; the
follow-up session searched, found the decision id and recorded outcome "migration went
smoothly" with quality good. Honest note: on the first run the agent logged a meta-decision
asking for the id instead of searching - the instructions now say search first, never ask
for an id, and the re-run recorded the outcome correctly.

---
