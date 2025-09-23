import tempfile
from pathlib import Path

import pytest

from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.csv_reader import CSVReader
from agno.models.anthropic.claude import Claude
from agno.models.google.gemini import Gemini
from agno.models.openai.chat import OpenAIChat
from agno.vectordb.chroma import ChromaDb

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


@pytest.fixture
async def knowledge_base(setup_csv_files):
    vector_db = ChromaDb(collection="vectors", path="tmp/chromadb", persistent_client=True)

    # Use the temporary directory with CSV files
    csv_dir = Path(setup_csv_files) / "csvs"
    print(f"Testing with CSV directory: {csv_dir}")

    # Create a knowledge base with the test CSV files
    knowledge = Knowledge(
        vector_db=vector_db,
    )

    reader = CSVReader(
        chunk=False,
    )

    await knowledge.add_content_async(
        path=str(csv_dir),
        reader=reader,
        metadata={"data_type": "sales", "region": "north_america", "currency": "USD"},
    )
    return knowledge


async def test_agentic_filtering_openai(knowledge_base):
    agent = Agent(model=OpenAIChat("gpt-4o-mini"), knowledge=knowledge_base, enable_agentic_knowledge_filters=True)
    response = await agent.arun(
        "Tell me about revenue performance and top selling products in the region north_america and data_type sales",
        markdown=True,
    )
    found_tool = False
    for tool in response.tools:
        if tool.tool_name == "search_knowledge_base_with_agentic_filters":
            assert tool.tool_args["filters"] == [
                {"key": "region", "value": "north_america"},
                {"key": "data_type", "value": "sales"},
            ]
            found_tool = True
            break
    assert found_tool


async def test_agentic_filtering_gemini(knowledge_base):
    agent = Agent(model=Gemini("gemini-2.0-flash-001"), knowledge=knowledge_base, enable_agentic_knowledge_filters=True)
    response = await agent.arun(
        "Tell me about revenue performance and top selling products in the region north_america and data_type sales",
        markdown=True,
    )
    found_tool = False
    for tool in response.tools:
        if tool.tool_name == "search_knowledge_base_with_agentic_filters":
            assert tool.tool_args["filters"] == [
                {"key": "region", "value": "north_america"},
                {"key": "data_type", "value": "sales"},
            ]
            found_tool = True
            break
    assert found_tool


async def test_agentic_filtering_claude(knowledge_base):
    agent = Agent(model=Claude("claude-sonnet-4-0"), knowledge=knowledge_base, enable_agentic_knowledge_filters=True)
    response = await agent.arun(
        "Tell me about revenue performance and top selling products in the region north_america and data_type sales",
        markdown=True,
    )
    found_tool = False
    for tool in response.tools:
        if tool.tool_name == "search_knowledge_base_with_agentic_filters":
            assert tool.tool_args["filters"] == [
                {"key": "region", "value": "north_america"},
                {"key": "data_type", "value": "sales"},
            ]
            found_tool = True
            break
    assert found_tool
