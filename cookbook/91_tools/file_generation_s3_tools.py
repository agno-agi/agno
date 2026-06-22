"""
File Generation Tool with S3 Example
This cookbook shows how to use the FileGenerationTool to generate various file types (JSON, CSV, PDF, TXT, DOCX, HTML)
and save them to an AWS S3 bucket instead of (or in addition to) the local disk.

Providing s3_bucket implies save_to_s3=True, mirroring how output_directory implies save_files.
The S3 location (s3://bucket/key) is reported in the agent's response, and
the generated File artifact includes a temporary presigned HTTPS URL at file.url
for browser rendering or downloading.

Requires boto3 (`pip install boto3`) and AWS credentials available via environment variables,
~/.aws config, or an IAM role. Set S3_BUCKET below to your own bucket name before running.
"""

from pathlib import Path

import boto3

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.tools.file_generation import FileGenerationTools

# Replace with your own bucket name.
S3_BUCKET = "yourbucket"
S3_PREFIX = "generated/"
AWS_REGION = "us-east-1"

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

# Providing s3_bucket enables S3 uploads (s3_prefix acts like a folder inside the bucket).
# Credentials fall back to environment variables / ~/.aws config / IAM role when not passed.
agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    db=SqliteDb(db_file="tmp/test.db"),
    tools=[
        FileGenerationTools(
            s3_bucket=S3_BUCKET,
            s3_prefix=S3_PREFIX,
            region_name=AWS_REGION,
            s3_presigned_url_expires_in=3600,
        )
    ],
    debug_mode=True,
    description="You are a helpful assistant that can generate files in various formats.",
    instructions=[
        "When asked to create files, use the appropriate file generation tools.",
        "Always provide meaningful content and appropriate filenames.",
        "Explain what you've created and where it was saved.",
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
                print(f"Temporary render URL: {file.url}")
    print()
    return response


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
                print(f"Temporary render URL: {file.url}")
    print()
    return response


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
                print(f"Temporary render URL: {file.url}")
    print()
    return response


def download_from_s3(response):
    """Download the generated files back from S3 to confirm they exist."""
    print("=== Downloading Generated Files from S3 ===")
    if response is None or not response.files:
        print("No files were generated.")
        return
    s3_client = boto3.client("s3", region_name=AWS_REGION)
    Path("tmp").mkdir(parents=True, exist_ok=True)
    for file in response.files:
        # The S3 key mirrors the upload: prefix + the generated filename.
        key = f"{S3_PREFIX}{file.filename}"
        local_path = Path("tmp") / file.filename
        s3_client.download_file(S3_BUCKET, key, str(local_path))
        print(
            f"Downloaded s3://{S3_BUCKET}/{key} -> {local_path} ({local_path.stat().st_size} bytes)"
        )
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
                print(f"Temporary render URL: {file.url}")
    print()
    return response


def example_docx_generation():
    """Example: Generate a DOCX file"""
    print("=== DOCX File Generation Example ===")
    response = agent.run(
        "Create a DOCX report about customer onboarding best practices. Include sections for welcome email, product tour, and success check-ins."
    )
    print(response.content)
    if response.files:
        for file in response.files:
            print(f"Generated file: {file.filename} ({file.size} bytes)")
            if file.url:
                print(f"Temporary render URL: {file.url}")
    print()
    return response


def example_html_generation():
    """Example: Generate an HTML file"""
    print("=== HTML File Generation Example ===")
    response = agent.run(
        "Create an HTML landing page for a coffee shop. Include a heading, a short intro, and a list of three signature drinks."
    )
    print(response.content)
    if response.files:
        for file in response.files:
            print(f"Generated file: {file.filename} ({file.size} bytes)")
            if file.url:
                print(f"Temporary render URL: {file.url}")
    print()
    return response


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("File Generation Tool with S3 Cookbook Example")
    print("=" * 50)

    # 1. Generate a file and upload it to S3.
    response = example_html_generation()
    # 2. Download it back from S3 to confirm it exists.
    download_from_s3(response)
