"""
Demonstrates isolate_vector_search combined with list-based FilterExpr filters.

When multiple Knowledge instances share the same vector database and
isolate_vector_search=True, each instance's searches are scoped to its own data
via an auto-injected linked_to filter. This works seamlessly with user-supplied
FilterExpr filters — the linked_to filter is prepended automatically.

This cookbook shows:
1. Two Knowledge instances sharing one vector database, each isolated.
2. Inserting documents with metadata into each instance.
3. Querying via an Agent with knowledge_filters using EQ, IN, AND, NOT operators.
4. The linked_to filter is auto-injected alongside user filters.
"""

from agno.agent import Agent
from agno.filters import AND, EQ, IN, NOT
from agno.knowledge.knowledge import Knowledge
from agno.utils.media import (
    SampleDataFileExtension,
    download_knowledge_filters_sample_data,
)
from agno.vectordb.pgvector import PgVector

# Download sample CSV files — 4 files with sales/survey/financial data
downloaded_csv_paths = download_knowledge_filters_sample_data(
    num_files=4, file_extension=SampleDataFileExtension.CSV
)

# Shared vector database — both Knowledge instances use the same table
vector_db = PgVector(
    table_name="isolated_filter_demo",
    db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
)

# -----------------------------------------------------------------------------
# Two isolated Knowledge instances sharing the same vector database
# -----------------------------------------------------------------------------

sales_knowledge = Knowledge(
    name="sales-data",
    description="Sales and financial data",
    vector_db=vector_db,
    isolate_vector_search=True,  # Scoped to sales-data documents only
)

survey_knowledge = Knowledge(
    name="survey-data",
    description="Customer survey data",
    vector_db=vector_db,
    isolate_vector_search=True,  # Scoped to survey-data documents only
)

# -----------------------------------------------------------------------------
# Insert documents into each isolated instance
# Documents are tagged with linked_to metadata automatically
# -----------------------------------------------------------------------------

# Sales documents go into the sales knowledge instance
sales_knowledge.insert_many(
    [
        {
            "path": downloaded_csv_paths[0],
            "metadata": {
                "data_type": "sales",
                "quarter": "Q1",
                "year": 2024,
                "region": "north_america",
                "currency": "USD",
            },
        },
        {
            "path": downloaded_csv_paths[1],
            "metadata": {
                "data_type": "sales",
                "year": 2024,
                "region": "europe",
                "currency": "EUR",
            },
        },
        {
            "path": downloaded_csv_paths[3],
            "metadata": {
                "data_type": "financial",
                "sector": "technology",
                "year": 2024,
                "report_type": "quarterly_earnings",
            },
        },
    ],
)

# Survey documents go into the survey knowledge instance
survey_knowledge.insert_many(
    [
        {
            "path": downloaded_csv_paths[2],
            "metadata": {
                "data_type": "survey",
                "survey_type": "customer_satisfaction",
                "year": 2024,
                "target_demographic": "mixed",
            },
        },
    ],
)

# -----------------------------------------------------------------------------
# Query with list-based FilterExpr filters
# The linked_to filter is auto-injected alongside any user-supplied filters
# -----------------------------------------------------------------------------

sales_agent = Agent(
    knowledge=sales_knowledge,
    search_knowledge=True,
)

survey_agent = Agent(
    knowledge=survey_knowledge,
    search_knowledge=True,
)

# EQ filter on the sales-isolated instance
# Effective filters: linked_to="sales-data" AND region="north_america"
print("--- Sales agent: EQ filter (North America only) ---")
sales_agent.print_response(
    "Describe revenue performance for the region",
    knowledge_filters=[EQ("region", "north_america")],
    markdown=True,
)

# IN filter on the sales-isolated instance
# Effective filters: linked_to="sales-data" AND region IN ["north_america", "europe"]
print("--- Sales agent: IN filter (multiple regions) ---")
sales_agent.print_response(
    "Compare revenue across regions",
    knowledge_filters=[IN("region", ["north_america", "europe"])],
    markdown=True,
)

# AND + NOT compound filter on the sales-isolated instance
# Effective filters: linked_to="sales-data" AND data_type="sales" AND NOT region="europe"
print("--- Sales agent: AND + NOT compound filter ---")
sales_agent.print_response(
    "Describe revenue performance excluding Europe",
    knowledge_filters=[AND(EQ("data_type", "sales"), NOT(EQ("region", "europe")))],
    markdown=True,
)

# Survey agent — isolated to survey-data only, even though it shares the same vector DB
# Effective filters: linked_to="survey-data" AND survey_type="customer_satisfaction"
print("--- Survey agent: EQ filter (customer satisfaction) ---")
survey_agent.print_response(
    "Summarize the customer satisfaction survey results",
    knowledge_filters=[EQ("survey_type", "customer_satisfaction")],
    markdown=True,
)
