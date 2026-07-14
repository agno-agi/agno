"""
Docling Reader: PDF Documents
==============================
Examples of using Docling to process PDF files with different output formats.
"""

import asyncio

from agno.knowledge.reader.docling_reader import DoclingReader
from utils import get_agent, get_knowledge

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

knowledge = get_knowledge(table_name="docling_pdf")
agent = get_agent(knowledge)

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

    asyncio.run(main())
