"""
Docling Reader: Office Documents
=================================
Examples of using Docling to process Microsoft Office documents.

Supported formats:
- DOCX: Microsoft Word documents with structure preservation
- DOTX: Microsoft Word templates
- PPTX: PowerPoint presentations

Run `uv pip install docling openai-whisper` to install dependencies.
"""

import asyncio

from agno.knowledge.reader.docling_reader import DoclingReader
from utils import get_agent, get_knowledge

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

knowledge = get_knowledge(table_name="docling_documents")
agent = get_agent(knowledge)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":

    async def main():
        # --- PPTX file with md output ---
        print("\n" + "=" * 60)
        print("PPTX file with markdown output")
        print("=" * 60 + "\n")

        await knowledge.ainsert(
            name="AI_Presentation",
            path="cookbook/07_knowledge/testing_resources/ai_presentation.pptx",
            reader=DoclingReader(),
        )
        agent.print_response(
            "What are the main topics covered in the AI presentation?",
            stream=True,
        )

        # --- DOCX file with markdown output ---
        print("\n" + "=" * 60)
        print("DOCX file (markdown output)")
        print("=" * 60 + "\n")

        await knowledge.ainsert(
            name="Project_Proposal",
            path="cookbook/07_knowledge/testing_resources/project_proposal.docx",
            reader=DoclingReader(),
        )
        agent.print_response(
            "What is the budget estimate for the AI analytics platform project?",
            stream=True,
        )

        # --- DOTX file with text output ---
        print("\n" + "=" * 60)
        print("DOTX file - Word Template (text output)")
        print("=" * 60 + "\n")

        await knowledge.ainsert(
            name="Meeting_Template",
            path="cookbook/07_knowledge/testing_resources/meeting_notes_template.dotx",
            reader=DoclingReader(output_format="text"),
        )
        agent.print_response(
            "What sections are included in the meeting notes template?",
            stream=True,
        )

    asyncio.run(main())
