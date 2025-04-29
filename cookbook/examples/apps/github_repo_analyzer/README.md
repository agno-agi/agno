# GitHub Repository Analyzer

This application provides a chat-based interface to interact with and analyze GitHub repositories using the Agno framework and OpenAI models. Users can select a repository and ask questions about its code, issues, pull requests, statistics, and more.

## Features

- **Chat Interface:** Interact with an AI agent knowledgeable about a selected GitHub repository.
- **Repository Selection:** Choose from a predefined list of popular open-source repositories or potentially add your own (requires code modification or environment setup).
- **Comprehensive Analysis:** Ask about:
  - Repository statistics (stars, forks, languages).
  - Open/Closed issues and pull requests.
  - Detailed pull request information, including code changes (diff/patch analysis).
  - File contents and directory structures.
  - Code searching within the repository.
- **Powered by Agno & OpenAI:** Leverages the `agno` framework for agent creation and tool usage.

### 1. Create a virtual environment

```shell
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install dependencies

```shell
pip install -r cookbook/examples/apps/github_repo_analyzer/requirements.txt
```

### 3. Export API Keys

Export the API keys:

```shell
export OPENAI_API_KEY=***
export GITHUB_ACCESS_TOKEN=**
```

### 4. Run the app

```shell
streamlit run cookbook/examples/apps/github_repo_analyzer/app.py
```

Navigate to the URL provided by Streamlit (usually `http://localhost:8501`) in your web browser. Select a repository from the sidebar and start chatting!

## Project Structure

The project uses a streamlined structure with all functionality in a single file:

```
github-repo-analyzer/
├── app.py            # Main application with all functionality
├── agent.py          # Agent initialization
├── requirements.txt  # Dependencies
├── README.md         # Documentation
└── output/           # Generated analysis reports
```

## Technologies Used

- [Agno](https://docs.agno.com) - AI agent framework for GitHub analysis
- [Streamlit](https://streamlit.io/) - Interactive web interface
- [PyGithub](https://pygithub.readthedocs.io/) - GitHub API access
