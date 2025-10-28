# Claude Agent Skills for Agno

## What are Claude Agent Skills?

[Claude Agent Skills](https://docs.anthropic.com/en/docs/agents-and-tools/agent-skills/quickstart) enable Claude to improve how it performs specific tasks:
- **PowerPoint (pptx)**: Create professional presentations with slides, layouts, and formatting
- **Excel (xlsx)**: Generate spreadsheets with formulas, charts, and data analysis
- **Word (docx)**: Create and edit documents with rich formatting
- **PDF (pdf)**: Analyze and extract information from PDF documents

These skills use a **progressive disclosure** architecture - Claude first discovers which skills are relevant, then loads full instructions only when needed.

## Prerequisites

Before you can use Claude Agent Skills, you'll need:

1. **Python 3.8 or higher**
2. **Anthropic API key** with access to Claude models
3. **Required Python packages (Only for file handling post its creation in Sandbox)**:
   - `anthropic` (for direct API access)
   - `agno` (for agent framework)
   - `python-pptx` (optional, for PowerPoint manipulation)
   - `openpyxl` (optional, for Excel file handling)
   - `python-docx` (optional, for Word document handling)
   - `PyPDF2` or `pdfplumber` (optional, for PDF processing)

## Installation

1. Install the required packages:
```bash
pip install anthropic agno

# Optional: Install document manipulation libraries
pip install python-pptx openpyxl python-docx PyPDF2 pdfplumber
```

2. Set up your Anthropic API key:
```bash
export ANTHROPIC_API_KEY="your_api_key_here"
```

Or create a `.env` file:
```
ANTHROPIC_API_KEY=your_api_key_here
```

## Quick Start

### Basic Direct API Usage

```python
import anthropic

client = anthropic.Anthropic()

response = client.messages.create(
    model="claude-sonnet-4-5-20250929",
    max_tokens=4096,
    betas=["skills-2025-10-02"],  # Enable skills beta
    container={
        "skills": [
            {"type": "anthropic", "skill_id": "pptx", "version": "latest"},
            {"type": "anthropic", "skill_id": "xlsx", "version": "latest"},
            {"type": "anthropic", "skill_id": "docx", "version": "latest"},
            {"type": "anthropic", "skill_id": "pdf", "version": "latest"},
        ]  # Enable all skills
    },
    messages=[
        {
            "role": "user",
            "content": "Create a 3-slide PowerPoint about AI trends"
        }
    ]
)
```

### Integration with Agno Agents

Agno now has native support for Claude Agent Skills! Simply pass the `skills` parameter to the Claude model:

```python
from agno.agent import Agent
from agno.models.anthropic import Claude

# Enable PowerPoint skill
agent = Agent(
    model=Claude(
        id="claude-sonnet-4-5-20250929",
        skills=[{"type": "anthropic", "skill_id": "pptx", "version": "latest"}]  # Enable PowerPoint skill
    ),
    instructions=[
        "You are a presentation specialist.",
        "Create professional PowerPoint presentations."
    ],
    markdown=True
)

agent.print_response("Create a sales presentation with 5 slides")
```

**Available Skills**: `pptx`, `xlsx`, `docx`, `pdf`

You can enable multiple skills at once:
```python
model=Claude(
    id="claude-sonnet-4-5-20250929",
    skills=[
        {"type": "anthropic", "skill_id": "pptx", "version": "latest"},
        {"type": "anthropic", "skill_id": "xlsx", "version": "latest"},
        {"type": "anthropic", "skill_id": "docx", "version": "latest"},
    ]
)
```

The framework automatically:
- Configures the required betas (`code-execution-2025-08-25`, `skills-2025-10-02`)
- Adds the code execution tool
- Uses the beta API client
- Sets up the container with skill configurations

## Available Examples

### 1. `agent_with_powerpoint.py`
Shows how to create an Agno agent specialized in PowerPoint presentations:
- Business presentation generation
- Market analysis reports
- Slide design and formatting

### 2. `agent_with_excel.py`
Demonstrates Excel/spreadsheet capabilities:
- Data analysis and visualization
- Financial calculations
- CSV to Excel conversion

### 3. `agent_with_documents.py`
Examples for Word and PDF processing:
- Document creation and editing
- PDF analysis and extraction
- Format conversion

### 4. `multi_skill_agent.py`
Advanced example combining multiple skills:
- Complete business workflow (Excel → PowerPoint → PDF)
- Progressive skill loading
- Skill orchestration patterns

## Features

- **Progressive Disclosure**: Skills are loaded only when needed, optimizing token usage
- **Native Code Execution**: Skills can execute Python code to create/modify documents
- **File Output**: Generated documents are created in execution sandbox (see File Downloads below)
- **Format Support**: Full support for PPTX, XLSX, DOCX, and PDF formats
- **Agno Integration**: Seamless integration with Agno's agent framework

## ⚠️ Important: File Downloads

**Files created by Agent Skills are NOT automatically saved to your local filesystem.**

When Claude creates a document (e.g., .pptx, .xlsx) using Agent Skills, it:
1. Creates the file in a sandboxed execution environment
2. Returns a **file ID** in the tool result
3. You must download the file separately using the [Anthropic Files API](https://docs.anthropic.com/en/docs/build-with-claude/files)

### How to Download Files

```python
import anthropic

client = anthropic.Anthropic()

# 1. Create document with skills
response = client.beta.messages.create(
    model="claude-sonnet-4-5-20250929",
    max_tokens=4096,
    betas=["code-execution-2025-08-25", "skills-2025-10-02"],
    container={"skills": [{"type": "anthropic", "skill_id": "pptx", "version": "latest"}]},
    messages=[{"role": "user", "content": "Create a presentation..."}],
    tools=[{"type": "code_execution_20250825", "name": "code_execution"}]
)

# 2. Extract file ID from tool results
file_id = None
for block in response.content:
    if block.type == "tool_use" and hasattr(block, "result"):
        # File ID is in the tool result
        file_id = block.result.get("file_id")

# 3. Download the file
if file_id:
    file_content = client.beta.files.download(file_id=file_id)
    with open("presentation.pptx", "wb") as f:
        f.write(file_content)
```

See `test_with_file_download.py` for a complete example.

## Configuration

### Model Requirements
- Recommended: `claude-sonnet-4-5-20250929` or later
- Minimum: `claude-3-5-sonnet-20241022`
- Skills require models with code execution capability

### Beta Version
Skills require the beta parameter:
```python
betas=["skills-2025-10-02"]
```

### Enabling Skills
Specify skills in the container parameter:
```python
container={
    "skills": ["pptx"]  # Enable only PowerPoint
    # or
    "skills": ["pptx", "xlsx", "docx", "pdf"]  # Enable all skills
}
```

## Performance Notes

- **Token Usage**: Skills use progressive disclosure to minimize token consumption
- **Generation Time**: Document creation may take 10-30 seconds depending on complexity
- **File Size**: Generated files are typically 50KB-5MB depending on content
- **Concurrency**: Skills can be used in parallel for multiple document types

## Use Cases

### Business Applications
- Automated report generation (Excel data → PowerPoint presentation)
- Financial analysis and visualization
- Contract and proposal creation
- Meeting notes and documentation

### Data Analysis
- CSV/Excel data visualization
- Statistical analysis with charts
- Data transformation and cleaning
- Interactive dashboards

### Document Processing
- PDF text extraction and analysis
- Document format conversion
- Template-based document generation
- Batch document processing

### Education
- Lecture slide generation
- Assignment and quiz creation
- Course material formatting
- Research paper analysis

## Limitations

- **File Size**: Large documents (>100MB) may hit token limits
- **Complex Formatting**: Some advanced formatting features may not be supported
- **External Resources**: Cannot fetch external images or data sources
- **OCR**: PDF skill focuses on text extraction, not OCR of scanned documents

## Security Notes

- **API Key**: Never commit your Anthropic API key to version control
- **File Access**: Skills operate in a sandboxed environment
- **Data Privacy**: Documents are processed through Anthropic's API
- **Output Validation**: Always validate generated documents before production use

## Troubleshooting

### "Skills not available" Error
- Ensure you're using the correct beta version: `betas=["skills-2025-10-02"]`
- Verify your API key has access to Claude models with skills
- Check that your account has skills beta access

### Code Execution Timeout
- Reduce document complexity or size
- Split large operations into smaller tasks
- Use simpler formatting when possible

### File Not Generated
- Check for errors in the response
- Verify the code execution completed successfully
- Ensure proper file paths and permissions

## Support

If you encounter any issues or have questions, please:
1. Check the [Anthropic Documentation](https://docs.anthropic.com/en/docs/agents-and-tools/agent-skills/quickstart)
2. Check the [Agno documentation](https://docs.agno.com)
3. Open an issue on the Agno GitHub repository
4. Join the Agno community for support

## Additional Resources

- [Claude Agent Skills Quickstart](https://docs.anthropic.com/en/docs/agents-and-tools/agent-skills/quickstart)
- [Anthropic API Reference](https://docs.anthropic.com/en/api)
- [Agno Documentation](https://docs.agno.com)
- [Python-PPTX Documentation](https://python-pptx.readthedocs.io/)
- [Openpyxl Documentation](https://openpyxl.readthedocs.io/)

## License

This integration follows the same license as the Agno framework.
