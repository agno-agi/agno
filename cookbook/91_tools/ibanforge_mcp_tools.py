"""
IBANforge MCP Tools
===================
Pre-flight payment compliance for AI finance agents.
IBAN validation, BIC/SWIFT lookup, Swiss BC-Nummer, SEPA + VoP reachability,
EMI/vIBAN classification, and a sanctions+risk score in one call.

Backed by 121,197 GLEIF entries and 1,190 SIX BankMaster entries —
the only MCP server exposing Swiss clearing data.

Installation:  npm install -g ibanforge-mcp   (or npx -y ibanforge-mcp)
Documentation: https://ibanforge.com/agents
Free tier:     200 calls/month after one POST to /v1/keys/generate
Paid tier:     0.005-0.020 USDC per call via x402 on Base mainnet
"""

import asyncio

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.team import Team
from agno.tools.mcp import MCPTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------


async def run_agent(message: str) -> None:
    async with MCPTools("npx -y ibanforge-mcp@latest") as ibanforge:
        agent = Agent(
            model=Claude(id="claude-sonnet-4-20250514"),
            tools=[ibanforge],
            instructions=(
                "You are a payment compliance agent.\n"
                "Before approving any payment, validate the IBAN and run a "
                "compliance check. Return a verdict (allow / review / block) "
                "with a reason code citing the specific risk indicators."
            ),
            markdown=True,
        )
        await agent.aprint_response(message, stream=True)


async def run_team(message: str) -> None:
    async with MCPTools("npx -y ibanforge-mcp@latest") as ibanforge:
        validator = Agent(
            model=Claude(id="claude-sonnet-4-20250514"),
            tools=[ibanforge],
            name="Validator",
            role="IBAN Validator",
            instructions=(
                "Validate IBANs and resolve their BIC, country, and Swiss "
                "BC-Nummer when applicable. Flag invalid checksums or "
                "unsupported countries early."
            ),
        )
        compliance_officer = Agent(
            model=Claude(id="claude-sonnet-4-20250514"),
            tools=[ibanforge],
            name="ComplianceOfficer",
            role="Compliance Officer",
            instructions=(
                "Run sanctions + SEPA + VoP + EMI/vIBAN checks on validated "
                "IBANs. Return a verdict with a reason code. Block when "
                "risk_score is at or above 70."
            ),
        )
        team = Team(
            members=[validator, compliance_officer],
            instructions=(
                "Validator processes the IBAN structurally, ComplianceOfficer "
                "runs the risk bundle and produces the final verdict."
            ),
        )
        await team.aprint_response(message, stream=True)


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Single-IBAN compliance triage (validate + classify + risk score in one flow)
    asyncio.run(
        run_agent(
            "Should we send EUR 5000 to CH9300762011623852957? "
            "Validate it, classify the issuer, run the compliance bundle, "
            "and give me a verdict."
        )
    )

    # Swiss BC-Nummer routing — IBANforge is the only MCP exposing this
    # asyncio.run(run_agent("What kind of Swiss institution has BC-Nummer 762?"))

    # BIC lookup with LEI enrichment
    # asyncio.run(run_agent("Resolve BIC UBSWCHZH80A and give me its LEI."))

    # Batch validation — clean a payout list before sending
    # asyncio.run(run_agent(
    #     "Validate this payout list and tell me which IBANs would fail SEPA: "
    #     "DE89370400440532013000, FR1420041010050500013M02606, XX00BAD"
    # ))

    # vIBAN / EMI detection — useful for fraud / chargeback exposure
    # asyncio.run(run_agent(
    #     "Is GB29NWBK60161331926819 a real bank account, an EMI, or a virtual IBAN?"
    # ))

    # Multi-agent team: validator + compliance officer collaborating
    # asyncio.run(run_team(
    #     "Triage this batch of incoming SEPA transfers for our payment ops "
    #     "team: CH9300762011623852957, DE89370400440532013000, "
    #     "GB29NWBK60161331926819. For each, give me country, issuer type, "
    #     "and a verdict."
    # ))
