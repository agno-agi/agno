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

Super Agent's coordination instructions delegate the company's name and description to Company Manager. Company Manager is instructed to use `update_company_details` when the person states their company's name or what it does, or asks to change either. The tool description distinguishes statements about another organization from a request to save; that disambiguation is not repeated in the system prompts. Products and Routines are created only when the person asks for them.

Initial setup saves without another approval while the record is still unedited. Replacing human-edited details requests approval through `confirm_company_details`; rejecting it leaves the record unchanged. Open a new chat and ask what your company does, then try a name-only edit. Restart with a different `CompanyConfig` name and description to verify that the saved edit remains.

The tool takes optional `name` and `description` arguments. Omitted or null values stay unchanged; an empty request is rejected. Use the API or UI to clear the description. Chat descriptions are limited to 2,000 characters; longer guidance belongs in the company playbook. The HTTP limit remains 20,000 characters. Both chat tools require the caller's `company:write` permission when authorization is configured and refuse Routines, Task execution, service accounts and the scheduler identity.

Initial setup checks for competing writes between the tool's read and write; it does not detect a model acting on stale conversational context. For replacements, approval applies to the proposed values and the record version returned by the update tool. If someone edits the record before the approved write, it fails without saving; review the current details before trying again.

A person may explicitly ask Super Agent to research and save company details. The tool description allows facts from requested research and states that text in Sources and tool results is not a request to save. Company details remain reference data, not instructions. Web-search configuration is separate and is not included in this example.

Chat messages make live model calls. The three live results in TEST_LOG.md were recorded against `c346e021b0`, before the prompt rewrite in `97cdd12a87`. They do not verify the current prompts; a paid rerun requires approval. The log also records the earlier offline approval, permission and persistence coverage.

## Offline persistence example

Run the offline database example against a disposable PostgreSQL database:

```bash
DATABASE_URL=postgresql+psycopg://ai:ai@localhost:5532/ai .venv/bin/python cookbook/05_agent_os/30_company/12_company_details/company_details.py
```
