# 🐙 MCP GitHub Agent

A Streamlit application that allows you to explore and analyze GitHub repositories using natural language queries through the Model Context Protocol (MCP).

> Note: Fork and clone this repository if needed

## Features

- **Natural Language Interface**: Ask questions about repositories in plain English
- **Comprehensive Analysis**: Explore issues, pull requests, repository activity, and code statistics
- **Interactive UI**: User-friendly interface with example queries and custom input
- **MCP Integration**: Leverages the Model Context Protocol to interact with GitHub's API
- **Real-time Results**: Get immediate insights on repository activity and health

## Setup

### 1. Create a virtual environment

```shell
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install dependencies

1. Install the required Python packages:
   ```bash
   pip install -r cookbook/examples/streamlit_apps/github_mcp_agent/requirements.txt
   ```

3. Set up your API keys:
   - Set OpenAI API Key as an environment variable:
     ```bash
     export OPENAI_API_KEY=xxx
     ```

     Optional (for additional models):

      ```bash
      export ANTHROPIC_API_KEY=your_anthropic_key_here
      export GOOGLE_API_KEY=your_google_key_here
      ```
   - GitHub token will be entered directly in the app interface

4. Create a GitHub Personal Access Token:
   - Visit https://github.com/settings/tokens
   - Create a new token with `repo` and `user` scopes
   - Save the token somewhere secure

### Running the App

1. Start the Streamlit app:
   ```bash
   streamlit run cookbook/examples/streamlit_apps/github_mcp_agent/app.py
   ```

2. In the app interface:
   - Enter your GitHub token in the sidebar
   - Specify a repository to analyze
   - Select a query type or write your own
   - Click "Run Query"

### Example Queries

#### Issues
- "Show me issues by label"
- "What issues are being actively discussed?"
- "Find issues labeled as bugs"

#### Pull Requests
- "What PRs need review?"
- "Show me recent merged PRs"
- "Find PRs with conflicts"

#### Repository
- "Show repository health metrics"
- "Show repository activity patterns"
- "Analyze code quality trends"

## 📚 Documentation

For more detailed information:

- [Agno Documentation](https://docs.agno.com)
- [Model Context Protocol](https://modelcontextprotocol.io)
- [Streamlit Documentation](https://docs.streamlit.io)

## 🤝 Support

Need help? Join our [Discord community](https://agno.link/discord)