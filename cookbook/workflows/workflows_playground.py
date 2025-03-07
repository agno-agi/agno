"""
1. Install dependencies using: `pip install openai duckduckgo-search sqlalchemy 'fastapi[standard]' newspaper4k lxml_html_clean yfinance agno`
2. Run the script using: `python cookbook/workflows/workflows_playground.py`
"""

from agno.playground import Playground, serve_playground_app
from agno.storage.sqlite import SqliteStorage

# Import the workflows
from blog_post_generator import BlogPostGenerator
from investment_report_generator import (
    InvestmentReportGenerator,
)
from personalized_email_generator import PersonalisedEmailGenerator
from startup_idea_validator import StartupIdeaValidator

# Initialize the workflows with SQLite storage

blog_post_generator = BlogPostGenerator(
    workflow_id="generate-blog-post",
    storage=SqliteStorage(
        table_name="generate_blog_post_workflows",
        db_file="tmp/agno_workflows.db",
    ),
)
personalised_email_generator = PersonalisedEmailGenerator(
    workflow_id="personalized-email-generator",
    storage=SqliteStorage(
        table_name="personalized_email_workflows",
        db_file="tmp/agno_workflows.db",
    ),
)

investment_report_generator = InvestmentReportGenerator(
    workflow_id="generate-investment-report",
    storage=SqliteStorage(
        table_name="investment_report_workflows",
        db_file="tmp/agno_workflows.db",
    ),
)

startup_idea_validator = StartupIdeaValidator(
    workflow_id="validate-startup-idea",
    storage=SqliteStorage(
        table_name="validate_startup_ideas_workflow",
        db_file="tmp/agno_workflows.db",
    ),
)

# Initialize the Playground with the workflows
app = Playground(
    workflows=[
        blog_post_generator,
        personalised_email_generator,
        investment_report_generator,
        startup_idea_validator,
    ]
).get_app()

if __name__ == "__main__":
    serve_playground_app("workflows_playground:app", reload=True)
