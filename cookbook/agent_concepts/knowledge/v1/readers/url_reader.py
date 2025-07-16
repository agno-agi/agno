from agno.document.chunking.recursive import RecursiveChunking
from agno.document.reader.url_reader import URLReader

reader = URLReader(chunking_strategy=RecursiveChunking(chunk_size=1000))

try:
    print("Starting read...")
    documents = reader.read("https://docs.agno.com/llms-full.txt")

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
