"""
Example showing how team tools can access media (images, videos, audio, files) passed to the team.

This demonstrates:
1. Uploading a PDF file to a team
2. A team tool that can access and process the uploaded file (OCR simulation)
3. The team leader responding directly without delegating to member agents
"""

from typing import Optional, Sequence

from agno.agent import Agent
from agno.media import File
from agno.models.google import Gemini
from agno.models.openai import OpenAIChat  # noqa: F401
from agno.team import Team
from agno.tools import Toolkit


class DocumentProcessingTools(Toolkit):
    def __init__(self):
        tools = [
            self.extract_text_from_pdf,
        ]

        super().__init__(name="document_processing_tools", tools=tools)

    def extract_text_from_pdf(self, files: Optional[Sequence[File]] = None) -> str:
        """
        Extract text from uploaded PDF files using OCR.

        This tool can access any files that were passed to the team.
        In a real implementation, you would use a proper OCR service.

        Args:
            files: Files passed to the team (automatically injected)

        Returns:
            Extracted text from the PDF files
        """
        if not files:
            return "No files were uploaded to process."

        print(f"--> Files: {files}")

        extracted_texts = []
        for i, file in enumerate(files):
            if file.content:
                # Simulate OCR processing
                # In reality, you'd use a service like Tesseract, AWS Textract, etc.
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
    """Create a sample PDF-like content for demonstration."""
    # This is just sample binary content - in reality you'd have actual PDF bytes
    sample_content = """
    %PDF-1.4
    Sample PDF content for demonstration
    This would be actual PDF binary data in a real scenario
    """.encode("utf-8")
    return sample_content


def main():
    # Create a simple member agent (required for team, but won't be used)
    member_agent = Agent(
        model=Gemini(id="gemini-2.5-pro"),
        name="Assistant",
        description="A general assistant agent.",
    )

    # Create a team with document processing tools
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

    print("=== Team Media Access Example (No Delegation) ===\n")

    # Example: PDF Processing handled directly by team leader
    print("1. Testing PDF processing handled directly by team leader...")

    # Create sample file content
    pdf_content = create_sample_pdf_content()
    sample_file = File(content=pdf_content)

    response = team.run(
        input="I've uploaded a PDF document. Please extract the text from it and provide a brief analysis of the financial information. Handle this directly using your tools - no need to delegate to team members.",
        files=[sample_file],
        session_id="test_team_files",
    )

    print(f"Team Response: {response.content}")
    print("\n" + "=" * 50 + "\n")


if __name__ == "__main__":
    main()
