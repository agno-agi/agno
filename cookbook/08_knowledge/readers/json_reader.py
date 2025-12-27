import json
from pathlib import Path

from agno.knowledge.reader.json_reader import JSONReader

reader = JSONReader()

json_path = Path("tmp/test.json")
test_data = {"key": "value"}
json_path.write_text(json.dumps(test_data))

try:
    print("Starting read...")
    documents = reader.read(json_path)

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
