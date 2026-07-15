"""
Docling Reader: Markup and Structured Documents
================================================
Examples of using Docling to process markup and structured document formats.

Supported formats:
- XML: Extensible Markup Language (including USPTO patent format)
- HTML: HyperText Markup Language
- LaTeX: LaTeX document format

These formats contain structured data and formatting that Docling preserves during conversion.

Run `uv pip install docling openai-whisper` to install dependencies.
"""

import asyncio

from agno.knowledge.reader.docling_reader import DoclingReader
from utils import get_agent, get_knowledge

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

knowledge = get_knowledge(table_name="docling_markup")
agent = get_agent(knowledge)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":

    async def main():
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
