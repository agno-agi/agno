# Contract Review Agent

An intelligent contract review agent that analyzes legal documents, extracts key terms and obligations, and flags potential risks or unusual clauses.

## Features

- **Key Term Extraction**: Automatically extracts dates, amounts, parties, and critical terms
- **Obligation Identification**: Maps obligations for each party with deadlines and priorities
- **Risk Flagging**: Identifies non-standard clauses, liability concerns, and missing protections
- **Clause Comparison**: Compares key clauses against standard market practices
- **Redlining Suggestions**: Provides specific language recommendations for improvements
- **Multi-Format Support**: Analyzes PDF, Word documents, text files, and URLs

## Supported Contract Types

- Non-Disclosure Agreements (NDAs)
- Employment Agreements
- Service Agreements / MSAs
- Vendor Contracts
- Lease and Rental Agreements
- Service Level Agreements (SLAs)
- Partnership Agreements
- Licensing Agreements
- Purchase Agreements

## Installation

```bash
pip install -r requirements.in
```

## Prerequisites

Set your OpenAI API key:

```bash
export OPENAI_API_KEY=your-api-key
```

## Usage

### Command Line Interface

```bash
python agent.py
```

### Python API

```python
from agno.media import File
from agent import contract_agent, review_contract, review_contract_text

# Review a local contract file
review = review_contract("path/to/contract.pdf")
print(review.executive_summary)
print(f"Overall Risk Level: {review.overall_risk_level}")

# Review a contract from URL
review = review_contract("https://example.com/contract.pdf")

# Review contract text directly
contract_text = """
SERVICE AGREEMENT
This Agreement is entered into as of January 1, 2024...
"""
review = review_contract_text(contract_text, contract_type="service_agreement")

# Use the agent directly with files
contract_agent.print_response(
    "Review this NDA and identify the key risks",
    files=[File(filepath="contract.pdf")]
)

# Or with a URL
contract_agent.print_response(
    "Analyze this contract",
    files=[File(url="https://example.com/contract.pdf")]
)
```

### Accessing Review Results

```python
review = review_contract("contract.pdf")

# Executive summary
print(review.executive_summary)

# Parties
for party in review.parties:
    print(f"{party.name} ({party.role})")

# Key terms
for term in review.key_terms:
    print(f"{term.term_type}: {term.value}")

# Obligations
for obligation in review.obligations:
    print(f"{obligation.obligated_party}: {obligation.description}")
    if obligation.deadline:
        print(f"  Deadline: {obligation.deadline}")

# Risk flags
for risk in review.risk_flags:
    print(f"[{risk.severity.upper()}] {risk.risk_type}: {risk.description}")
    print(f"  Recommendation: {risk.recommendation}")

# Redline suggestions
for redline in review.redline_suggestions:
    print(f"Section: {redline.section}")
    print(f"Original: {redline.original_text}")
    print(f"Suggested: {redline.suggested_text}")
    print(f"Rationale: {redline.rationale}")
```

## Example Output Structure

```python
ContractReview(
    contract_type="service_agreement",
    executive_summary="This is a Master Service Agreement between...",
    parties=[
        ContractParty(name="Acme Corp", role="client"),
        ContractParty(name="Tech Solutions Inc", role="service_provider")
    ],
    key_terms=[
        KeyTerm(term_type="effective_date", value="January 1, 2024"),
        KeyTerm(term_type="amount", value="$50,000 annually"),
        KeyTerm(term_type="governing_law", value="State of Delaware")
    ],
    obligations=[
        Obligation(
            obligated_party="Tech Solutions Inc",
            description="Provide monthly performance reports",
            deadline="5th of each month",
            is_recurring=True
        )
    ],
    risk_flags=[
        RiskFlag(
            risk_type="liability_concern",
            severity="high",
            description="No limitation on liability for service provider",
            recommendation="Add mutual liability cap equal to 12 months of fees"
        )
    ],
    overall_risk_level="medium",
    confidence=0.85
)
```

## Example Prompts

- "Review this vendor contract and identify all payment obligations"
- "What are the termination rights in this agreement?"
- "Flag any unusual indemnification clauses in this MSA"
- "Extract all deadlines and notice periods from this lease"
- "Compare the confidentiality terms to standard NDA practices"
- "Suggest redlines for the limitation of liability section"

## Architecture

```
contract_review/
├── agent.py          # Main agent definition and helper functions
├── schemas.py        # Pydantic models for structured output
├── documents/        # Sample contracts for testing
├── examples/         # Usage examples
├── requirements.in   # Dependencies
└── README.md         # This file
```

## Notes

- The agent uses Agno's built-in file handling to process PDF, DOCX, TXT, and other document formats
- Files can be passed as local paths or URLs
- Confidence scores indicate the reliability of the analysis
- Complex contracts may require multiple review passes for thorough analysis
