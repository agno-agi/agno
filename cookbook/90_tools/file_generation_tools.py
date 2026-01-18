"""
File Generation Tool Example
This cookbook shows how to use the FileGenerationTool to generate various file types (JSON, CSV, PDF, TXT).
The tool can generate files from agent responses and make them available for download or further processing.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.tools.file_generation import FileGenerationTools

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    db=SqliteDb(db_file="tmp/test.db"),
    tools=[FileGenerationTools(output_directory="tmp")],
    description="You are a helpful assistant that can generate files in various formats.",
    instructions=[
        "When asked to create files, use the appropriate file generation tools.",
        "Always provide meaningful content and appropriate filenames.",
        "Explain what you've created and how it can be used.",
    ],
    markdown=True,
)


def example_json_generation():
    """Example: Generate a JSON file"""
    print("=== JSON File Generation Example ===")
    response = agent.run(
        "Create a JSON file containing information about 3 fictional employees with name, position, department, and salary."
    )
    print(response.content)
    if response.files:
        for file in response.files:
            print(f"Generated file: {file.filename} ({file.size} bytes)")
            if file.url:
                print(f"File location: {file.url}")
    print()


def example_csv_generation():
    """Example: Generate a CSV file"""
    print("=== CSV File Generation Example ===")
    response = agent.run(
        "Create a CSV file with sales data for the last 6 months. Include columns for month, product, units_sold, and revenue."
    )
    print(response.content)
    if response.files:
        for file in response.files:
            print(f"Generated file: {file.filename} ({file.size} bytes)")
            if file.url:
                print(f"File location: {file.url}")
    print()


def example_pdf_generation():
    """Example: Generate a PDF file"""
    print("=== PDF File Generation Example ===")
    response = agent.run(
        "Create a PDF report about renewable energy trends in 2024. Include sections on solar, wind, and hydroelectric power."
    )
    print(response.content)
    if response.files:
        for file in response.files:
            print(f"Generated file: {file.filename} ({file.size} bytes)")
            if file.url:
                print(f"File location: {file.url}")
    print()


def example_text_generation():
    """Example: Generate a text file"""
    print("=== Text File Generation Example ===")
    response = agent.run(
        "Create a text file with a list of best practices for remote work productivity."
    )
    print(response.content)
    if response.files:
        for file in response.files:
            print(f"Generated file: {file.filename} ({file.size} bytes)")
            if file.url:
                print(f"File location: {file.url}")
    print()


if __name__ == "__main__":
    print("File Generation Tool Cookbook Example")
    print("=" * 50)

    example_pdf_generation()
