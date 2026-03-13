# Investment Memo Generator

AI-native investment research workflow for financial analysis and memo generation.

## Overview

Investment Memo Generator automates financial research by orchestrating three specialized agents:

1. **Company Profiler** - Gathers real-time financial data via Finnhub API
2. **Valuation Agent** - Performs fundamental analysis and price target calculations
3. **Memo Writer** - Structures findings into professional investment memoranda

## Prerequisites

- Python 3.8+
- Finnhub API key
- Google Gemini API key

## Installation

```bash
pip install -r requirements.txt
```

## Setup

1. Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```

2. Add your API keys to `.env`:
```
FINNHUB_API_KEY=your_finnhub_api_key_here
GEMINI_API_KEY=your_gemini_api_key_here
```

**Get API Keys:**
- **Finnhub:** https://finnhub.io/register
- **Gemini:** https://aistudio.google.com/app/apikey

## Running

Start the AgentOS server:
```bash
python main.py
```

## Use

- To use Agno OS, go to os.agno.com and create an account
- In the UI, click on "Create your OS" and add your localhost endpoint
- All of your agents and teams will appear on the home page
- Access the agent at `http://localhost:7777`

## Usage

Submit stock ticker queries through the AgentOS interface. The workflow will:
- **Profile**: Gather company data, real-time quotes, and financial metrics
- **Analyze**: Perform valuation analysis using multiple methodologies
- **Generate**: Create structured investment memos with recommendations

**Example Queries:**
- "Analyze Apple (AAPL) for investment potential"
- "Generate investment memo for Tesla (TSLA)"
- "Evaluate Microsoft (MSFT) stock fundamentals"

## Project Structure

```
Investment_Memo_Generator/
├── agents/
│   ├── company_profiler.py   # Financial data acquisition via MCP
│   ├── valuation_agent.py        # Fundamental analysis and valuation
│   └── memo_writer.py            # Investment memo generation
├── mcp/
│   └── finnhub_mcp_server.py     # Finnhub API MCP server
├── main.py                       # Workflow and AgentOS configuration
├── requirements.txt          # Dependencies
└── README.md                  #Projectdocumentation
└── .env                          # Environment variables (gitignored)
```

## Architecture

The system uses Model Context Protocol (MCP) for standardized API integration:

- **Automatic MCP Connection**: Agno handles server lifecycle management
- **Self-contained Agent**: MCP logic resides within CompanyProfiler
- **Clean Orchestration**: Main file focuses on team coordination only

## Sample Output

```markdown
# Investment Brief: Tesla, Inc. (TSLA) — October 31, 2025

## Executive Summary
Tesla remains a leader in the global EV market, driven by innovation and strong brand positioning.

## Investment Recommendation
**Recommendation:** BUY  
**Target Price:** $295.00  
**Current Price:** $243.60  
**Upside Potential:** +21%

## Key Investment Drivers
1. Battery technology advancements  
2. Global EV market expansion  
3. Strong delivery growth  

## Risk Factors
1. Competitive pressure from legacy automakers  
2. Raw material cost fluctuations  

## Financial Highlights
- Market Cap: $720B  
- P/E Ratio: 65.2x  
- EPS: $3.72
```

## Troubleshooting

**API errors:**
- Verify Finnhub API key is set in `.env`
- Check API key validity and quota
- Verify Gemini API key is correctly configured

**MCP connection errors:**
- Ensure `mcp/finnhub_mcp_server.py` exists and is executable
- Check that Python environment has all required dependencies
- Verify environment variables are loaded correctly

**Port conflicts:**
- Default port is 7777
- Ensure port is not already in use by another application

**Data retrieval issues:**
- Confirm ticker symbols are valid and properly formatted
- Check network connectivity to Finnhub API
- Verify API rate limits are not exceeded

## References

- **Agno 2.0 Docs:** https://docs.agno.com
- **Gemini Docs:** https://ai.google.dev/docs
- **Finnhub API Docs:** https://finnhub.io/docs/api
- **Model Context Protocol (MCP):** https://modelcontextprotocol.io
