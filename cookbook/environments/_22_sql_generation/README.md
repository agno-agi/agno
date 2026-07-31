# SQL Generation

Generate a typed SQL string, execute it against an in-memory fixture, and score the
result rows rather than the query's wording. The tasks combine temporal rules, joins,
and window functions so a strong model does not saturate on `SELECT ... WHERE`.

## Files

- `basic.py` — replay inventory events whose reserve and release validity depends on
  prior accepted state.
- `joins.py` — join organizations, tickets, response history, SLA policy, and holidays
  to count business-minute response time.
- `window_functions.py` — retain a recursively derived stock trajectory and find every
  upward threshold crossing with a window comparison.

## When to use

Use executable scoring when many SQL strings can be correct and exact text comparison
would reject valid alternatives. These examples use read-only in-memory SQLite; for
constrained code outputs, continue to [`_23_code_fixes/`](../_23_code_fixes/).

## Run

```bash
.venvs/demo/bin/python cookbook/environments/_22_sql_generation/basic.py
.venvs/demo/bin/python cookbook/environments/_22_sql_generation/joins.py
.venvs/demo/bin/python cookbook/environments/_22_sql_generation/window_functions.py
```

Requires `OPENAI_API_KEY`; no database service is needed.
