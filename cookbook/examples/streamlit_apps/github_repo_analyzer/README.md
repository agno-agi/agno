# GitHub Repository Analyzer

**GitHub Repository Analyzer** is a chat application that provides an interface to analyze GitHub repositories using AI.
It allows users to explore code, review pull requests, analyze project structures, and get insights about repository activity through natural language queries.

> Note: Fork and clone this repository if needed

### 1. Create a virtual environment

```shell
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install dependencies

```shell
pip install -r cookbook/examples/streamlit_apps/github_repo_analyzer/requirements.txt
```

### 3. Configure API Keys

Required:

```bash
export OPENAI_API_KEY=your_openai_key_here
```

Optional (for additional models):

```bash
export ANTHROPIC_API_KEY=your_anthropic_key_here
export GOOGLE_API_KEY=your_google_key_here
export GROQ_API_KEY=your_groq_key_here
```

Optional (for enhanced GitHub access):

```bash
export GITHUB_ACCESS_TOKEN=your_github_token_here
```

### 4. Run GitHub Repository Analyzer App

```shell
streamlit run cookbook/examples/streamlit_apps/github_repo_analyzer/app.py
```

## 🔧 Customization

### Model Selection

The application supports multiple model providers:

- OpenAI (o3-mini, gpt-4o)
- Anthropic (claude-3-5-sonnet)
- Google (gemini-2.0-flash-exp)
- Groq (llama-3.3-70b-versatile)

### How to Use

- Open [localhost:8501](http://localhost:8501) in your browser.
- Optionally configure your GitHub Personal Access Token for enhanced access to private repositories.
- Enter repository queries in the chat interface:
  - "Analyze the repository 'owner/repo'"
  - "Show me the latest issues in 'microsoft/vscode'"
  - "Review the latest pull request in 'facebook/react'"
  - "What programming languages are used in 'kubernetes/kubernetes'?"
- The AI will analyze repositories, code, and provide detailed insights.

### Key Features

- **Repository Analysis**: Get comprehensive overviews of any public GitHub repository
- **Code Review**: Analyze pull requests and code changes with detailed feedback
- **Issue Tracking**: Explore and summarize repository issues and discussions
- **Code Search**: Find specific functions, patterns, or implementations across repositories
- **Statistics**: View repository metrics like stars, forks, languages, and activity
- **File Navigation**: Browse repository structure and read file contents
- **Session Management**: Maintain conversation context across sessions

## 📚 Documentation

For more detailed information:

- [Agno Documentation](https://docs.agno.com)
- [Streamlit Documentation](https://docs.streamlit.io)
- [GitHub API Documentation](https://docs.github.com/en/rest)

## 🤝 Support

Need help? Join our [Discord community](https://agno.link/discord)
