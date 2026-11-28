# context management

Examples for team workflows in context_management.

## Prerequisites

- Load environment variables (for example, OPENAI_API_KEY) via direnv allow.
- Use .venvs/demo/bin/python to run cookbook examples.
- Some examples require additional services (for example PostgreSQL, LanceDB, or Infinity server) as noted in file docstrings.

## Files

- few_shot_learning.py - Demonstrates few shot learning.
- filter_tool_calls_from_history.py - Demonstrates filter tool calls from history.
- introduction.py - Demonstrates introduction.
- additional_context.py - Demonstrates additional_context and resolve_in_context.
- custom_system_message.py - Demonstrates custom system message and system message role.
- datetime_format.py - Demonstrates custom datetime format in team context.
- location_context.py - Demonstrates location and timezone context.
- compaction/team_compaction.py - Keep a long conversation with a Team in the context window with `compaction`, and fold now with `team.compact()`.
- compaction/team_compaction_events.py - Stream `TeamCompactionStarted` / `TeamCompactionCompleted` and show what was reclaimed.
- compaction/team_compaction_searchable_archive.py - Let the team leader search the history that was compacted away.
- compaction/team_compaction_members.py - Compact a member's own history with a `compaction` on the member.
