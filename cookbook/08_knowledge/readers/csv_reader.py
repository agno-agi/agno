from pathlib import Path

from agno.knowledge.reader.csv_reader import CSVReader

reader = CSVReader()

csv_path = Path("tmp/test.csv")


try:
    print("Starting read...")
    documents = reader.read(csv_path)

    if documents:
        for doc in documents:
            print(doc.name)
            # print(doc.content)
            print(f"Content length: {len(doc.content)}")
            print("-" * 80)
    else:
        print("No documents were returned")

except Exception as e:
    print(f"Error type: {type(e)}")
    print(f"Error occurred: {str(e)}")
