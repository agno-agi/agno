"""
Joke Writer with Contacts: local and remote agents working together.

A freelance joke writer agent with three contacts: a local safety-check agent,
a remote news agent and a remote publishing team on the news agency AgentOS.
The model messages contacts through the message_contact tool; each contacted
entity runs like a child run inside the writer's session, streaming nested
events into the chat under the contact's own name.

Start the news agency server first: python cookbook/05_agent_os/contacts/server.py
Then run: python cookbook/05_agent_os/contacts/01_joke_writer.py
"""

from agno.agent import Agent
from agno.agent.remote import RemoteAgent
from agno.contacts import Contact
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.team.remote import RemoteTeam
from agno.tools.openai import OpenAITools

db = SqliteDb(id="joke-writer-db", db_file="tmp/contacts_joke_writer.db")

# =============================================================================
# Contacts
# =============================================================================

news_agent = RemoteAgent(base_url="http://localhost:7778", agent_id="news-agent")
publish_team = RemoteTeam(base_url="http://localhost:7778", team_id="publish-team")

safety_check = Agent(
    name="Safety Check",
    id="safety-check",
    model=OpenAIResponses(id="gpt-5.5"),
    instructions="Check if the given statement is offensive or derogatory. Reply with SAFE or UNSAFE and a one-line reason.",
)

news_reporter = Contact(
    agent=news_agent,
    instructions="Contact to get the latest news",
)

publishing_department = Contact(
    team=publish_team,
    instructions="Contact to get the joke/cartoon/meme published",
)

pr_check = Contact(
    agent=safety_check,
    instructions="Contact to see if a generated joke/meme is safe",
)

# =============================================================================
# The Joke Writer
# =============================================================================

joke_writer = Agent(
    name="Joke Writer",
    id="joke-writer",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    instructions=(
        "You are a freelance joke writer for a news agency. "
        "Create jokes, memes and cartoons from the latest news, "
        "have them reviewed for safety and send them for publishing. "
        "When a meme or cartoon is requested, generate exactly one single-image meme with the generate_image tool."
    ),
    tools=[
        OpenAITools(
            enable_transcription=False,
            enable_speech_generation=False,
            image_model="gpt-image-1",
        )
    ],
    contacts=[pr_check, publishing_department, news_reporter],
    markdown=True,
)

agent_os = AgentOS(
    id="joke-writer-os",
    description="Freelance joke writer with local and remote contacts",
    agents=[joke_writer, safety_check],
)

app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="01_joke_writer:app", access_log=True, port=7777)
