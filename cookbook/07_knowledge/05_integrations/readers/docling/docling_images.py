"""
Docling Reader: Image Documents
================================
Examples of using Docling to process image files with OCR capabilities.

Supported formats:
- JPEG: JPEG image files
- PNG: PNG image files

Docling uses advanced OCR to extract text from images including:
- Invoices and receipts
- Screenshots
- Scanned documents
- Any image with text content

Run `uv pip install docling openai-whisper` to install dependencies.
"""

import asyncio

from agno.knowledge.reader.docling_reader import DoclingReader
from utils import get_agent, get_knowledge

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

knowledge = get_knowledge(table_name="docling_images")
agent = get_agent(knowledge)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":

    async def main():
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

    asyncio.run(main())
