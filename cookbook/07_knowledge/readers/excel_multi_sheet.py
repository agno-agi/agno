from pathlib import Path

from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.excel_reader import ExcelReader
from agno.models.openai import OpenAIChat
from agno.vectordb.pgvector import PgVector

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

# Path to the multi-sheet test workbook
data_path = (
    Path(__file__).parent.parent
    / "testing_resources"
    / "excel_samples"
    / "multi_sheet_test.xlsx"
)


def demo_selective_sheet_loading():
    """Demonstrate loading only specific sheets from a workbook."""
    print("\n" + "=" * 60)
    print("Demo 1: Selective Sheet Loading")
    print("=" * 60)

    # Load only Products and Categories sheets - useful when workbook has
    # many sheets but you only need specific ones
    reader = ExcelReader(sheets=["Products", "Categories"])

    knowledge_base = Knowledge(
        vector_db=PgVector(
            table_name="excel_multi_sheet_selective",
            db_url=db_url,
        ),
    )

    knowledge_base.insert(
        path=str(data_path),
        reader=reader,
    )

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        knowledge=knowledge_base,
        search_knowledge=True,
        instructions=[
            "You are a product catalog assistant.",
            "Use the knowledge base to answer questions about products and categories.",
            "The Products sheet has: Product ID, Name, Price, In Stock, Added Date, Description.",
            "The Categories sheet has: Category ID, Category Name, Parent Category.",
        ],
    )

    print("\n--- Query: Product inventory ---\n")
    agent.print_response(
        "What products are currently in stock? Include their prices.",
        markdown=True,
        stream=True,
    )

    print("\n--- Query: Category hierarchy ---\n")
    agent.print_response(
        "List all the product categories and their parent categories.",
        markdown=True,
        stream=True,
    )


def demo_unicode_content():
    """Demonstrate handling Unicode content from international data."""
    print("\n" + "=" * 60)
    print("Demo 2: Unicode Content Handling")
    print("=" * 60)

    # Load only the International sheet with Unicode greetings
    reader = ExcelReader(sheets=["International"])

    knowledge_base = Knowledge(
        vector_db=PgVector(
            table_name="excel_multi_sheet_unicode",
            db_url=db_url,
        ),
    )

    knowledge_base.insert(
        path=str(data_path),
        reader=reader,
    )

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        knowledge=knowledge_base,
        search_knowledge=True,
        instructions=[
            "You are an international data assistant.",
            "Use the knowledge base to answer questions about international greetings and data.",
            "The data contains: Country, Greeting (in native language), Currency Symbol, Special notes.",
        ],
    )

    print("\n--- Query: International greetings ---\n")
    agent.print_response(
        "What are the greetings in Japanese and Chinese? Show the native text.",
        markdown=True,
        stream=True,
    )


def demo_all_sheets():
    """Demonstrate loading all sheets and querying across them."""
    print("\n" + "=" * 60)
    print("Demo 3: Full Workbook Loading")
    print("=" * 60)

    # Load all sheets (default behavior)
    reader = ExcelReader()

    knowledge_base = Knowledge(
        vector_db=PgVector(
            table_name="excel_multi_sheet_all",
            db_url=db_url,
        ),
    )

    knowledge_base.insert(
        path=str(data_path),
        reader=reader,
    )

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        knowledge=knowledge_base,
        search_knowledge=True,
        instructions=[
            "You are a data assistant with access to multiple Excel sheets.",
            "The workbook contains: Products, Categories, International, Edge Cases, and Numbers sheets.",
            "When answering, mention which sheet the data comes from if relevant.",
        ],
    )

    print("\n--- Query: Cross-sheet search ---\n")
    agent.print_response(
        "What numerical data is available? Show quarterly figures if any.",
        markdown=True,
        stream=True,
    )

    print("\n--- Query: Price search ---\n")
    agent.print_response(
        "What is the most expensive product and how much does it cost?",
        markdown=True,
        stream=True,
    )


if __name__ == "__main__":
    print("=" * 60)
    print("Excel Multi-Sheet Workbook - Sheet Filtering & Unicode")
    print("=" * 60)

    demo_selective_sheet_loading()
    demo_unicode_content()
    demo_all_sheets()
