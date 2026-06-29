"""
Compliance Agent with Strale
==============================
An agent that verifies businesses and screens for compliance risks
using Strale's 250+ quality-scored API capabilities.

This example shows how to create custom tools that call Strale's REST API
for company verification, sanctions screening, and financial validation.

Example prompts to try:
- "Verify Swedish company 556703-7485"
- "Check if Sberbank is on any sanctions lists"
- "Validate IBAN DE89370400440532013000"
- "Run a full compliance check on UK company 08804411"

Requirements:
    pip install agno straleio
    export STRALE_API_KEY=sk_live_...  # get at https://strale.dev/signup
    export GOOGLE_API_KEY=...          # or use any supported model
"""

import os
from typing import Optional

from agno.agent import Agent
from agno.models.google import Gemini
from agno.tools import tool

# ---------------------------------------------------------------------------
# Strale API tools (using straleio SDK)
# ---------------------------------------------------------------------------

STRALE_API_KEY = os.environ.get("STRALE_API_KEY", "")

try:
    from straleio import Strale

    strale = Strale(api_key=STRALE_API_KEY) if STRALE_API_KEY else None
except ImportError:
    strale = None


@tool
def validate_iban(iban: str) -> str:
    """Validate an IBAN number — checks format, length, and mod-97 checksum.
    Returns country code, bank code, and whether the IBAN is valid.
    Free tier: works without an API key."""
    if not strale:
        return "Error: pip install straleio and set STRALE_API_KEY"
    result = strale.do("iban-validate", {"iban": iban})
    o = result.get("output", result)
    return f"IBAN: {iban}\nValid: {o.get('valid')}\nCountry: {o.get('country_code')}\nBank: {o.get('bank_code')}"


@tool
def validate_vat(vat_number: str) -> str:
    """Validate a European VAT number against the EU VIES system.
    Returns whether the VAT is valid and the registered company name."""
    if not strale:
        return "Error: pip install straleio and set STRALE_API_KEY"
    result = strale.do("vat-validate", {"vat_number": vat_number})
    o = result.get("output", result)
    return f"VAT: {vat_number}\nValid: {o.get('valid')}\nCompany: {o.get('company_name', 'N/A')}"


@tool
def lookup_company(country: str, company_id: str) -> str:
    """Look up a company in official government registries.
    Supports 27 countries: SE, NO, DK, FI, UK, DE, FR, US, AU, etc.
    Pass the country code and registration/org number."""
    if not strale:
        return "Error: pip install straleio and set STRALE_API_KEY"
    slug_map = {
        "SE": "swedish-company-data",
        "NO": "norwegian-company-data",
        "DK": "danish-company-data",
        "FI": "finnish-company-data",
        "UK": "uk-company-data",
        "GB": "uk-company-data",
        "US": "us-company-data",
        "DE": "german-company-data",
        "FR": "french-company-data",
        "AU": "australian-company-data",
    }
    slug = slug_map.get(country.upper(), f"{country.lower()}-company-data")
    input_key = "company_number" if country.upper() in ("UK", "GB") else "org_number"
    if country.upper() == "US":
        input_key = "company"
    result = strale.do(slug, {input_key: company_id})
    o = result.get("output", result)
    name = o.get("company_name", o.get("name", "Unknown"))
    status = o.get("status", o.get("company_status", "Unknown"))
    return f"Company: {name}\nStatus: {status}\nCountry: {country}\nID: {company_id}"


@tool
def check_sanctions(name: str, country: Optional[str] = None) -> str:
    """Screen a person or company against international sanctions lists.
    Covers OFAC, EU, UN, UK OFSI, and 120+ other sources."""
    if not strale:
        return "Error: pip install straleio and set STRALE_API_KEY"
    inputs = {"name": name}
    if country:
        inputs["country"] = country
    result = strale.do("sanctions-check", inputs)
    o = result.get("output", result)
    sanctioned = o.get("is_sanctioned", False)
    matches = o.get("match_count", 0)
    status = "SANCTIONED" if sanctioned else "CLEAR"
    return f"Entity: {name}\nStatus: {status}\nMatches: {matches}"


@tool
def check_pep(name: str) -> str:
    """Screen a person against Politically Exposed Persons (PEP) databases.
    Returns whether the person is a PEP and their positions if found."""
    if not strale:
        return "Error: pip install straleio and set STRALE_API_KEY"
    result = strale.do("pep-check", {"name": name})
    o = result.get("output", result)
    is_pep = o.get("is_pep", False)
    matches = o.get("match_count", 0)
    status = "PEP FOUND" if is_pep else "CLEAR"
    return f"Person: {name}\nStatus: {status}\nMatches: {matches}"


# ---------------------------------------------------------------------------
# Agent Instructions
# ---------------------------------------------------------------------------
instructions = """\
You are a Compliance Agent — a KYB/AML analyst who verifies businesses
and screens for compliance risks using Strale tools.

## Workflow

1. Understand the request — identify company, person, or financial identifier
2. Use the appropriate tool(s):
   - Company verification: lookup_company(country, company_id)
   - VAT validation: validate_vat(vat_number)
   - IBAN validation: validate_iban(iban) — works without API key
   - Sanctions screening: check_sanctions(name)
   - PEP screening: check_pep(name)
3. For a "full compliance check", run: company lookup + sanctions + PEP
4. Present results in a clear report format

## Rules

- Always cite the data source (Strale API, which queries official registries)
- Report risk level: LOW (all clear), MEDIUM (review needed), HIGH (flagged)
- No speculation — report only what the tools return
- IBAN validation is free (no API key needed)\
"""

# ---------------------------------------------------------------------------
# Create the Agent
# ---------------------------------------------------------------------------
compliance_agent = Agent(
    name="Compliance Agent",
    model=Gemini(id="gemini-3-flash-preview"),
    instructions=instructions,
    tools=[validate_iban, validate_vat, lookup_company, check_sanctions, check_pep],
    add_datetime_to_context=True,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run the Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    compliance_agent.print_response(
        "Verify Swedish company 556703-7485 and check for sanctions", stream=True
    )

# ---------------------------------------------------------------------------
# More Examples
# ---------------------------------------------------------------------------
"""
Try these prompts:

1. Free tier (no API key needed)
   "Validate IBAN DE89370400440532013000"

2. Company verification
   "Look up UK company 08804411"

3. Sanctions screening
   "Is Sberbank on any sanctions lists?"

4. Full compliance check
   "Run a compliance check on Spotify AB (556703-7485, Sweden)"

5. PEP screening
   "Check if Angela Merkel is a PEP"
"""
