"""
Excel Enterprise Edge Cases - Fortune 500 Real-World Data Scenarios

This cookbook demonstrates handling messy enterprise Excel data including:
- Unicode/international characters (Chinese, Arabic, German)
- Error values (#DIV/0!, #N/A)
- Mixed data types in same column
- Empty rows interspersed in data
- Very long text fields (500+ chars)
- Scientific notation
- Negative values and refunds
- Boolean variations (True/False, Yes/No, 1/0)
- Leading/trailing whitespace
- Multi-row headers in corporate reports
- Wide tables (30+ columns)
"""

from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.excel_reader import ExcelReader
from agno.models.openai import OpenAIChat
from agno.vectordb.pgvector import PgVector

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

reader = ExcelReader()

knowledge_base = Knowledge(
    vector_db=PgVector(
        table_name="excel_enterprise_edge_cases",
        db_url=db_url,
    ),
)

knowledge_base.insert(
    path="cookbook/07_knowledge/testing_resources/excel_samples/enterprise_edge_cases.xlsx",
    reader=reader,
)

agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    knowledge=knowledge_base,
    search_knowledge=True,
    instructions=[
        "You are an enterprise data analyst.",
        "The data may contain messy real-world issues - handle them gracefully.",
        "Look for patterns in the data despite inconsistencies.",
        "When reporting financial figures, note any missing or estimated values.",
    ],
)

if __name__ == "__main__":
    print("=" * 60)
    print("Excel Enterprise Edge Cases - Fortune 500 Data Scenarios")
    print("=" * 60)

    # Test 1: Unicode/International characters
    print("\n--- Test 1: International customers (Unicode handling) ---\n")
    agent.print_response(
        "List all customers with non-English names (Chinese, Arabic). "
        "What products did they order?",
        markdown=True,
        stream=True,
    )

    # Test 2: Data quality issues
    print("\n--- Test 2: Data quality issues (TBD, missing values) ---\n")
    agent.print_response(
        "Find any transactions with missing or incomplete data. "
        "What fields are problematic?",
        markdown=True,
        stream=True,
    )

    # Test 3: Large numbers and precision
    print("\n--- Test 3: Large transactions (billion-dollar deals) ---\n")
    agent.print_response(
        "What was the largest transaction by total value? "
        "Are there any enterprise license deals?",
        markdown=True,
        stream=True,
    )

    # Test 4: Refunds and negative values
    print("\n--- Test 4: Refunds (negative values) ---\n")
    agent.print_response(
        "Are there any refunds or returns in the sales data? What was the reason?",
        markdown=True,
        stream=True,
    )

    # Test 5: Financial summary with estimates
    print("\n--- Test 5: Financial summary (corporate reporting) ---\n")
    agent.print_response(
        "What is the Operating Income trend across quarters? "
        "Are there any quarters with estimated or missing data?",
        markdown=True,
        stream=True,
    )

    # Test 6: Employee directory with international names
    print("\n--- Test 6: Employee names (international characters) ---\n")
    agent.print_response(
        "List employees in the Engineering department. "
        "Include their names even if they use non-Latin characters.",
        markdown=True,
        stream=True,
    )

    # Test 7: Wide table handling (inventory matrix)
    print("\n--- Test 7: Inventory status (wide table with 30+ warehouses) ---\n")
    agent.print_response(
        "Which products have LOW or DISCONTINUED status? "
        "What are their total inventory levels?",
        markdown=True,
        stream=True,
    )
