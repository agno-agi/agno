# Test log

### background_conversation.py

**Status:** PASS

**Description:** Actual Company/conversation APIs and PostgreSQL durable queue in a disposable schema, using an offline deterministic model. An accepted Task starts in a separate session; status and an unrelated coordinator turn complete while its worker waits. The worker then completes with its origin retained.

**Result:** 202 coordinator receipt, separate durable Task/run identifiers, responsive conversation, and Task in review. No model provider, live Slack, or production account was used.

---

### Conversation API and storage regressions

**Status:** PASS

**Description:** `test_company_conversation.py` and `test_company_conversation_associations.py` exercise PostgreSQL intake/queue/restart, session serialization, authorization and revocation, disabled users, concurrent first-owner claims, deterministic worker-session collision prevention, caller isolation, duplicate receipt after queue retention, recovery after Task projection failure, and multiple concurrent conversations joining one Task attempt. SQLite, async SQLite, PostgreSQL, and async PostgreSQL all retain origins atomically.

**Result:** 26 passed; 3 redundant parameter combinations skipped because their authenticated/unauthenticated counterpart covers that case. Controlled local evidence; hosted replicas and paid model behavior remain untested.
