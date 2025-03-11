# 1. CEO Agent (Leader) – Sets vision, prioritizes tasks, and makes strategic decisions.
# 2. Product Manager Agent – Defines product roadmap, gathers user feedback, and refines features.
# 3. Marketing Manager Agent – Develops branding, runs campaigns, and tracks audience engagement.
# 4. Designer Agent – Creates UI/UX mockups, branding assets, and product visuals.
# 5. Financial Analyst Agent – Handles revenue projections, pricing strategies, and investor reports.
# 6.  Market Research Agent – Analyzes industry trends, competitors, and customer demands.
# 7. Legal Compliance Agent – Ensures contracts, policies, and regulations are met.
# 8. Sales & Partnerships Agent – Identifies leads, negotiates deals, and tracks conversions.
# 9.  Customer Support Agent – Engages with users, handles tickets, and improves customer satisfaction.


from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.team.team import Team
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.yfinance import YFinanceTools
from agno.tools.exa import ExaTools
from agno.knowledge.pdf import PDFKnowledgeBase , PDFReader
from agno.vectordb.pgvector.pgvector import PgVector
from agno.tools.slack import SlackTools

knowledge_base = PDFKnowledgeBase(
    path="data/compliance_report.pdf",
    vector_db=PgVector(
        table_name="autonomous_startup_team",
        db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
    ),
    reader=PDFReader(chunk=True),
)

knowledge_base.load(recreate=False)

support_channel = "test"


legal_compliance_agent = Agent(
    name="Legal Compliance Agent",
    role="Legal Compliance",
    model=OpenAIChat("gpt-4o"),
    tools=[ExaTools()],
    knowledge=knowledge_base,
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
    add_datetime_to_instructions=True,
    markdown=True,
)

product_manager_agent = Agent(
    name="Product Manager Agent",
    role="Product Manager",
    model=OpenAIChat("gpt-4o"),
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
    add_datetime_to_instructions=True,
    markdown=True,
    tools=[],
)

market_research_agent = Agent(
    name="Market Research Agent",
    role="Market Research",
    model=OpenAIChat("gpt-4o"),
    tools=[DuckDuckGoTools(), ExaTools()],
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
    add_datetime_to_instructions=True,
    markdown=True,
)

# sales_agent = Agent(
#     name="Sales Agent",
#     role="Sales",
#     model=OpenAIChat("gpt-4o"),
#     tools=[DuckDuckGoTools(), ExaTools()],
#     instructions=[
#         "You are the Sales Agent of a startup, responsible for revenue generation and client relationships.",
#         "Key Responsibilities:",
#         "1. Develop and execute sales strategies",
#         "2. Identify and qualify potential leads",
#         "3. Build and maintain relationships with key clients",
#         "4. Create compelling sales presentations and proposals",
#         "5. Negotiate contracts and close deals",
#         "6. Track sales metrics and pipeline",
#         "7. Collaborate with marketing on lead generation",
#         "8. Provide market feedback to product team",
#         "9. Maintain accurate sales forecasts",
#     ],
#     add_datetime_to_instructions=True,
#     markdown=True,
# )


financial_analyst_agent = Agent(
    name="Financial Analyst Agent",
    role="Financial Analyst",
    model=OpenAIChat("gpt-4o"),
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
    add_datetime_to_instructions=True,
    markdown=True,
)

customer_support_agent = Agent(
    name="Customer Support Agent",
    role="Customer Support",
    model=OpenAIChat("gpt-4o"),
    tools=[SlackTools()],
    instructions=[
        "You are the Customer Support Agent of a startup, responsible for handling customer inquiries and maintaining customer satisfaction.",
        "Key Responsibilities:",
        "1. Answer Questions:",
        "   - Respond to general startup and product inquiries",
        "   - Provide clear and accurate information about our services",
        "   - Maintain a knowledge base of common questions and answers",
        "",
        "2. Issue Management:",
        "   - For bug reports: Forward to support channel with prefix 'BUG:'",
        "   - For feature requests: Forward to support channel with prefix 'FEATURE:'",
        "   - For new deals/sales opportunities: Forward to support channel with prefix 'DEAL:'",
        "",
        "3. Slack Communication Protocol:",
        f"   - Channel: {support_channel}",
        "   - Format messages as:",
        "     ```",
        "     Type: [BUG/FEATURE/DEAL]",
        "     Priority: [High/Medium/Low]",
        "     Description: [Detailed description]",
        "     Customer: [Customer information]",
        "     Action Required: [Next steps or required actions]",
        "     ```",
        "",
        "4. Response Guidelines:",
        "   - Acknowledge all inquiries within first response",
        "   - Use professional and friendly tone",
        "   - Provide clear next steps or expectations",
        "   - Follow up on escalated issues",
        "",
        "5. Priority Levels:",
        "   - High: System-critical issues, potential revenue impact",
        "   - Medium: Functional issues, feature requests from key clients",
        "   - Low: Minor issues, general feedback",
        "",
        "Always maintain a professional and helpful demeanor while ensuring proper routing of issues to the right channels.",
    ],
    add_datetime_to_instructions=True,
    markdown=True,
)


autonomous_startup_team = Team(
    name="CEO Agent",
    mode="coordinator",
    model=OpenAIChat("gpt-4o"),
    instructions=[
        "You are the CEO of a startup, responsible for overall leadership and success.",
        "Key Responsibilities:",
        "1. Set and communicate company vision and strategy",
        "2. Coordinate and prioritize team activities",
        "3. Make high-level strategic decisions",
        "4. Evaluate opportunities and risks",
        "5. Manage resource allocation",
        "6. Drive growth and innovation",
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
    add_datetime_to_instructions=True,
    markdown=True,
    members=[product_manager_agent, market_research_agent, financial_analyst_agent, legal_compliance_agent, customer_support_agent],
)

# autonomous_startup_team.print_response(
#     message="I want to start a startup that sells AI agents to businesses. What is the best way to do this?",
#     stream=True,
#     stream_intermediate_steps=True,
# )

# autonomous_startup_team.print_response(
#     message="I want to start a startup that sells AI agents to businesses. What is the best way to do this?, Make sure we are compliant with all legal requirements",
#     stream=True,
#     stream_intermediate_steps=True,
# )

autonomous_startup_team.print_response(
    message="I?",
    stream=True,
    stream_intermediate_steps=True,
    show_tool_calls=True,
)


