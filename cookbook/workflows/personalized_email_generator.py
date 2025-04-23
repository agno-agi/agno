"""
🎯 B2B Email Outreach - Your Personal Sales Writing Assistant!

This workflow helps sales professionals craft highly personalized cold emails by:
1. Researching target companies through their websites
2. Analyzing their business model, tech stack, and unique attributes
3. Generating personalized email drafts
4. Sending test emails to yourself for review before actual outreach

Why is this helpful?
--------------------------------------------------------------------------------
• You always have an extra review step—emails are sent to you first.
  This ensures you can fine-tune messaging before reaching your actual prospect.
• Ideal for iterating on tone, style, and personalization en masse.

Who should use this?
--------------------------------------------------------------------------------
• SDRs, Account Executives, Business Development Managers
• Founders, Marketing Professionals, B2B Sales Representatives
• Anyone building relationships or conducting outreach at scale

Example use cases:
--------------------------------------------------------------------------------
• SaaS sales outreach
• Consulting service proposals
• Partnership opportunities
• Investor relations
• Recruitment outreach
• Event invitations

Quick Start:
--------------------------------------------------------------------------------
1. Install dependencies:
   pip install openai agno

2. Set environment variables:
   - OPENAI_API_KEY

3. Update sender_details_dict with YOUR info.

4. Add target companies to "leads" dictionary.

5. Run:
   python personalized_email_generator.py

The script will send draft emails to your email first if DEMO_MODE=False.
If DEMO_MODE=True, it prints the email to the console for review.

Then you can confidently send the refined emails to your prospects!
"""

import json
from datetime import datetime
from textwrap import dedent
from typing import Dict, Iterator, List, Optional

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.storage.sqlite import SqliteStorage
from agno.tools.exa import ExaTools
from agno.utils.log import logger
from agno.utils.pprint import pprint_run_response
from agno.workflow import RunResponse, Workflow
from pydantic import BaseModel, Field

# Demo mode
# - set to True to print email to console
# - set to False to send to yourself
DEMO_MODE = True
today = datetime.now().strftime("%Y-%m-%d")

# Example leads - Replace with your actual targets
leads: Dict[str, Dict[str, str]] = {
    "Notion": {
        "name": "Notion",
        "website": "https://www.notion.so",
        "contact_name": "Ivan Zhao",
        "position": "CEO",
    },
    # Add more companies as needed
}

# Updated sender details for an AI analytics company
sender_details_dict: Dict[str, str] = {
    "name": "Sarah Chen",
    "email": "your.email@company.com",  # Your email goes here
    "organization": "Data Consultants Inc",
    "service_offered": "We help build data products and offer data consulting services",
    "calendar_link": "https://calendly.com/data-consultants-inc",
    "linkedin": "https://linkedin.com/in/your-profile",
    "phone": "+1 (555) 123-4567",
    "website": "https://www.data-consultants.com",
}

email_template = """\
Hey [RECIPIENT_NAME]

[PERSONAL_NOTE]

[PROBLEM_THEY_HAVE]

[SOLUTION_YOU_OFFER]

[SOCIAL_PROOF]

Here's my cal link if you're open to a call: [CALENDAR_LINK] ☕️

[SIGNATURE]

P.S. You can also dm me on X\
"""


class CompanyInfo(BaseModel):
    """
    Stores in-depth data about a company gathered during the research phase.
    """

    # Basic Information
    company_name: str = Field(..., description="Company name")
    website_url: str = Field(..., description="Company website URL")

    # Business Details
    industry: Optional[str] = Field(None, description="Primary industry")
    core_business: Optional[str] = Field(None, description="Main business focus")
    business_model: Optional[str] = Field(None, description="B2B, B2C, etc.")

    # Marketing Information
    motto: Optional[str] = Field(None, description="Company tagline/slogan")
    value_proposition: Optional[str] = Field(None, description="Main value proposition")
    target_audience: Optional[List[str]] = Field(
        None, description="Target customer segments"
    )

    # Company Metrics
    company_size: Optional[str] = Field(None, description="Employee count range")
    founded_year: Optional[int] = Field(None, description="Year founded")
    locations: Optional[List[str]] = Field(None, description="Office locations")

    # Technical Details
    technologies: Optional[List[str]] = Field(None, description="Technology stack")
    integrations: Optional[List[str]] = Field(None, description="Software integrations")

    # Market Position
    competitors: Optional[List[str]] = Field(None, description="Main competitors")
    unique_selling_points: Optional[List[str]] = Field(
        None, description="Key differentiators"
    )
    market_position: Optional[str] = Field(None, description="Market positioning")

    # Social Proof
    customers: Optional[List[str]] = Field(None, description="Notable customers")
    case_studies: Optional[List[str]] = Field(None, description="Success stories")
    awards: Optional[List[str]] = Field(None, description="Awards and recognition")

    # Recent Activity
    recent_news: Optional[List[str]] = Field(None, description="Recent news/updates")
    blog_topics: Optional[List[str]] = Field(None, description="Recent blog topics")

    # Pain Points & Opportunities
    challenges: Optional[List[str]] = Field(None, description="Potential pain points")
    growth_areas: Optional[List[str]] = Field(None, description="Growth opportunities")

    # Contact Information
    email_address: Optional[str] = Field(None, description="Contact email")
    phone: Optional[str] = Field(None, description="Contact phone")
    social_media: Optional[Dict[str, str]] = Field(
        None, description="Social media links"
    )

    # Additional Fields
    pricing_model: Optional[str] = Field(None, description="Pricing strategy and tiers")
    user_base: Optional[str] = Field(None, description="Estimated user base size")
    key_features: Optional[List[str]] = Field(None, description="Main product features")
    integration_ecosystem: Optional[List[str]] = Field(
        None, description="Integration partners"
    )
    funding_status: Optional[str] = Field(
        None, description="Latest funding information"
    )
    growth_metrics: Optional[Dict[str, str]] = Field(
        None, description="Key growth indicators"
    )


class PersonalisedEmailGenerator(Workflow):
    """
    Personalized email generation system that:

    1. Scrapes the target company's website
    2. Gathers essential info (tech stack, position in market, new updates)
    3. Generates a personalized cold email used for B2B outreach

    This workflow is designed to help you craft outreach that resonates
    specifically with your prospect, addressing known challenges and
    highlighting tailored solutions.
    """

    description: str = dedent("""\
        AI-Powered B2B Outreach Workflow:
        --------------------------------------------------------
        1. Research & Analyze
        2. Generate Personalized Email
        3. Send Draft to Yourself
        --------------------------------------------------------
        This creates a frictionless review layer, letting you refine each
        email before sending it to real prospects.
        Perfect for data-driven, personalized B2B outreach at scale.
    """)

    scraper: Agent = Agent(
        model=OpenAIChat(id="gpt-4o"),
        tools=[ExaTools()],
        description=dedent("""\
            You are an expert SaaS business analyst specializing in:

            🔍 Product Intelligence
            - Feature analysis
            - User experience evaluation
            - Integration capabilities
            - Platform scalability
            - Enterprise readiness

            📊 Market Position Analysis
            - Competitive advantages
            - Market penetration
            - Growth trajectory
            - Enterprise adoption
            - International presence

            💡 Technical Architecture
            - Infrastructure setup
            - Security standards
            - API capabilities
            - Data management
            - Compliance status

            🎯 Business Intelligence
            - Revenue model analysis
            - Customer acquisition strategy
            - Enterprise pain points
            - Scaling challenges
            - Integration opportunities\
        """),
        instructions=dedent("""\
            1. Start with the company website and analyze:
            - Homepage messaging
            - Product/service pages
            - About us section
            - Blog content
            - Case studies
            - Team pages

            2. Look for specific details about:
            - Recent company news
            - Customer testimonials
            - Technology partnerships
            - Industry awards
            - Growth indicators

            3. Identify potential pain points:
            - Scaling challenges
            - Market pressures
            - Technical limitations
            - Operational inefficiencies

            4. Focus on actionable insights that could:
            - Drive business growth
            - Improve operations
            - Enhance customer experience
            - Increase market share

            Remember: Quality over quantity. Focus on insights that could lead to meaningful business conversations.\
        """),
        response_model=CompanyInfo,
    )

    email_creator: Agent = Agent(
        model=OpenAIChat(id="gpt-4o"),
        description=dedent("""\
            You are writing for a friendly, empathetic 20-year-old sales rep whose
            style is cool, concise, and respectful. Tone is casual yet professional.

            - Be polite but natural, using simple language.
            - Never sound robotic or use big cliché words like "delve", "synergy" or "revolutionary."
            - Clearly address problems the prospect might be facing and how we solve them.
            - Keep paragraphs short and friendly, with a natural voice.
            - End on a warm, upbeat note, showing willingness to help.\
        """),
        instructions=dedent("""\
            Please craft a highly personalized email that has:

            1. A simple, personal subject line referencing the problem or opportunity.
            2. At least one area for improvement or highlight from research.
            3. A quick explanation of how we can help them (no heavy jargon).
            4. References a known challenge from the research.
            5. Avoid words like "delve", "explore", "synergy", "amplify", "game changer", "revolutionary", "breakthrough".
            6. Use first-person language ("I") naturally.
            7. Maintain a 20-year-old’s friendly style—brief and to the point.
            8. Avoid placing the recipient's name in the subject line.

            Use the following structural template, but ensure the final tone
            feels personal and conversation-like, not automatically generated:
            ----------------------------------------------------------------------
            """)
        + "Email Template to work with:\n"
        + email_template,
        markdown=False,
        add_datetime_to_instructions=True,
    )

    def get_cached_company_data(self, company_name: str) -> Optional[CompanyInfo]:
        """Retrieve cached company research data"""
        logger.info(f"Checking cache for company data: {company_name}")
        cached_data = self.session_state.get("company_research", {}).get(company_name)
        if cached_data:
            return CompanyInfo.model_validate(cached_data)
        return None

    def cache_company_data(self, company_name: str, company_data: CompanyInfo):
        """Cache company research data"""
        logger.info(f"Caching company data for: {company_name}")
        self.session_state.setdefault("company_research", {})
        self.session_state["company_research"][company_name] = company_data.model_dump()
        self.write_to_storage()

    def get_cached_email(self, company_name: str) -> Optional[str]:
        """Retrieve cached email content"""
        logger.info(f"Checking cache for email: {company_name}")
        return self.session_state.get("generated_emails", {}).get(company_name)

    def cache_email(self, company_name: str, email_content: str):
        """Cache generated email content"""
        logger.info(f"Caching email for: {company_name}")
        self.session_state.setdefault("generated_emails", {})
        self.session_state["generated_emails"][company_name] = email_content
        self.write_to_storage()

    def run(
        self,
        use_research_cache: bool = True,
        use_email_cache: bool = True,
    ) -> Iterator[RunResponse]:
        """
        Orchestrates the entire personalized marketing workflow:

        1. Looks up or retrieves from cache the company's data.
        2. If uncached, uses the scraper agent to research the company website.
        3. Passes that data to the email_creator agent to generate a targeted email.
        4. Yields the generated email content for review or distribution.
        """
        logger.info("Starting personalized marketing workflow...")

        for company_name, company_info in leads.items():
            try:
                logger.info(f"Processing company: {company_name}")

                # Check email cache first
                if use_email_cache:
                    cached_email = self.get_cached_email(company_name)
                    if cached_email:
                        logger.info(f"Using cached email for {company_name}")
                        yield RunResponse(content=cached_email)
                        continue

                # 1. Research Phase with caching
                company_data = None
                if use_research_cache:
                    company_data = self.get_cached_company_data(company_name)
                    if company_data:
                        logger.info(f"Using cached company data for {company_name}")

                if not company_data:
                    logger.info("Starting company research...")
                    scraper_response = self.scraper.run(
                        json.dumps(company_info, indent=4)
                    )

                    if not scraper_response or not scraper_response.content:
                        logger.warning(
                            f"No data returned for {company_name}. Skipping."
                        )
                        continue

                    company_data = scraper_response.content
                    if not isinstance(company_data, CompanyInfo):
                        logger.error(
                            f"Invalid data format for {company_name}. Skipping."
                        )
                        continue

                    # Cache the research results
                    self.cache_company_data(company_name, company_data)

                # 2. Generate email
                logger.info("Generating personalized email...")
                email_context = json.dumps(
                    {
                        "contact_name": company_info.get(
                            "contact_name", "Decision Maker"
                        ),
                        "position": company_info.get("position", "Leader"),
                        "company_info": company_data.model_dump(),
                        "recipient_email": sender_details_dict["email"],
                        "sender_details": sender_details_dict,
                    },
                    indent=4,
                )
                yield from self.email_creator.run(
                    f"Generate a personalized email using this context:\n{email_context}",
                    stream=True,
                )

                # Cache the generated email content
                self.cache_email(company_name, self.email_creator.run_response.content)

                # Obtain final email content:
                email_content = self.email_creator.run_response.content

                # 3. If not in demo mode, you'd handle sending the email here.
                #    Implementation details omitted.
                if not DEMO_MODE:
                    logger.info(
                        "Production mode: Attempting to send email to yourself..."
                    )
                    # Implementation for sending the email goes here.

            except Exception as e:
                logger.error(f"Error processing {company_name}: {e}")
                raise


def main():
    """
    Main entry point for running the personalized email generator workflow.
    """
    try:
        # Create workflow with SQLite storage
        workflow = PersonalisedEmailGenerator(
            session_id="personalized-email-generator",
            storage=SqliteStorage(
                table_name="personalized_email_workflows",
                db_file="tmp/agno_workflows.db",
            ),
        )

        # Run workflow with caching
        responses = workflow.run(
            use_research_cache=True,
            use_email_cache=False,
        )

        # Process and pretty-print responses
        pprint_run_response(responses, markdown=True)

        logger.info("Workflow completed successfully!")
    except Exception as e:
        logger.error(f"Workflow failed: {e}")
        raise


if __name__ == "__main__":
    main()
