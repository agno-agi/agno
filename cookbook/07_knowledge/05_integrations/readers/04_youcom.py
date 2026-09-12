"""
You.com Knowledge Readers
==========================
Search, contents, research, and finance readers for RAG ingestion.
"""

import asyncio
import os

from agno.knowledge.reader.youcom.contents_reader import YouContentsReader
from agno.knowledge.reader.youcom.finance_reader import YouFinanceResearchReader
from agno.knowledge.reader.youcom.research_reader import YouResearchReader
from agno.knowledge.reader.youcom.search_reader import YouSearchReader


API_KEY = os.getenv("YDC_API_KEY")


async def main() -> None:
    search_reader = YouSearchReader(api_key=API_KEY, chunk=False, count=3)
    search_docs = await search_reader.async_read("agno rag readers")
    print("SEARCH")
    for doc in search_docs[:2]:
        print(doc.name)
        print(doc.meta_data)
        print(doc.content[:400])
        print()

    contents_reader = YouContentsReader(api_key=API_KEY, chunk=False)
    content_docs = await contents_reader.async_read(["https://you.com/docs/api-reference/contents"])
    print("CONTENTS")
    for doc in content_docs[:1]:
        print(doc.name)
        print(doc.meta_data)
        print(doc.content[:400])
        print()

    research_reader = YouResearchReader(api_key=API_KEY, chunk=False, include_source_documents=True)
    research_docs = await research_reader.async_read("How does Agno use knowledge readers?")
    print("RESEARCH")
    for doc in research_docs[:2]:
        print(doc.name)
        print(doc.meta_data)
        print(doc.content[:400])
        print()

    finance_reader = YouFinanceResearchReader(api_key=API_KEY, chunk=False, include_source_documents=True)
    finance_docs = await finance_reader.async_read("What drove NVIDIA revenue growth in fiscal 2025?")
    print("FINANCE")
    for doc in finance_docs[:2]:
        print(doc.name)
        print(doc.meta_data)
        print(doc.content[:400])
        print()


if __name__ == "__main__":
    asyncio.run(main())
