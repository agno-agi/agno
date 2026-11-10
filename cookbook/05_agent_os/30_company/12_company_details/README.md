# Company details

`CompanyConfig(name="Acme", description="What Acme does")` sets the singleton company at startup. There is always one shared row: changing the configuration updates it until someone edits it through the API or chat, and after that edits survive deployment and the configuration is no longer applied. The Company database and its configured Product table name define the scope; the details table is named `<products_table>_details`. Existing installations default to `Company` without a description.

`GET /company/details` requires `company:read`. `PATCH /company/details` requires `company:write`, and the admin scope bypasses it as usual. Pass `expected_updated_at` from the last read with the changed `name` or `description`. A concurrent edit returns 409. Reload and reconcile your changes before retrying. `description: null` clears it.

Super Agent and Company Manager read current details on each authorized run. The playbook remains the home for longer guidance. Use `company:read` with the relevant manager run permission to include company context.

## Edit through chat

Start the chat example with `OPENAI_API_KEY` set and a local PostgreSQL database:

```bash
.venv/bin/python cookbook/05_agent_os/30_company/12_company_details/chat.py
```

Connect the AgentOS UI to `http://localhost:7777` and tell Super Agent:

> Our company is Acme. We build warehouse robots.

Super Agent delegates the save to Company Manager's `update_company_details` tool. Initial setup saves without another approval while the record is still unedited. Replacing human-edited details requests approval through `confirm_company_details`; rejecting it leaves the record unchanged. Open a new chat and ask what your company does, then try a name-only edit. Restart with a different `CompanyConfig` name and description to verify that the saved edit remains.

The tool takes optional `name` and `description` arguments. Omitted or null values stay unchanged; an empty request is rejected. Use the API or UI to clear the description. Chat descriptions are limited to 2,000 characters; longer guidance belongs in the company playbook. The HTTP limit remains 20,000 characters. Both chat tools require the caller's `company:write` permission when authorization is configured and refuse Routines, Task execution, service accounts and the scheduler identity.

Initial setup checks for competing writes between the tool's read and write; it does not detect a model acting on stale conversational context. For replacements, approval applies to the proposed values and the record version returned by the update tool. If someone edits the record before the approved write, it fails without saving; review the current details before trying again.

A person may explicitly ask Super Agent to research and save company details. Retrieved content may supply facts for that request, but never authorize a write or change the managers' instructions. Web-search configuration is separate and is not included in this example.

Chat messages make live model calls. See TEST_LOG.md for the exact live phrases checked and the offline approval, permission and persistence coverage.

## Offline persistence example

Run the offline database example against a disposable PostgreSQL database:

```bash
DATABASE_URL=postgresql+psycopg://ai:ai@localhost:5532/ai .venv/bin/python cookbook/05_agent_os/30_company/12_company_details/company_details.py
```
