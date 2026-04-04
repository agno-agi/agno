"""
File Text Extraction for Models
================================

Some models and providers reject the ``{"type": "file"}`` content format used
by OpenAI-compatible APIs.  The ``extract_file_text`` flag on ``OpenAIChat``,
``DeepSeek``, and ``LiteLLM`` model classes extracts text from uploaded files
and sends them as ``{"type": "text"}`` content blocks instead.

Supported formats:
- Text files (txt, csv, json, html, css, py, js, md, xml, etc.)
- PDF files (requires ``pypdf``)
- DOCX files (requires ``python-docx``)

If extraction fails for a given file, the original ``{"type": "file"}``
format is used as a fallback.

Usage:
    Set ``extract_file_text=True`` on the model to enable text extraction.

Run this cookbook:
    .venvs/demo/bin/python cookbook/02_agents/12_multimodal/file_text_extraction.py
"""

from agno.agent import Agent
from agno.media import File
from agno.models.openai import OpenAIChat

# ---------------------------------------------------------------------------
# Example: Agent with text extraction enabled
# ---------------------------------------------------------------------------
# Models like gpt-4.1-mini via Azure OpenAI reject {"type": "file"} content
# blocks.  Setting extract_file_text=True extracts text from supported
# document types and sends it as plain text instead.
agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini", extract_file_text=True),
    markdown=True,
)

if __name__ == "__main__":
    # Text file
    print("--- Text file extraction ---")
    agent.print_response(
        "Summarize this file",
        files=[
            File(
                content=b"Project Status Report\n\nThe migration is 80% complete.\nRemaining: testing and docs.",
                filename="status.txt",
                mime_type="text/plain",
            )
        ],
    )

    # Python source file
    print("--- Python file extraction ---")
    agent.print_response(
        "What does this code do?",
        files=[
            File(
                content=b"def fibonacci(n):\n    a, b = 0, 1\n    for _ in range(n):\n        a, b = b, a + b\n    return a",
                filename="fib.py",
                mime_type="text/x-python",
            )
        ],
    )
