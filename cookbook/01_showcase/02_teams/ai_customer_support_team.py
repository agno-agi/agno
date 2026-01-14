from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.website_reader import WebsiteReader
from agno.models.openai import OpenAIChat
from agno.team.team import Team
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.exa import ExaTools
from agno.tools.slack import SlackTools
from agno.vectordb.pgvector.pgvector import PgVector

knowledge = Knowledge(
    vector_db=PgVector(
        table_name="website_documents",
        db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
    ),
)

knowledge.add_content(
    url="https://docs.agno.com/introduction",
    reader=WebsiteReader(
        # Number of links to follow from the seed URLs
        max_links=10,
    ),
)


support_channel = "testing"
feedback_channel = "testing"

doc_researcher_agent = Agent(
    name="Doc researcher Agent",
    role="Search the knowledge base for information",
    model=OpenAIChat(id="gpt-4o"),
    tools=[DuckDuckGoTools(), ExaTools()],
    knowledge=knowledge,
    search_knowledge=True,
    instructions=[
        "You are a documentation expert for given product. Search the knowledge base thoroughly to answer user questions.",
        "Always provide accurate information based on the documentation.",
        "If the question matches an FAQ, provide the specific FAQ answer from the documentation.",
        "When relevant, include direct links to specific documentation pages that address the user's question.",
        "If you're unsure about an answer, acknowledge it and suggest where the user might find more information.",
        "Format your responses clearly with headings, bullet points, and code examples when appropriate.",
        "Always verify that your answer directly addresses the user's specific question.",
        "If you cannot find the answer in the documentation knowledge base, use the DuckDuckGoTools or ExaTools to search the web for relevant information to answer the user's question.",
    ],
)


escalation_manager_agent = Agent(
    name="Escalation Manager Agent",
    role="Escalate the issue to the slack channel",
    model=OpenAIChat(id="gpt-4o"),
    tools=[SlackTools()],
    instructions=[
        "You are an escalation manager responsible for routing critical issues to the support team.",
        f"When a user reports an issue, always send it to the #{support_channel} Slack channel with all relevant details using the send_message toolkit function.",
        "Include the user's name, contact information (if available), and a clear description of the issue.",
        "After escalating the issue, respond to the user confirming that their issue has been escalated.",
        "Your response should be professional and reassuring, letting them know the support team will address it soon.",
        "Always include a ticket or reference number if available to help the user track their issue.",
        "Never attempt to solve technical problems yourself - your role is strictly to escalate and communicate.",
    ],
)

feedback_collector_agent = Agent(
    name="Feedback Collector Agent",
    role="Collect feedback from the user",
    model=OpenAIChat(id="gpt-4o"),
    tools=[SlackTools()],
    description="You are an AI agent that can collect feedback from the user.",
    instructions=[
        "You are responsible for collecting user feedback about the product or feature requests.",
        f"When a user provides feedback or suggests a feature, use the Slack tool to send it to the #{feedback_channel} channel using the send_message toolkit function.",
        "Include all relevant details from the user's feedback in your Slack message.",
        "After sending the feedback to Slack, respond to the user professionally, thanking them for their input.",
        "Your response should acknowledge their feedback and assure them that it will be taken into consideration.",
        "Be warm and appreciative in your tone, as user feedback is valuable for improving our product.",
        "Do not promise specific timelines or guarantee that their suggestions will be implemented.",
    ],
)


customer_support_team = Team(
    name="Customer Support Team",
    model=OpenAIChat("gpt-4o"),
    members=[doc_researcher_agent, escalation_manager_agent, feedback_collector_agent],
    determine_input_for_members=False,
    respond_directly=True,
    markdown=True,
    debug_mode=True,
    show_members_responses=True,
    instructions=[
        "You are the lead customer support agent responsible for classifying and routing customer inquiries.",
        "Carefully analyze each user message and determine if it is: a question that needs documentation research, a bug report that requires escalation, or product feedback.",
        "For general questions about the product, route to the doc_researcher_agent who will search documentation for answers.",
        "If the doc_researcher_agent cannot find an answer to a question, escalate it to the escalation_manager_agent.",
        "For bug reports or technical issues, immediately route to the escalation_manager_agent.",
        "For feature requests or product feedback, route to the feedback_collector_agent.",
        "Always provide a clear explanation of why you're routing the inquiry to a specific agent.",
        "After receiving a response from the appropriate agent, relay that information back to the user in a professional and helpful manner.",
        "Ensure a seamless experience for the user by maintaining context throughout the conversation.",
    ],
)

# Add in the query and the agent redirects it to the appropriate agent
customer_support_team.print_response(
    "Hi Team, I want to build an educational platform where the models are have access to tons of study materials, How can Agno platform help me build this?",
    stream=True,
)
# customer_support_team.print_response(
#     "Support json schemas in Gemini client in addition to pydantic base model",
#     stream=True,
# )
# customer_support_team.print_response(
#     "Can you please update me on the above feature",
#     stream=True,
# )
# customer_support_team.print_response(
#     "[Bug] Async tools in team of agents not awaited properly, causing runtime errors ",
#     stream=True,
# )
