"""
Media Input For Tool
====================

Demonstrates team tools accessing uploaded media files directly.
"""

from typing import Optional, Sequence

from agno.agent import Agent
from agno.media import File
from agno.models.google import Gemini
from agno.team import Team
from agno.tools import Toolkit


class DocumentProcessingTools(Toolkit):
    def __init__(self):
        tools = [
            self.extract_text_from_pdf,
        ]
        super().__init__(name="document_processing_tools", tools=tools)

    def extract_text_from_pdf(self, files: Optional[Sequence[File]] = None) -> str:
        """Extract text from uploaded PDF files using simulated OCR."""
        if not files:
            return "No files were uploaded to process."

        print(f"--> Files: {files}")

        extracted_texts = []
        for i, file in enumerate(files):
            if file.content:
                file_size = len(file.content)
                extracted_text = f"""
                    [SIMULATED OCR RESULT FOR FILE {i + 1}]
                    Document processed successfully!
                    File size: {file_size} bytes

                    Sample extracted content:
                    "This is a sample document with important information about quarterly sales figures.
                    Q1 Revenue: $125,000
                    Q2 Revenue: $150,000
                    Q3 Revenue: $175,000

                    The growth trend shows a 20% increase quarter over quarter."
                """
                extracted_texts.append(extracted_text)
            else:
                extracted_texts.append(
                    f"File {i + 1}: Content is empty or inaccessible."
                )

        return "\n\n".join(extracted_texts)


def create_sample_pdf_content() -> bytes:
    """Create sample PDF-like bytes for demonstration."""
    sample_content = """
    %PDF-1.4
    Sample PDF content for demonstration
    This would be actual PDF binary data in a real scenario
    """.encode("utf-8")
    return sample_content


# ---------------------------------------------------------------------------
# Create Members
# ---------------------------------------------------------------------------
member_agent = Agent(
    model=Gemini(id="gemini-2.5-pro"),
    name="Assistant",
    description="A general assistant agent.",
)

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------
team = Team(
    members=[member_agent],
    model=Gemini(id="gemini-2.5-pro"),
    tools=[DocumentProcessingTools()],
    name="Document Processing Team",
    description="A team that can process uploaded documents and analyze their content directly using team tools. You have access to document processing tools that can extract text from PDF files. Use these tools to process any uploaded documents and provide analysis directly without delegating to team members.",
    instructions=[
        "You are a document processing expert who can handle PDF analysis directly.",
        "When files are uploaded, use the extract_text_from_pdf tool to process them.",
        "Analyze the extracted content and provide insights directly in your response.",
        "Do not delegate tasks to team members - handle everything yourself using the available tools.",
    ],
    debug_mode=True,
    send_media_to_model=False,
    store_media=True,
)

# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=== Team Media Access Example (No Delegation) ===\n")
    print("1. Testing PDF processing handled directly by team leader...")

    pdf_content = create_sample_pdf_content()
    sample_file = File(content=pdf_content)

    response = team.run(
        input="I've uploaded a PDF document. Please extract the text from it and provide a brief analysis of the financial information. Handle this directly using your tools - no need to delegate to team members.",
        files=[sample_file],
        session_id="test_team_files",
    )

    print(f"Team Response: {response.content}")
    print("\n" + "=" * 50 + "\n")
