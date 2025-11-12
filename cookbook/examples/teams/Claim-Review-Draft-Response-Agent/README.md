# Claim Review & Draft Response Agent

A multi-agent system built with Agno for automated insurance claim processing, policy verification, and draft response generation.

## Overview

This system uses three specialized AI agents working together to process insurance claims:

1. **Claim Ingestor Agent**: Extracts structured data and full content from claim documents (invoices, forms, PDFs)
2. **Rule Checker Agent**: Verifies claims against policy rules, exclusions, and thresholds
3. **Draft Response Agent**: Generates approval or denial responses with detailed comparison tables

The agents work as a team to provide comprehensive claim assessment with:
- Complete document content extraction
- Policy verification and eligibility checking
- Side-by-side comparison tables (Claim Details vs Policy Details)
- Detailed assessment and decision rationale

## Prerequisites

- Python 3.8+
- Gemini API key from Google AI Studio

## Installation

1. Clone or download this repository

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Set up environment variables:
   - Copy `.env.template` to `.env`
   - Add your Gemini API key:
   ```
   GEMINI_API_KEY=your_api_key_here
   GOOGLE_API_KEY=your_api_key_here
   ```

## How to Use

- To use Agno OS, go to os.agno.com and create an account
- In the UI, click on "Create your OS" and add your localhost endpoint
- All of your agents and teams will appear on the home page
- Access the agent at `http://localhost:7777`

Run the main application:

```bash
python main.py
```

### Processing Claims

1. **Access the Web UI**: Open `http://os.agno.com ` in your browser

2. **Upload Documents**:
   - Upload **claim documents** (invoices, forms, PDFs, etc.)
   - Upload **policy document** (PDF, text, or any format)

3. **Submit for Processing**: The team will automatically:
   - Extract data from claim documents
   - Verify against policy rules
   - Generate a draft response with comparison tables

4. **Review Output**: The final response includes:
   - Claim Decision (Approval/Denial)
   - Policy Number
   - Policy Summary
   - Claim Details Table
   - Policy Details Table
   - Decision Rationale
   - Payout Details (if approved)
   - Assessment Details
   - Next Steps

## Connecting to AgentOS

The AgentOS provides a web interface for interacting with the agents:

- **URL**: `http://os.agno.com `
- **Team**: "Claim Review Team" - Use this for end-to-end claim processing
- **Individual Agents**: Available for direct interaction if needed
  - `claim-ingestor`: Extract claim data
  - `rule-checker`: Verify against policy
  - `draft-response`: Generate response

### Using the Team

1. Navigate to the "Claim Review Team" in the UI
2. Upload both claim and policy documents
3. Submit your request
4. Review the complete draft response

## Features

- **Multi-Agent Coordination**: Three specialized agents working together
- **Full Content Extraction**: Complete document text extraction (no summarization)
- **Policy Verification**: Automatic policy number matching and eligibility checking
- **Comparison Tables**: Side-by-side view of claim and policy details
- **Memory Management**: Automatic user memory for personalized responses
- **Markdown Output**: Formatted responses for easy reading
- **File Type Support**: Handles PDFs, text files, invoices, and forms

## Project Structure

```
.
├── agent.py              # Agent definitions (Claim Ingestor, Rule Checker, Draft Response)
├── main.py               # AgentOS setup and team configuration
├── storage/              # Database storage (SQLite)
│   └── claim_memory.db   # Session and memory database
├── requirements.txt      # Python dependencies
├── .env                  # Environment variables (create from .env.template)
└── README.md             # This file
```

## Technology Stack

- **Agno**: Multi-agent framework
- **Gemini 2.0 Flash**: LLM for all agents
- **SQLite**: Database for sessions and memories
- **Python**: Programming language