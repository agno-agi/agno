from agno.document.reader.website_reader import WebsiteReader

reader = WebsiteReader(max_depth=3, max_links=10)

try:
    print("Starting read...")
    documents = reader.read("https://docs.agno.com/introduction")
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
