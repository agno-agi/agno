"""Example of a Team using the `coordinate` mode to play the role of a CEO of a Startup.

1. Run: `pip install agno exa_py slack_sdk pgvector psycopg` to install the dependencies
2. Add the following environment variables:
- `EXA_API_KEY`
- `SLACK_TOKEN`
"""

from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.pdf_reader import PDFReader
from agno.models.openai import OpenAIChat
from agno.team.team import Team
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.exa import ExaTools
from agno.tools.slack import SlackTools
from agno.tools.yfinance import YFinanceTools
from agno.vectordb.pgvector.pgvector import PgVector

knowledge = Knowledge(
    vector_db=PgVector(
        table_name="autonomous_startup_team",
        db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
    ),
)

knowledge.add_content(
    path="cookbook/teams/coordinate/data", reader=PDFReader(chunk=True)
)


support_channel = "testing"
sales_channel = "sales"


legal_compliance_agent = Agent(
    name="Legal Compliance Agent",
    role="Legal Compliance",
    model=OpenAIChat("gpt-4o"),
    tools=[ExaTools()],
    knowledge=knowledge,
    instructions=[
        "You are the Legal Compliance Agent of a startup, responsible for ensuring legal and regulatory compliance.",
        "Key Responsibilities:",
        "1. Review and validate all legal documents and contracts",
        "2. Monitor regulatory changes and update compliance policies",
        "3. Assess legal risks in business operations and product development",
        "4. Ensure data privacy and security compliance (GDPR, CCPA, etc.)",
        "5. Provide legal guidance on intellectual property protection",
        "6. Create and maintain compliance documentation",
        "7. Review marketing materials for legal compliance",
        "8. Advise on employment law and HR policies",
    ],
    add_datetime_to_context=True,
    markdown=True,
)

product_manager_agent = Agent(
    name="Product Manager Agent",
    role="Product Manager",
    model=OpenAIChat("gpt-4o"),
    knowledge=knowledge,
    instructions=[
        "You are the Product Manager of a startup, responsible for product strategy and execution.",
        "Key Responsibilities:",
        "1. Define and maintain the product roadmap",
        "2. Gather and analyze user feedback to identify needs",
        "3. Write detailed product requirements and specifications",
        "4. Prioritize features based on business impact and user value",
        "5. Collaborate with technical teams on implementation feasibility",
        "6. Monitor product metrics and KPIs",
        "7. Conduct competitive analysis",
        "8. Lead product launches and go-to-market strategies",
        "9. Balance user needs with business objectives",
    ],
    add_datetime_to_context=True,
    markdown=True,
    tools=[],
)

market_research_agent = Agent(
    name="Market Research Agent",
    role="Market Research",
    model=OpenAIChat("gpt-4o"),
    tools=[DuckDuckGoTools(), ExaTools()],
    knowledge=knowledge,
    instructions=[
        "You are the Market Research Agent of a startup, responsible for market intelligence and analysis.",
        "Key Responsibilities:",
        "1. Conduct comprehensive market analysis and size estimation",
        "2. Track and analyze competitor strategies and offerings",
        "3. Identify market trends and emerging opportunities",
        "4. Research customer segments and buyer personas",
        "5. Analyze pricing strategies in the market",
        "6. Monitor industry news and developments",
        "7. Create detailed market research reports",
        "8. Provide data-driven insights for decision making",
    ],
    add_datetime_to_context=True,
    markdown=True,
)

sales_agent = Agent(
    name="Sales Agent",
    role="Sales",
    model=OpenAIChat("gpt-4o"),
    tools=[SlackTools()],
    knowledge=knowledge,
    instructions=[
        "You are the Sales & Partnerships Agent of a startup, responsible for driving revenue growth and strategic partnerships.",
        "Key Responsibilities:",
        "1. Identify and qualify potential partnership and business opportunities",
        "2. Evaluate partnership proposals and negotiate terms",
        "3. Maintain relationships with existing partners and clients",
        "5. Collaborate with Legal Compliance Agent on contract reviews",
        "6. Work with Product Manager on feature requests from partners",
        f"7. Document and communicate all partnership details in #{sales_channel} channel",
        "",
        "Communication Guidelines:",
        "1. Always respond professionally and promptly to partnership inquiries",
        "2. Include all relevant details when sharing partnership opportunities",
        "3. Highlight potential risks and benefits in partnership proposals",
        "4. Maintain clear documentation of all discussions and agreements",
        "5. Ensure proper handoff to relevant team members when needed",
    ],
    add_datetime_to_context=True,
    markdown=True,
)


financial_analyst_agent = Agent(
    name="Financial Analyst Agent",
    role="Financial Analyst",
    model=OpenAIChat("gpt-4o"),
    knowledge=knowledge,
    tools=[YFinanceTools()],
    instructions=[
        "You are the Financial Analyst of a startup, responsible for financial planning and analysis.",
        "Key Responsibilities:",
        "1. Develop financial models and projections",
        "2. Create and analyze revenue forecasts",
        "3. Evaluate pricing strategies and unit economics",
        "4. Prepare investor reports and presentations",
        "5. Monitor cash flow and burn rate",
        "6. Analyze market conditions and financial trends",
        "7. Assess potential investment opportunities",
        "8. Track key financial metrics and KPIs",
        "9. Provide financial insights for strategic decisions",
    ],
    add_datetime_to_context=True,
    markdown=True,
)

customer_support_agent = Agent(
    name="Customer Support Agent",
    role="Customer Support",
    model=OpenAIChat("gpt-4o"),
    knowledge=knowledge,
    tools=[SlackTools()],
    instructions=[
        "You are the Customer Support Agent of a startup, responsible for handling customer inquiries and maintaining customer satisfaction.",
        f"When a user reports an issue or issue or the question you cannot answer, always send it to the #{support_channel} Slack channel with all relevant details.",
        "Always maintain a professional and helpful demeanor while ensuring proper routing of issues to the right channels.",
    ],
    add_datetime_to_context=True,
    markdown=True,
)


autonomous_startup_team = Team(
    name="CEO Agent",
    model=OpenAIChat("gpt-4o"),
    instructions=[
        "You are the CEO of a startup, responsible for overall leadership and success.",
        " Always delegate task to product manager agent so it can search the knowledge base.",
        "Instruct all agents to use the knowledge base to answer questions.",
        "Key Responsibilities:",
        "1. Set and communicate company vision and strategy",
        "2. Coordinate and prioritize team activities",
        "3. Make high-level strategic decisions",
        "4. Evaluate opportunities and risks",
        "5. Manage resource allocation",
        "6. Drive growth and innovation",
        "7. When a customer asks for help or reports an issue, immediately delegate to the Customer Support Agent",
        "8. When any partnership, sales, or business development inquiries come in, immediately delegate to the Sales Agent",
        "",
        "Team Coordination Guidelines:",
        "1. Product Development:",
        "   - Consult Product Manager for feature prioritization",
        "   - Use Market Research for validation",
        "   - Verify Legal Compliance for new features",
        "2. Market Entry:",
        "   - Combine Market Research and Sales insights",
        "   - Validate financial viability with Financial Analyst",
        "3. Strategic Planning:",
        "   - Gather input from all team members",
        "   - Prioritize based on market opportunity and resources",
        "4. Risk Management:",
        "   - Consult Legal Compliance for regulatory risks",
        "   - Review Financial Analyst's risk assessments",
        "5. Customer Support:",
        "   - Ensure all customer inquiries are handled promptly and professionally",
        "   - Maintain a positive and helpful attitude",
        "   - Escalate critical issues to the appropriate team",
        "",
        "Always maintain a balanced view of short-term execution and long-term strategy.",
    ],
    members=[
        product_manager_agent,
        market_research_agent,
        financial_analyst_agent,
        legal_compliance_agent,
        customer_support_agent,
        sales_agent,
    ],
    add_datetime_to_context=True,
    markdown=True,
    debug_mode=True,
    show_members_responses=True,
)

autonomous_startup_team.print_response(
    input="I want to start a startup that sells AI agents to businesses. What is the best way to do this?",
    stream=True,
)


autonomous_startup_team.print_response(
    input="Give me good marketing campaign for buzzai?",
    stream=True,
)

autonomous_startup_team.print_response(
    input="What is my company and what are the monetization strategies?",
    stream=True,
)

# autonomous_startup_team.print_response(
#     input="Read the partnership details and give me details about the partnership with InnovateAI",
#     stream=True,
# )
