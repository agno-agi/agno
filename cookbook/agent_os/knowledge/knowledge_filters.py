"""
Examples demonstrating how to use FilterExpressions via the Agno API.

This cookbook shows how to serialize FilterExpr objects to JSON and send them
through HTTP APIs for knowledge base filtering.
"""

import json

from agno.filters import EQ, GT, IN, LT


def print_example(title: str, filter_expr, curl_command: str):
    """Helper to print examples in a readable format."""
    print(f"\n{'=' * 80}")
    print(f"Example: {title}")
    print(f"{'=' * 80}")
    print("\nFilter Expression:")
    print(f"  {filter_expr}")
    print("\nSerialized JSON:")
    serialized = filter_expr.to_dict()
    print(f"  {json.dumps(serialized, indent=2)}")
    print("\nCurl Command:")
    print(f"  {curl_command}")


# ============================================================
# Example 1: Simple Equality Filter
# ============================================================

filter_1 = EQ("category", "technology")
print_example(
    "Simple Equality Filter",
    filter_1,
    """curl -X 'POST' \\
  'http://localhost:7777/agents/my-agent/runs' \\
  -H 'accept: application/json' \\
  -H 'Content-Type: multipart/form-data' \\
  -F 'message=What are the latest tech articles?' \\
  -F 'stream=false' \\
  -F 'knowledge_filters={"op": "EQ", "key": "category", "value": "technology"}'""",
)


# ============================================================
# Example 2: IN Filter - Multiple Values
# ============================================================

filter_2 = IN("region", ["north_america", "europe", "asia"])
print_example(
    "IN Filter - Match Multiple Regions",
    filter_2,
    """curl -X 'POST' \\
  'http://localhost:7777/agents/my-agent/runs' \\
  -H 'accept: application/json' \\
  -H 'Content-Type: multipart/form-data' \\
  -F 'message=Show me the documents' \\
  -F 'stream=false' \\
  -F 'knowledge_filters={"op": "IN", "key": "region", "values": ["north_america", "europe", "asia"]}'""",
)


# ============================================================
# Example 3: Range Filter with GT and LT
# ============================================================

filter_3 = GT("views", 1000) & LT("views", 10000)
print_example(
    "Range Filter - Views between 1000 and 10000",
    filter_3,
    """curl -X 'POST' \\
  'http://localhost:7777/agents/my-agent/runs' \\
  -H 'accept: application/json' \\
  -H 'Content-Type: multipart/form-data' \\
  -F 'message=Find popular articles' \\
  -F 'stream=false' \\
  -F 'knowledge_filters={"op": "AND", "conditions": [{"op": "GT", "key": "views", "value": 1000}, {"op": "LT", "key": "views", "value": 10000}]}'""",
)


# ============================================================
# Example 4: Complex AND Filter
# ============================================================

filter_4 = (
    EQ("status", "published")
    & GT("word_count", 500)
    & IN("category", ["tech", "science"])
)
print_example(
    "Complex AND - Published tech/science articles with 500+ words",
    filter_4,
    """curl -X 'POST' \\
  'http://localhost:7777/agents/my-agent/runs' \\
  -H 'accept: application/json' \\
  -H 'Content-Type: multipart/form-data' \\
  -F 'message=Find detailed articles' \\
  -F 'stream=false' \\
  -F 'knowledge_filters={"op": "AND", "conditions": [{"op": "EQ", "key": "status", "value": "published"}, {"op": "GT", "key": "word_count", "value": 500}, {"op": "IN", "key": "category", "values": ["tech", "science"]}]}'""",
)


# ============================================================
# Example 5: OR Filter - Multiple Conditions
# ============================================================

filter_5 = EQ("priority", "high") | EQ("urgent", True)
print_example(
    "OR Filter - High priority OR urgent",
    filter_5,
    """curl -X 'POST' \\
  'http://localhost:7777/agents/my-agent/runs' \\
  -H 'accept: application/json' \\
  -H 'Content-Type: multipart/form-data' \\
  -F 'message=Show important documents' \\
  -F 'stream=false' \\
  -F 'knowledge_filters={"op": "OR", "conditions": [{"op": "EQ", "key": "priority", "value": "high"}, {"op": "EQ", "key": "urgent", "value": true}]}'""",
)


# ============================================================
# Example 6: NOT Filter - Exclusion
# ============================================================

filter_6 = ~EQ("status", "archived")
print_example(
    "NOT Filter - Exclude archived documents",
    filter_6,
    """curl -X 'POST' \\
  'http://localhost:7777/agents/my-agent/runs' \\
  -H 'accept: application/json' \\
  -H 'Content-Type: multipart/form-data' \\
  -F 'message=Show active documents' \\
  -F 'stream=false' \\
  -F 'knowledge_filters={"op": "NOT", "condition": {"op": "EQ", "key": "status", "value": "archived"}}'""",
)


# ============================================================
# Example 7: Complex Nested Logic
# ============================================================

filter_7 = (EQ("type", "article") & GT("word_count", 500)) | (
    EQ("type", "tutorial") & ~EQ("difficulty", "beginner")
)
print_example(
    "Complex Nested - Articles 500+ words OR advanced tutorials",
    filter_7,
    f"""curl -X 'POST' \\
  'http://localhost:7777/agents/my-agent/runs' \\
  -H 'accept: application/json' \\
  -H 'Content-Type: multipart/form-data' \\
  -F 'message=Find advanced content' \\
  -F 'stream=false' \\
  -F 'knowledge_filters={json.dumps(json.dumps(filter_7.to_dict()))}'""",
)


# ============================================================
# Example 8: Multiple Filters as List
# ============================================================

filters_list = [EQ("category", "technology"), GT("published_date", "2024-01-01")]
serialized_list = [f.to_dict() for f in filters_list]
print(f"\n{'=' * 80}")
print("Example: Multiple Filters as List")
print(f"{'=' * 80}")
print("\nFilter Expressions:")
for i, f in enumerate(filters_list, 1):
    print(f"  {i}. {f}")
print("\nSerialized JSON:")
print(f"  {json.dumps(serialized_list, indent=2)}")
print("\nCurl Command:")
print(f"""  curl -X 'POST' \\
  'http://localhost:7777/agents/my-agent/runs' \\
  -H 'accept: application/json' \\
  -H 'Content-Type: multipart/form-data' \\
  -F 'message=Find recent tech articles' \\
  -F 'stream=false' \\
  -F 'knowledge_filters={json.dumps(json.dumps(serialized_list))}'""")


# ============================================================
# Example 9: Python Client Helper Function
# ============================================================

print(f"\n{'=' * 80}")
print("Helper: Python Client Function")
print(f"{'=' * 80}")
print("""
def send_filtered_request(message: str, filters, agent_id: str = "my-agent", base_url: str = "http://localhost:7777"):
    import requests
    import json
    from agno.filters import FilterExpr
    
    # Serialize filters
    if isinstance(filters, FilterExpr):
        filters_json = json.dumps(filters.to_dict())
    elif isinstance(filters, list):
        filters_json = json.dumps([f.to_dict() if isinstance(f, FilterExpr) else f for f in filters])
    else:
        filters_json = json.dumps(filters)
    
    response = requests.post(
        f"{base_url}/agents/{agent_id}/runs",
        data={
            "message": message,
            "stream": "false",
            "knowledge_filters": filters_json,
        }
    )
    return response.json()

# Usage:
from agno.filters import EQ, GT, IN

# Simple filter
result = send_filtered_request(
    "What are agno's features?",
    EQ("docs", "agno")
)

# Complex filter
result = send_filtered_request(
    "Find detailed tech articles",
    (EQ("category", "tech") & GT("word_count", 500))
)

# Multiple filters
result = send_filtered_request(
    "Find recent content",
    [EQ("status", "published"), GT("date", "2024-01-01")]
)
""")


# ============================================================
# Example 10: Dict Filters Alternative
# ============================================================

print(f"\n{'=' * 80}")
print("Alternative: Dict Filters")
print(f"{'=' * 80}")
print("""
# Dict approach (simple key-value matching):
curl -X 'POST' \\
  'http://localhost:7777/agents/my-agent/runs' \\
  -F 'message=What are agno'\''s features?' \\
  -F 'knowledge_filters={"category": "technology", "status": "published"}'

# FilterExpr approach (complex logical conditions):
curl -X 'POST' \\
  'http://localhost:7777/agents/my-agent/runs' \\
  -F 'message=What are agno'\''s features?' \\
  -F 'knowledge_filters={"op": "AND", "conditions": [{"op": "EQ", "key": "category", "value": "technology"}, {"op": "EQ", "key": "status", "value": "published"}]}'

# Both approaches are supported! The API automatically detects the format.
""")


if __name__ == "__main__":
    print("\n" + "=" * 80)
    print("FilterExpressions API Examples Complete!")
    print("=" * 80)
    print("\nKey Points:")
    print("  1. FilterExpr objects have a .to_dict() method for serialization")
    print("  2. The API detects FilterExpr format by the presence of 'op' key")
    print("  3. Single FilterExpr or list of FilterExprs both work")
    print("  4. Dict filters are also supported (simple key-value matching)")
    print("  5. Complex nested logic is fully supported with FilterExpr")
    print("\nFor more info, see:")
    print("  - agno.filters module documentation")
    print("  - cookbook/knowledge/filters/filtering_with_conditions_on_agent.py")
    print("  - cookbook/knowledge/filters/API_FILTERS_GUIDE.md")
    print("=" * 80)
