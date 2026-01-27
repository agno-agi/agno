# Code Review Agent

An intelligent code review agent that analyzes pull requests, provides context-aware suggestions, and enforces coding standards and best practices.

## Features

- **Bug Detection**: Identifies logic errors, null references, race conditions, and edge cases
- **Security Scanning**: Detects SQL injection, XSS, hardcoded credentials, and other vulnerabilities
- **Style Enforcement**: Checks coding conventions and consistency
- **Performance Suggestions**: Recommends optimizations and efficiency improvements
- **Test Recommendations**: Identifies missing test coverage with specific scenarios
- **Documentation Gaps**: Spots missing docstrings, comments, and API documentation
- **File Operations**: Reads, analyzes, and creates fixed versions of code files
- **HTML Generation**: Creates HTML pages from natural language descriptions

## Supported Languages

The agent can review code in any language, with particular expertise in:

- Python
- JavaScript / TypeScript
- Java
- Go
- Rust
- C / C++
- Ruby
- PHP

## Installation

```bash
pip install -r requirements.in
```

## Prerequisites

### Required

The agent uses **GPT-5.2-Codex** by default. You can also use **Claude Opus 4.5** as an alternative (see Model Options below).

**For GPT-5.2-Codex (Default):**

```bash
# Windows
set OPENAI_API_KEY=your-api-key

# Unix/Mac
export OPENAI_API_KEY=your-api-key
```

**For Claude Opus 4.5 (Optional Alternative):**

```bash
# Windows
set ANTHROPIC_API_KEY=your-api-key

# Unix/Mac
export ANTHROPIC_API_KEY=your-api-key
```

Get your Claude API key at: https://console.anthropic.com/

### Optional

Set GitHub token for PR reviews:

```bash
# Windows
set GITHUB_TOKEN=your-github-token

# Unix/Mac
export GITHUB_TOKEN=your-github-token
```

Get a token at: https://github.com/settings/tokens

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

This launches a menu-based TUI with the following options:

```
  1. Review Python Code
  2. Review JavaScript Code
  3. Review Code Diff
  4. Review GitHub PR (enter URL)
  5. Security-Focused Review
  6. Review Single File
  7. Create HTML Page
  8. Interactive Mode

  0. Exit
```

## Usage

### Command Line Interface

```bash
python agent.py
```

This starts an interactive session where you can paste code or ask for reviews.

### Python API

```python
from agent import code_review_agent
from agno.media import File

# Review code inline
code_review_agent.print_response(
    "Review this Python code for bugs and security issues:\n\n```python\n...\n```",
    stream=True,
)

# Review a file using file tools
code_review_agent.print_response(
    "Read and review the file at path/to/file.py",
    stream=True,
)

# Review a GitHub PR (requires GITHUB_TOKEN)
code_review_agent.print_response(
    "Review this pull request and provide feedback: https://github.com/owner/repo/pull/123",
    stream=True,
)

# Security-focused review
code_review_agent.print_response(
    "Perform a security-focused review of this code",
    files=[File(filepath="auth.py")],
    stream=True,
)
```

### Model Options

The agent supports two high-performance models for code review:

#### Option 1: GPT-5.2-Codex (Default)

Best for: Tool use, GitHub integration, and technical analysis

```python
from agno.models.openai import OpenAIResponses

model = OpenAIResponses(id="gpt-5.2-codex")
```

**Pros:**
- Optimized specifically for code analysis
- Excellent tool calling and GitHub API integration
- Fast and cost-effective for large PRs

**Requires:** `OPENAI_API_KEY` environment variable

#### Option 2: Claude Opus 4.5 (Alternative)

Best for: Nuanced feedback, prose quality, and detailed explanations

```python
from agno.models.anthropic import Claude

model = Claude(id="claude-opus-4-5")
```

**Pros:**
- Superior prose and explanation quality
- Excellent at nuanced security analysis
- Great for complex code patterns

**Requires:** `ANTHROPIC_API_KEY` environment variable

**To switch to Claude Opus 4.5:**

1. Open `agent.py`
2. Uncomment the Claude import: `from agno.models.anthropic import Claude`
3. Replace the model line with: `model=Claude(id="claude-opus-4-5")`
4. Set `ANTHROPIC_API_KEY` environment variable

Both models provide excellent code review capabilities—choose based on your preferences and use case.

### Optional Structured Output

By default, the agent returns markdown. To get structured output, create a new agent instance with `output_schema`:

```python
from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from schemas import CodeReviewResult

# Create agent with structured output
review_agent = Agent(
    model=OpenAIResponses(id="gpt-5.2-codex"),
    output_schema=CodeReviewResult,
    # ... other configuration options
)

result = review_agent.run("Review this code: ...")
# Access structured fields
print(result.content.bugs)
print(result.content.security_issues)
```

Available schema models: `CodeReviewResult`, `BugReport`, `SecurityIssue`, `StyleViolation`, `TestRecommendation`, `DocumentationGap`, `FileChange`, `Suggestion`

## Output Format

By default, the agent returns a readable markdown report with:

- Overview with assessment and risk level
- Files changed summary
- Bugs found with severity, location, and suggested fixes
- Security issues with CWE references
- Style violations
- Performance suggestions
- Test recommendations
- Documentation gaps
- Positive highlights

## Tools Used

| Tool | Purpose |
|------|---------|
| `GithubTools` | Fetch PRs, diffs, repo structure |
| `ReasoningTools` | Analyze complex code logic |
| `WebSearchTools` | Look up best practices, CVEs |
| `ShellTools` | Execute shell commands for linting, testing |
| `FileTools` | Read/write files for local repo analysis |
| `PythonTools` | Run Python code for static analysis |
| `WebsiteTools` | Read and summarize web documentation |

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `OPENAI_API_KEY` | Yes (default) | OpenAI API key for GPT-5.2-Codex model |
| `ANTHROPIC_API_KEY` | Optional | Anthropic API key for Claude Opus 4.5 (if using Claude) |
| `GITHUB_TOKEN` | Optional | GitHub token for PR access |

## Project Structure

```
code_review/
├── agent.py              # Main agent definition
├── schemas.py            # Optional Pydantic output schemas
├── __init__.py           # Package exports
├── requirements.in       # Dependencies
├── README.md             # This file
├── scripts/
│   └── check_setup.py    # Setup verification
└── examples/
    ├── run_examples.py        # Menu-based TUI with examples
    ├── sample_calculator.py   # Sample Python file with intentional bugs
    └── sample_calculator.html # Sample HTML file with intentional bugs
```

## Tips

1. **Provide context**: Tell the agent what the code does for better reviews
2. **Specify focus areas**: Ask for security, performance, or specific concerns
3. **Use sample files**: Try option 6 in the menu to review the sample calculator files
4. **Create HTML pages**: Use option 7 to generate HTML pages from descriptions
5. **Iterate**: Ask follow-up questions about specific findings

## Troubleshooting

### "OPENAI_API_KEY not set" or "ANTHROPIC_API_KEY not set"

Make sure you've exported the environment variable for your chosen model:

```bash
# Check if set (GPT-5.2-Codex)
echo $OPENAI_API_KEY  # Unix
echo %OPENAI_API_KEY%  # Windows CMD
$env:OPENAI_API_KEY  # PowerShell

# Check if set (Claude Opus 4.5)
echo $ANTHROPIC_API_KEY  # Unix
echo %ANTHROPIC_API_KEY%  # Windows CMD
$env:ANTHROPIC_API_KEY  # PowerShell
```

### "Could not fetch PR"

1. Verify `GITHUB_TOKEN` is set
2. Check the PR URL is correct
3. Ensure your token has `repo` scope for private repos

### Rate Limits

For large PRs or many reviews:
- Use streaming (`stream=True`) for faster feedback
- Review files individually for very large PRs

## License

See the main Agno repository license.
