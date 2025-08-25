import os

from agno.knowledge.reader.firecrawl_reader import FirecrawlReader

api_key = os.getenv("FIRECRAWL_API_KEY")

reader = FirecrawlReader(
    api_key=api_key,
    mode="scrape",
    chunk=True,
    # for crawling
    # params={
    #     'limit': 5,
    #     'scrapeOptions': {'formats': ['markdown']}
    # }
    # for scraping
    params={"formats": ["markdown"]},
)

try:
    print("Starting scrape...")
    documents = reader.read("https://github.com/agno-agi/agno")

    if documents:
        for doc in documents:
            print(doc.name)
            print(doc.content)
            print(f"Content length: {len(doc.content)}")
            print("-" * 80)
    else:
        print("No documents were returned")

except Exception as e:
    print(f"Error type: {type(e)}")
    print(f"Error occurred: {str(e)}")
