# Contract Review Agent

An intelligent contract review agent that analyzes legal documents, extracts key terms and obligations, and flags potential risks or unusual clauses.

## Features

- **Key Term Extraction**: Automatically extracts dates, amounts, parties, and critical terms
- **Obligation Identification**: Maps obligations for each party with deadlines and priorities
- **Risk Flagging**: Identifies non-standard clauses, liability concerns, and missing protections
- **Clause Comparison**: Compares key clauses against standard market practices
- **Redlining Suggestions**: Provides specific language recommendations for improvements
- **Multi-Format Support**: Analyzes PDF, Word documents, text files, and URLs
- **Security Guardrails**: PII detection, prompt injection protection, and content moderation

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

Set your Google API key (the agent uses the Gemini model):

```bash
# Windows
set GOOGLE_API_KEY=your-api-key

# Unix/Mac
export GOOGLE_API_KEY=your-api-key
```

## Quick Start

### Verify Setup

```bash
python scripts/check_setup.py
```

### Interactive CLI

```bash
python agent.py
```

### Run Examples

```bash
python examples/run_examples.py
```

## Usage

### Command Line Interface

```bash
python agent.py
```

This starts an interactive session where you can provide contracts for review.

### Python API

```python
from agno.media import File
from agent import contract_agent

# Review a local contract file
contract_agent.print_response(
    "Analyze this contract and identify key risks.",
    files=[File(filepath="path/to/contract.pdf")],
    stream=True,
)

# Review a contract from URL
contract_agent.print_response(
    "Review this NDA and identify the key risks",
    files=[File(url="https://example.com/contract.pdf")],
    stream=True,
)
```

### Structured Output (Optional)

The agent outputs readable markdown by default. To get structured output, set the output schema:

```python
from agent import contract_agent
from schemas import ContractReview

contract_agent.output_schema = ContractReview

result = contract_agent.run(
    "Analyze this contract.",
    files=[File(filepath="contract.pdf")],
)
# Access structured fields: result.content.executive_summary, result.content.risk_flags, etc.
```

## Output Format

By default, the agent returns a readable markdown report with:

- Overview with contract type, risk level, and confidence score
- Parties table
- Key dates and terms
- Obligations by party with deadlines
- Risk flags categorized by severity (High / Medium / Low)
- Clause analysis comparison table
- Recommended redlines with original and suggested text
- Missing clauses checklist
- Ambiguous sections
- Key deadlines to track

## Security Guardrails

The agent includes pre-processing guardrails:

| Guardrail | Purpose |
|-----------|---------|
| `PIIDetectionGuardrail` | Detects PII (SSN, credit cards, emails, etc.) |
| `PromptInjectionGuardrail` | Prevents prompt injection attacks |
| `OpenAIModerationGuardrail` | Filters inappropriate/harmful content |

## Tools Used

| Tool | Purpose |
|------|---------|
| `ReasoningTools` | Plan analysis approach and work through complex clauses |
| `WebSearchTools` | Look up legal standards, precedents, and regulations |

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GOOGLE_API_KEY` | Yes | Google API key for Gemini model |

## Example Prompts

- "Review this vendor contract and identify all payment obligations"
- "What are the termination rights in this agreement?"
- "Flag any unusual indemnification clauses in this MSA"
- "Extract all deadlines and notice periods from this lease"
- "Compare the confidentiality terms to standard NDA practices"
- "Suggest redlines for the limitation of liability section"

## Project Structure

```
contract_review/
├── agent.py          # Main agent definition
├── schemas.py        # Pydantic models for optional structured output
├── requirements.in   # Dependencies
├── README.md         # This file
├── documents/        # Sample contracts for testing
├── scripts/
│   └── check_setup.py    # Setup verification
└── examples/
    └── run_examples.py   # Usage examples
```

## Notes

- The agent uses Agno's built-in file handling to process PDF, DOCX, TXT, and other document formats
- Files can be passed as local paths or URLs
- Confidence scores indicate the reliability of the analysis
- Complex contracts may require multiple review passes for thorough analysis

## License

See the main Agno repository license.
