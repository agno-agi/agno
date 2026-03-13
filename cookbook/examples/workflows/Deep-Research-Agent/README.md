# Deep Research Agent

AI-native deep research workflow for technical research and analysis.

## Overview

Deep Research Agent automates technical research by orchestrating three specialized agents:

1. **Search Orchestrator** - Gathers technical sources (docs, blogs, GitHub repos, research papers)
2. **Evidence Extractor** - Extracts key concepts, trade-offs, and benchmarks with citations
3. **Report Synthesizer** - Structures findings into comprehensive research reports

## Prerequisites

- Python 3.8+
- OpenAI API key
- GitHub token (for enhanced GitHub repository search)

## Installation

```bash
pip install -r requirements.txt
```

## Setup

1. Copy `.env.template` to `.env`:
```bash
cp .env.template .env
```

2. Add your API keys to `.env`:
```
OPENAI_API_KEY=your_openai_api_key_here
GITHUB_TOKEN=your_github_token_here  # Optional: enables GithubTools for better GitHub search
```

**Optional - Get GitHub Token:**
1. Go to https://github.com/settings/tokens
2. Click "Generate new token" → "Generate new token (classic)"
3. Select `public_repo` scope
4. Copy token and add to `.env`
5. Without token, GitHub search uses DuckDuckGo with `site:github.com`

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

Submit research queries through the AgentOS interface. The workflow will:
- **Search**: Gather sources from DuckDuckGo, Wikipedia, Arxiv, HackerNews, and GitHub (if token provided)
- **Extract**: Analyze sources and extract key concepts, trade-offs, and benchmarks with citations
- **Synthesize**: Generate a structured research report with background, findings, alternatives, and recommendations

**Example Queries:**
- "What are the best practices for implementing real-time collaboration features in web applications?"
- "Compare state management solutions for large-scale React applications"
- "Research latest developments in vector database technologies for AI applications"

## Troubleshooting

**Database errors:**
- Ensure `tmp/` directory exists (created automatically)
- Check file permissions for database write access

**Import errors:**
- Verify all dependencies installed: `pip install -r requirements.txt`
- Check Python version: `python --version` (should be 3.8+)

**API errors:**
- Verify OpenAI API key is set in `.env`
- Check API key validity and quota
- GitHub token errors: If `GITHUB_TOKEN` is invalid, agent falls back to DuckDuckGo for GitHub searches

**Port conflicts:**
- Default port is 7777

## Project Structure

```
├── agents.py          # Agent definitions with Memory setup
├── main.py            # Workflow and AgentOS configuration
├── requirements.txt   # Dependencies
├── .env              # Environment variables (gitignored)
└── tmp/              # Database storage (gitignored)
```

