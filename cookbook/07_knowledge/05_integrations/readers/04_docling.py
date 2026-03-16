"""
Docling Reader: Advanced Document Understanding
================================================
Docling uses IBM's advanced document conversion library to extract content from multiple document formats.

Supported formats examples::
- PDF: PDFs with advanced layout understanding and text extraction
- DOCX: Microsoft Word documents with structure preservation
- PPTX: PowerPoint presentations
- Markdown: Markdown files
- CSV: CSV spreadsheets
- XLSX: Excel spreadsheets

Output formats examples:
- markdown: Preserves structure and formatting
- text: Plain text output
- json: Lossless serialization with full document structure
- html: HTML with image embedding/referencing support
- doctags: Markup format with full content and layout characteristics

Key features:
- Advanced document structure understanding
- Better handling of complex layouts (tables, columns, etc.)
- Multiple output formats for different use cases
- Ideal for complex documents with rich formatting

Run `uv pip install docling openai-whisper` to install dependencies.

See also: 01_documents.py for PDF/DOCX, 02_data.py for CSV/JSON and 03_web.py for web sources.
"""

import asyncio
import warnings

from agno.agent import Agent
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.docling_reader import DoclingReader
from agno.models.openai import OpenAIResponses
from agno.vectordb.qdrant import Qdrant
from agno.vectordb.search import SearchType

# Suppress Whisper FP16 warnings when running on CPU
warnings.filterwarnings("ignore", message="FP16 is not supported on CPU")

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

qdrant_url = "http://localhost:6333"

knowledge = Knowledge(
    vector_db=Qdrant(
        collection="docling_reader",
        url=qdrant_url,
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)

agent = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
    knowledge=knowledge,
    search_knowledge=True,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":

    async def main():
        # --- Local PDF file with markdown output ---
        print("\n" + "=" * 60)
        print("Local PDF file (markdown output)")
        print("=" * 60 + "\n")

        await knowledge.ainsert(
            name="CV_Local",
            path="cookbook/07_knowledge/testing_resources/cv_1.pdf",
            reader=DoclingReader(output_format="markdown"),
        )
        agent.print_response("What skills does Jordan Mitchell have?", stream=True)

        # --- PDF from URL with text output ---
        print("\n" + "=" * 60)
        print("PDF from URL (text output)")
        print("=" * 60 + "\n")

        await knowledge.ainsert(
            name="Recipes_URL",
            url="https://agno-public.s3.amazonaws.com/recipes/thai_recipes_short.pdf",
            reader=DoclingReader(output_format="text"),
        )
        agent.print_response("What Thai recipes are available?", stream=True)

        # --- ArXiv paper from URL with md output---
        print("\n" + "=" * 60)
        print("ArXiv paper from URL (markdown output)")
        print("=" * 60 + "\n")

        await knowledge.ainsert(
            name="Docling_Paper",
            url="https://arxiv.org/pdf/2408.09869",
            reader=DoclingReader(),
        )
        agent.print_response(
            "What is Docling and what are its key features?", stream=True
        )

        # --- JSON output for structured data ---
        print("\n" + "=" * 60)
        print("PDF with JSON output")
        print("=" * 60 + "\n")

        await knowledge.ainsert(
            name="Structured_Doc",
            path="cookbook/07_knowledge/testing_resources/cv_1.pdf",
            reader=DoclingReader(output_format="json"),
        )
        agent.print_response(
            "What is the structure of this document?",
            stream=True,
        )

        # --- PDF with HTML output ---
        print("\n" + "=" * 60)
        print("PDF with HTML output")
        print("=" * 60 + "\n")

        await knowledge.ainsert(
            name="HTML_Doc",
            path="cookbook/07_knowledge/testing_resources/cv_1.pdf",
            reader=DoclingReader(output_format="html"),
        )
        agent.print_response(
            "Summarize the candidate's experience",
            stream=True,
        )

        # --- PDF with Doctags output ---
        print("\n" + "=" * 60)
        print("PDF with Doctags output")
        print("=" * 60 + "\n")

        await knowledge.ainsert(
            name="Doctags_Doc",
            path="cookbook/07_knowledge/testing_resources/cv_1.pdf",
            reader=DoclingReader(output_format="doctags"),
        )
        agent.print_response(
            "What sections are in this document?",
            stream=True,
        )

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

        # --- JPEG image - Restaurant invoice ---
        print("\n" + "=" * 60)
        print("JPEG image - Restaurant Invoice (text output)")
        print("=" * 60 + "\n")

        await knowledge.ainsert(
            name="Restaurant_Invoice",
            path="cookbook/07_knowledge/testing_resources/restaurant_invoice.jpeg",
            reader=DoclingReader(output_format="text"),
        )
        agent.print_response(
            "What is the total amount on the restaurant invoice?",
            stream=True,
        )

        # --- PNG image - Order summary ---
        print("\n" + "=" * 60)
        print("PNG image - Order Summary (markdown output)")
        print("=" * 60 + "\n")

        await knowledge.ainsert(
            name="Order_Summary",
            path="cookbook/07_knowledge/testing_resources/restaurant_invoice.png",
            reader=DoclingReader(output_format="markdown"),
        )
        agent.print_response(
            "What items were ordered according to the order summary?",
            stream=True,
        )

        # --- WAV audio - Agno description with HTML output ---
        print("\n" + "=" * 60)
        print("WAV audio - Agno Description (HTML output)")
        print("=" * 60 + "\n")

        await knowledge.ainsert(
            name="Agno_Audio_WAV",
            path="cookbook/07_knowledge/testing_resources/agno_description.wav",
            reader=DoclingReader(output_format="html"),
        )
        agent.print_response(
            "What does the audio describe about Agno?",
            stream=True,
        )

        # --- MP3 audio - Agno description ---
        print("\n" + "=" * 60)
        print("MP3 audio - Agno Description (markdown output)")
        print("=" * 60 + "\n")

        await knowledge.ainsert(
            name="Agno_Audio_MP3",
            path="cookbook/07_knowledge/testing_resources/agno_description.mp3",
            reader=DoclingReader(),
        )
        agent.print_response(
            "Summarize what Agno framework is used for",
            stream=True,
        )

        # --- MP4 audio - Agno description with VTT output ---
        print("\n" + "=" * 60)
        print("MP4 audio - Agno Description (VTT output)")
        print("=" * 60 + "\n")

        await knowledge.ainsert(
            name="Agno_Audio_MP4",
            path="cookbook/07_knowledge/testing_resources/agno_description.mp4",
            reader=DoclingReader(output_format="vtt"),
        )
        agent.print_response(
            "What are the key features of Agno mentioned in the audio?",
            stream=True,
        )

        # --- XLSX file - Sample products with HTML output ---
        print("\n" + "=" * 60)
        print("XLSX file - Sample Products (HTML output)")
        print("=" * 60 + "\n")

        await knowledge.ainsert(
            name="Sample_Products",
            path="cookbook/07_knowledge/testing_resources/sample_products.xlsx",
            reader=DoclingReader(output_format="html"),
        )
        agent.print_response(
            "What products are available and what are their prices?",
            stream=True,
        )

        # --- XML USPTO file - Patent document with markdown output ---
        print("\n" + "=" * 60)
        print("XML USPTO file - Patent Document (markdown output)")
        print("=" * 60 + "\n")

        await knowledge.ainsert(
            name="Patent_USPTO",
            path="cookbook/07_knowledge/testing_resources/patent_sample.xml",
            reader=DoclingReader(output_format="markdown"),
        )
        agent.print_response(
            "What is the patent about and who is the inventor?",
            stream=True,
        )

        # --- LaTeX file - Research paper with text output ---
        print("\n" + "=" * 60)
        print("LaTeX file - Research Paper (text output)")
        print("=" * 60 + "\n")

        await knowledge.ainsert(
            name="Research_Paper_LaTeX",
            path="cookbook/07_knowledge/testing_resources/research_paper.tex",
            reader=DoclingReader(output_format="text"),
        )
        agent.print_response(
            "What is the main topic of the research paper and what are the key findings?",
            stream=True,
        )

        # --- HTML file - Company information with JSON output ---
        print("\n" + "=" * 60)
        print("HTML file - Company Information (JSON output)")
        print("=" * 60 + "\n")

        await knowledge.ainsert(
            name="Company_Info_HTML",
            path="cookbook/07_knowledge/testing_resources/company_info.html",
            reader=DoclingReader(output_format="json"),
        )
        agent.print_response(
            "Who are the members of the leadership team and what is their revenue growth?",
            stream=True,
        )

    asyncio.run(main())
