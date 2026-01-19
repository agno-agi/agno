# Document Summarizer

An intelligent document summarization agent that processes various document types (PDF, text, web pages) and produces structured summaries with key points, entities, and action items.

## What You'll Learn

| Concept | Description |
|:--------|:------------|
| **Structured Output** | Using Pydantic schemas for consistent agent responses |
| **Document Loading** | Reading PDFs, text files, and web pages |
| **Entity Extraction** | Identifying people, organizations, dates, technologies |
| **Action Items** | Finding tasks and next steps in documents |

## Quick Start

### 1. Install Dependencies

```bash
pip install pypdf requests beautifulsoup4
```

### 2. Run an Example

```bash
.venvs/demo/bin/python cookbook/01_showcase/01_agents/document_summarizer/examples/01_basic_summary.py
```

## Examples

| # | File | What You'll Learn |
|:--|:-----|:------------------|
| 01 | `examples/01_basic_summary.py` | Basic summarization, accessing structured fields |
| 02 | `examples/02_extract_entities.py` | Entity extraction and categorization |
| 03 | `examples/03_batch_processing.py` | Processing multiple documents |

## Architecture

```
document_summarizer/
├── agent.py          # Main agent with structured output
├── schemas.py        # Pydantic models for summaries
├── tools/
│   ├── pdf_reader.py    # PDF text extraction
│   ├── text_reader.py   # Text file reading
│   └── web_fetcher.py   # URL content fetching
├── documents/        # Sample documents
└── examples/
```

## Key Concepts

### Structured Output with Pydantic

The agent returns a `DocumentSummary` object with typed fields:

```python
from document_summarizer import summarize_document

summary = summarize_document("meeting_notes.txt")

print(summary.title)        # Document title
print(summary.summary)      # Concise summary
print(summary.key_points)   # List of key takeaways
print(summary.entities)     # Extracted entities
print(summary.action_items) # Tasks identified
print(summary.confidence)   # 0-1 confidence score
```

### Document Summary Schema

```python
class DocumentSummary(BaseModel):
    title: str
    document_type: str  # report, article, meeting_notes, research_paper, email, other
    summary: str
    key_points: list[str]
    entities: list[Entity]
    action_items: list[ActionItem]
    word_count: int
    confidence: float
```

### Entity Extraction

Entities are categorized by type:

```python
class Entity(BaseModel):
    name: str      # "Sarah Chen"
    type: str      # "person", "organization", "date", "location", "technology"
    context: str   # "Project Manager leading Q4 planning"
```

### Action Item Detection

Action items capture tasks with optional metadata:

```python
class ActionItem(BaseModel):
    task: str       # "Submit contractor request to HR"
    owner: str      # "Mike"
    deadline: str   # "January 20"
    priority: str   # "high", "medium", "low"
```

## Supported Document Types

| Format | Extension | Notes |
|:-------|:----------|:------|
| PDF | `.pdf` | Text extraction via pypdf |
| Text | `.txt` | UTF-8 and common encodings |
| Markdown | `.md` | Treated as plain text |
| Web | `http://`, `https://` | Main content extraction |

## Usage Patterns

### Basic Summarization

```python
from document_summarizer import summarize_document

summary = summarize_document("report.pdf")
print(summary.summary)
```

### Using the Agent Directly

```python
from document_summarizer import summarizer_agent

# For interactive use
summarizer_agent.print_response(
    "Summarize this text: <your content here>",
    stream=True
)

# For programmatic use
response = summarizer_agent.run("Summarize: <content>")
summary = response.content  # DocumentSummary object
```

### Web Page Summarization

```python
from document_summarizer import summarize_document

summary = summarize_document("https://example.com/article")
print(summary.key_points)
```

## Requirements

- Python 3.11+
- OpenAI API key

## Environment Variables

```bash
export OPENAI_API_KEY=your-openai-key
```

## Sample Documents

The `documents/` folder includes:

| File | Type | Purpose |
|:-----|:-----|:--------|
| `meeting_notes.txt` | Meeting notes | Action item extraction |
| `blog_post.md` | Technical article | Entity extraction |
