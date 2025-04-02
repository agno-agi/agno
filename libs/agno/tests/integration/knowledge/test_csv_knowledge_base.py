import io
import tempfile
from pathlib import Path

import pytest

from agno.agent import Agent
from agno.knowledge.csv import CSVKnowledgeBase
from agno.vectordb.lancedb.lance_db import LanceDb

# Sample CSV data to use in tests
EMPLOYEE_CSV_DATA = """id,name,department,salary,years_experience
1,John Smith,Engineering,75000,5
2,Sarah Johnson,Marketing,65000,3
3,Michael Brown,Finance,85000,8
4,Jessica Lee,Engineering,80000,6
5,David Wilson,HR,55000,2
6,Emily Chen,Product,70000,4
7,Robert Miller,Engineering,90000,10
8,Amanda White,Marketing,60000,3
9,Thomas Garcia,Finance,82000,7
10,Lisa Thompson,Engineering,78000,5
"""

SALES_CSV_DATA = """quarter,region,product,revenue,units_sold
Q1,North,Laptop,128500,85
Q1,South,Laptop,95000,65
Q1,East,Laptop,110200,75
Q1,West,Laptop,142300,95
Q2,North,Laptop,138600,90
Q2,South,Laptop,105800,70
Q2,East,Laptop,115000,78
Q2,West,Laptop,155000,100
"""


@pytest.fixture
def setup_csv_files():
    """Create temporary CSV files for testing."""
    with tempfile.TemporaryDirectory() as temp_dir:
        # Create the directory for CSV files
        data_dir = Path(temp_dir) / "csvs"
        data_dir.mkdir(parents=True, exist_ok=True)

        # Create employees.csv
        employee_path = data_dir / "employees.csv"
        with open(employee_path, "w") as f:
            f.write(EMPLOYEE_CSV_DATA)

        # Create sales.csv
        sales_path = data_dir / "sales.csv"
        with open(sales_path, "w") as f:
            f.write(SALES_CSV_DATA)

        yield temp_dir


def test_csv_knowledge_base(setup_csv_files):
    vector_db = LanceDb(
        table_name="employees",
        uri="tmp/lancedb",
    )

    # Use the temporary directory with CSV files
    csv_dir = Path(setup_csv_files) / "csvs"
    print(f"Testing with CSV directory: {csv_dir}")

    # Create a knowledge base with the test CSV files
    knowledge_base = CSVKnowledgeBase(
        path=str(csv_dir),
        vector_db=vector_db,
    )
    knowledge_base.reader.chunk = False

    knowledge_base.load(recreate=True)

    assert vector_db.exists()

    assert vector_db.get_count() == 2

    agent = Agent(knowledge=knowledge_base)
    response = agent.run("Tell me about the employees in the Engineering department", markdown=True)

    assert any(term in response.content.lower() for term in ["engineering", "employee", "department"])

    vector_db.drop()


def test_csv_knowledge_base_single_file():
    """Test with a single in-memory CSV file."""
    vector_db = LanceDb(
        table_name="sales",
        uri="tmp/lancedb",
    )
    csv_file = io.StringIO(SALES_CSV_DATA)
    csv_file.name = "sales.csv"
    with tempfile.NamedTemporaryFile(suffix=".csv", mode="w+") as temp_file:
        temp_file.write(SALES_CSV_DATA)
        temp_file.flush()

        knowledge_base = CSVKnowledgeBase(
            path=temp_file.name,
            vector_db=vector_db,
        )
        knowledge_base.reader.chunk = False

        knowledge_base.load(recreate=True)

        assert vector_db.exists()
        assert vector_db.get_count() == 1

        # Create and use the agent
        agent = Agent(knowledge=knowledge_base)
        response = agent.run("What was the revenue for the West region?", markdown=True)

        assert any(term in response.content.lower() for term in ["west", "revenue", "region"])

        vector_db.drop()


@pytest.mark.asyncio
async def test_csv_knowledge_base_async(setup_csv_files):
    vector_db = LanceDb(
        table_name="employees_async",
        uri="tmp/lancedb",
    )
    csv_dir = Path(setup_csv_files) / "csvs"

    knowledge_base = CSVKnowledgeBase(
        path=str(csv_dir),
        vector_db=vector_db,
    )
    knowledge_base.reader.chunk = False

    await knowledge_base.aload(recreate=True)

    assert await vector_db.async_exists()
    count = await vector_db.async_get_count()
    assert count >= 2

    # Create and use the agent
    agent = Agent(knowledge=knowledge_base)
    response = await agent.arun("Which employees have salaries above 80000?", markdown=True)

    # Check for relevant content in the response
    assert any(term in response.content.lower() for term in ["salary", "80000", "employee"])

    # Clean up
    await vector_db.async_drop()


@pytest.mark.asyncio
async def test_csv_knowledge_base_async_single_file():
    """Test with a single in-memory CSV file asynchronously."""
    vector_db = LanceDb(
        table_name="sales_async",
        uri="tmp/lancedb",
    )

    with tempfile.NamedTemporaryFile(suffix=".csv", mode="w+") as temp_file:
        temp_file.write(SALES_CSV_DATA)
        temp_file.flush()

        knowledge_base = CSVKnowledgeBase(
            path=temp_file.name,
            vector_db=vector_db,
        )
        knowledge_base.reader.chunk = False

        await knowledge_base.aload(recreate=True)

        assert await vector_db.async_exists()
        count = await vector_db.async_get_count()
        assert count >= 1

        agent = Agent(knowledge=knowledge_base)
        response = await agent.arun("Compare Q1 and Q2 laptop sales", markdown=True)

        assert any(term in response.content.lower() for term in ["q1", "q2", "laptop", "sales"])

        await vector_db.async_drop()
