# Company AgentOS Servers

One servable AgentOS for each Company cookbook in the parent folder. The parent
scripts exercise Company in a temporary database and exit; these keep the same
setup running on http://localhost:7777 with seeded records, so you can work
with them over HTTP, MCP or the AgentOS UI at https://os.agno.com.

| File | Serves | Needs |
| --- | --- | --- |
| `01_manage_products.py` | Alice's and Bob's Products for owner filters, archive and restore | SQLite |
| `02_manage_projects.py` | A done Project and a proposed Project awaiting acceptance | SQLite |
| `03_manage_tasks.py` | Backlog Tasks and a `writer` agent to accept them for | SQLite |
| `04_manage_playbook.py` | A Product status page and decision log | SQLite |
| `05_product_manager.py` | Product Manager chat and MCP, with an `intake-reader` | SQLite |
| `06_execute_tasks.py` | The durable queue and scheduler with a local `draft` workflow | PostgreSQL |
| `07_cascading_archive.py` | A Product whose accepted Task blocks archiving | SQLite |
| `07_heartbeat.py` | A weekday intake Routine over a local markdown Source | SQLite |
| `08_custom_routines.py` | A template-free Routine for a `researcher` agent | SQLite |
| `09_sandboxed_engineers.py` | Claude and Codex engineers in Docker sandboxes | PostgreSQL, Redis, Docker |
| `09_task_session_ownership.py` | JWT-authorized Alice and Bob sharing one Task session | PostgreSQL |

Run one at a time from the repository root:

```bash
.venv/bin/python cookbook/05_agent_os/30_company/agent_os/01_manage_products.py
```

Each file's docstring lists requests to try. Seeding runs once: delete the
`tmp/company_*` database, or the PostgreSQL schema, to start fresh.
Product Manager chat needs `OPENAI_API_KEY`. Start PostgreSQL with
`./cookbook/scripts/run_pgvector.sh`.

Only `09_task_session_ownership.py` enables authorization; it prints bearer
tokens for Alice and Bob. If `JWT_VERIFICATION_KEY` or `AGNO_SECURITY_KEY`
is set in your shell, the other servers require it too. Unset them for local use.
