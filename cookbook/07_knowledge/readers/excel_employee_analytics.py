from pathlib import Path

from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.excel_reader import ExcelReader
from agno.models.openai import OpenAIChat
from agno.vectordb.pgvector import PgVector

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

# ExcelReader with RowChunking (default) - each row becomes a separate document
# This enables finding individual employees via semantic search
reader = ExcelReader()

knowledge_base = Knowledge(
    vector_db=PgVector(
        table_name="excel_employee_analytics",
        db_url=db_url,
    ),
)

# Path to the sample employee data
data_path = (
    Path(__file__).parent.parent
    / "testing_resources"
    / "excel_samples"
    / "Employee Sample Data.xlsx"
)

# Insert the Excel file - each of the 1000+ employee rows becomes a chunk
knowledge_base.insert(
    path=str(data_path),
    reader=reader,
)

agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    knowledge=knowledge_base,
    search_knowledge=True,
    instructions=[
        "You are an HR analytics assistant.",
        "Use the knowledge base to answer questions about employees.",
        "The data contains employee records with: EEID, Full Name, Job Title, Department, Business Unit, Gender, Ethnicity, Age, Hire Date, Annual Salary, Bonus %, Country, City, and Exit Date.",
        "When listing employees, include relevant details like name, title, and department.",
        "For statistical questions, analyze the retrieved records and provide insights.",
    ],
)

if __name__ == "__main__":
    print("=" * 60)
    print("Excel Employee Analytics - Real-world HR Data Queries")
    print("=" * 60)

    # Query 1: Find employees by department and role
    print("\n--- Query 1: IT Department Employees ---\n")
    agent.print_response(
        "List employees in the IT department. Show their names and job titles.",
        markdown=True,
        stream=True,
    )

    # Query 2: Filter by multiple criteria
    print("\n--- Query 2: Female Employees in R&D ---\n")
    agent.print_response(
        "Who are the female employees in Research & Development? Include their job titles.",
        markdown=True,
        stream=True,
    )

    # Query 3: Demographic analysis
    print("\n--- Query 3: Senior Technical Roles ---\n")
    agent.print_response(
        "Find employees who are Technical Architects or Senior Software Engineers. What can you tell me about their experience based on hire dates?",
        markdown=True,
        stream=True,
    )
