"""
1. Install dependencies using: `pip install openai duckduckgo-search sqlalchemy 'fastapi[standard]' newspaper4k lxml_html_clean yfinance agno`
2. Run the script using: `python cookbook/workflows/workflows_playground.py`
"""

from agno.playground import Playground

# Import the workflows
from blog_post_generator import blog_generator_workflow
from investment_report_generator import investment_workflow
from startup_idea_validator import startup_validation_workflow

# Initialize the Playground with the workflows
playground = Playground(
    workflows=[
        blog_generator_workflow,
        investment_workflow,
        startup_validation_workflow,
    ],
    app_id="workflows-playground-app",
    name="Workflows Playground",
)
app = playground.get_app()

if __name__ == "__main__":
    # Start the playground server
    playground.serve(
        app="playground_demo:app",
        host="localhost",
        port=7777,
        reload=True,
    )
