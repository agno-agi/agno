# Test Log — 05_state_and_session

Tested: 2026-02-12 | Branch: cookbook/v25-merge-fixes

| File | Status | Notes |
|------|--------|-------|
| agentic_session_state.py | PASS | Shopping list via update_session_state tool, add/remove items across runs |
| chat_history.py | PASS | Multi-turn chat history with space facts, persists across sessions |
| dynamic_session_state.py | PASS | Dynamic session state with customer create/retrieve, hooks log state changes |
| last_n_session_messages.py | PASS | Multi-user session isolation, user 2 only sees own history (currency/population) |
| persistent_session.py | PASS | Persistent session with SQLite, space facts across multiple runs |
| session_options.py | PASS | Session options: use_history + scrub_history, verifies stored vs used messages |
| session_state_advanced.py | PASS | Advanced session state with shopping list: add, remove, clear, replace operations |
| session_state_basic.py | PASS | Basic session state with shopping list add_item tool |
| session_state_events.py | PASS | Session state events, shopping list updated via tools |
| session_state_manual_update.py | PASS | Manual session state update (add chocolate), persists across runs |
| session_state_multiple_users.py | PASS | Multi-user session state isolation, 3 users with separate shopping lists |
| session_summary.py | PASS | Session summary generated after multi-turn conversation about hobbies |
