# Invoice Extraction Agent

This agent automates invoice processing by extracting structured data from PDF invoices. It uses a three-agent team (parser, extractor, validator) powered by Gemini to convert raw invoice PDFs into normalized JSON with fields like invoice number, dates, vendor information, line items, and totals. Ideal for accounts payable automation, expense tracking, and invoice data integration workflows.

See Agno cookbook for more patterns and examples: `https://github.com/agno-agi/agno/tree/main/cookbook`.

## Quickstart

1) Install
```
pip install -r requirements.txt
```

2) Env
```
GOOGLE_API_KEY=<your_key>
# Optional: place in .env at project root
```

3) Run
```
python main.py
```

4) Use
- To use Agno OS, go to os.agno.com and create an account
- In the UI, click on "Create your OS" and add your localhost endpoint
- All of your agents and teams will appear on the home page

Workflow: `parser-agent` → `extractor-agent` → `validator-agent`. The response is validated JSON.

Example response shape:
```
{
  "invoice_number": "INV-1042",
  "issue_date": "2024-08-15",
  "vendor_name": "Acme Inc",
  "billing_name": "Contoso Ltd",
  "currency": "USD",
  "subtotal": 1200.0,
  "tax_amount": 96.0,
  "total_amount": 1296.0,
  "line_items": [
    {"description": "Widget A", "quantity": 2, "unit_price": 300.0, "total": 600.0}
  ],
  "notes": null
}
```

## Files
- main.py: Team and AgentOS app
- agents.py: Member agents (parser, extractor, validator)
- tmp/teams.db: SQLite session DB

## Notes
- Uses AgentOS standard endpoints and UI; see cookbook reference above for endpoint patterns and examples: `https://github.com/agno-agi/agno/tree/main/cookbook`.
