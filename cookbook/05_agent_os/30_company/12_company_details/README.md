# Company details

`CompanyConfig(name="Acme", description="What Acme does")` sets the singleton company at startup. There is always one row: changing the configuration updates it until someone edits it through the API, and after that edits survive deployment and the configuration is no longer applied. The Company database and its configured Product table name define the scope; the details table is named `<products_table>_details`. Existing installations default to `Company` without a description.

`GET /company/details` requires `company:read`. `PATCH /company/details` requires `company:write`, and the admin scope bypasses it as usual; managers have no company-details write tool. Pass `expected_updated_at` from the last read with the changed `name` or `description`. A concurrent edit returns 409. Reload and reconcile your changes before retrying. `description: null` clears it.

Super Agent and Company Manager read current details on each authorized run. The playbook remains the home for longer guidance. Use `company:read` with the relevant manager run permission to include company context.

Run the offline database example against a disposable PostgreSQL database:

```bash
DATABASE_URL=postgresql+psycopg://ai:ai@localhost:5532/ai .venv/bin/python cookbook/05_agent_os/30_company/12_company_details/company_details.py
```
