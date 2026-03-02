"""Google Slides Tools

Requirements:
1. `pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib`
2. Set environment variables:
   export GOOGLE_CLIENT_ID=your_client_id
   export GOOGLE_CLIENT_SECRET=your_client_secret
   export GOOGLE_PROJECT_ID=your_project_id
"""

from agno.agent import Agent
from agno.tools.google.slides import GoogleSlidesTools

agent = Agent(
    tools=[GoogleSlidesTools()],
    markdown=True,
)

agent.print_response(
    "Create a presentation titled 'Team Update' and add a slide with title 'Agenda' and body 'Project status, timelines, next steps'",
    stream=True,
)
