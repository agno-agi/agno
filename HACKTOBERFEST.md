Hacktoberfest contribution: truncate_middle utility

What I added
- New utility: `agno.utils.string.truncate_middle(input_string, max_length)` — truncates long strings with an ellipsis in the middle while preserving start/end segments.
- Unit tests added in: `libs/agno/tests/unit/utils/test_string.py` (several small tests covering behavior).

Files changed
- libs/agno/agno/utils/string.py  (added `truncate_middle`)
- libs/agno/tests/unit/utils/test_string.py  (added tests)

- libs/agno/agno/session/exporter.py (added `export_session_to_dict`, `export_session_to_json`, `export_session_to_markdown`)
- libs/agno/tests/unit/session/test_exporter.py (added tests)

Why this is a good first contribution
- Small, self-contained change with unit tests
- Low risk: pure-Python helper function, no external dependencies

How to run the tests locally (Windows PowerShell)
1. Create and activate a virtual environment:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

2. Install dev dependencies (recommended):

```powershell
pip install -e libs/agno[dev]
pip install pytest
```

3. Run the new tests only:

```powershell
py -3 -m pytest libs/agno/tests/unit/utils/test_string.py -k truncate_middle -q
```

Notes about CI/test-run issues
- When I attempted to run pytest in the current environment, pytest loaded an installed pytest plugin named `langsmith` which caused import-time errors (Pydantic v1/v2 forward-ref issue). To avoid this, run the tests in a clean virtualenv (see steps above) or uninstall the conflicting plugin from your environment: `pip uninstall langsmith`.

What you can do next
- Run the tests locally using the commands above.
- Create a branch, commit the changes if you'd like to iterate, and open a PR to `main` with the contribution label for Hacktoberfest.

Session exporter usage (example):

```python
from agno.session.agent import AgentSession
from agno.session.exporter import export_session_to_json, export_session_to_markdown

# assume `session` is an AgentSession object retrieved from storage
json_str = export_session_to_json(session)
md = export_session_to_markdown(session)

# write to files
export_session_to_json(session, path="/tmp/session_s1.json")
export_session_to_markdown(session, path="/tmp/session_s1.md")
```

If you want, I can:
- Open a local branch and prepare a commit message for you to push (I can generate the git commands), or
- Add a small README note inside `libs/agno` describing the helper API.

Happy Hacktoberfest! 🎉

Demo run (actual output)

Run the demo script to see the JSON and Markdown exports printed and written to `tmp_export/`:

```powershell
py -3 demo/session_export_demo.py
```

Observed output (trimmed for clarity):

--- JSON Export (pretty) ---
{
	"session_id": "s1",
	"agent_id": "agent1",
	"team_id": null,
	"user_id": "user1",
	"workflow_id": null,
	"session_data": {
		"key": "value"
	},
	"runs": [
		{
			"run_id": "r1",
			"agent_id": "agent1",
			"session_id": "s1",
			"content": "response text",
			"content_type": "str",
			"created_at": 1760345278,
			"status": "RUNNING",
			"messages": [
				{"content": "hello", "role": "user"},
				{"content": "world", "role": "assistant"}
			]
		}
	],
	"summary": {"summary": "short summary"}
}

Wrote JSON to: C:\\Users\\Asus\\agno\\tmp_export\\session_s1.json

--- Markdown Export ---
# Session s1
- Agent: `agent1`
- User: `user1`

## Summary

short summary

## Runs

### Run 1 — r1 — RunStatus.running
**user**: hello
**assistant**: world

Wrote Markdown to: C:\\Users\\Asus\\agno\\tmp_export\\session_s1.md
