"""
Task Mode with Custom Tools

Demonstrates task mode where member agents use custom Python function tools.
Shows how agents with specialized tools can be orchestrated via tasks.

Run: .venvs/demo/bin/python cookbook/03_teams/02_modes/tasks/09_custom_tools.py
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.team.mode import TeamMode
from agno.team.team import Team
from agno.tools import tool

# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@tool
def calculate_compound_interest(
    principal: float, annual_rate: float, years: int, compounds_per_year: int = 12
) -> str:
    """Calculate compound interest on an investment.

    Args:
        principal: Initial investment amount in dollars.
        annual_rate: Annual interest rate as a percentage (e.g., 5.0 for 5%).
        years: Number of years to compound.
        compounds_per_year: How many times interest compounds per year. Defaults to 12 (monthly).
    """
    rate = annual_rate / 100
    amount = principal * (1 + rate / compounds_per_year) ** (compounds_per_year * years)
    interest = amount - principal
    return (
        f"Investment: ${principal:,.2f}\n"
        f"Rate: {annual_rate}% compounded {compounds_per_year}x/year\n"
        f"Duration: {years} years\n"
        f"Final value: ${amount:,.2f}\n"
        f"Total interest earned: ${interest:,.2f}"
    )


@tool
def calculate_monthly_payment(principal: float, annual_rate: float, years: int) -> str:
    """Calculate monthly loan payment using amortization formula.

    Args:
        principal: Loan amount in dollars.
        annual_rate: Annual interest rate as a percentage (e.g., 5.0 for 5%).
        years: Loan term in years.
    """
    monthly_rate = (annual_rate / 100) / 12
    num_payments = years * 12
    if monthly_rate == 0:
        payment = principal / num_payments
    else:
        payment = (
            principal
            * (monthly_rate * (1 + monthly_rate) ** num_payments)
            / ((1 + monthly_rate) ** num_payments - 1)
        )
    total_paid = payment * num_payments
    total_interest = total_paid - principal
    return (
        f"Loan: ${principal:,.2f} at {annual_rate}% for {years} years\n"
        f"Monthly payment: ${payment:,.2f}\n"
        f"Total paid: ${total_paid:,.2f}\n"
        f"Total interest: ${total_interest:,.2f}"
    )


@tool
def assess_risk_score(
    debt_to_income_ratio: float, credit_score: int, years_employed: int
) -> str:
    """Assess financial risk based on key metrics.

    Args:
        debt_to_income_ratio: Monthly debt payments divided by monthly income (e.g., 0.3 for 30%).
        credit_score: Credit score (300-850).
        years_employed: Years at current employer.
    """
    score = 0
    if credit_score >= 750:
        score += 40
    elif credit_score >= 700:
        score += 30
    elif credit_score >= 650:
        score += 20
    else:
        score += 10

    if debt_to_income_ratio <= 0.28:
        score += 30
    elif debt_to_income_ratio <= 0.36:
        score += 20
    else:
        score += 10

    if years_employed >= 5:
        score += 30
    elif years_employed >= 2:
        score += 20
    else:
        score += 10

    if score >= 80:
        risk = "LOW"
    elif score >= 60:
        risk = "MODERATE"
    else:
        risk = "HIGH"

    return (
        f"Risk Assessment:\n"
        f"  Credit score: {credit_score} -> {'Excellent' if credit_score >= 750 else 'Good' if credit_score >= 700 else 'Fair' if credit_score >= 650 else 'Poor'}\n"
        f"  Debt-to-income: {debt_to_income_ratio:.0%} -> {'Good' if debt_to_income_ratio <= 0.28 else 'Acceptable' if debt_to_income_ratio <= 0.36 else 'High'}\n"
        f"  Employment: {years_employed} years -> {'Stable' if years_employed >= 5 else 'Moderate' if years_employed >= 2 else 'New'}\n"
        f"  Overall risk: {risk} (score: {score}/100)"
    )


# ---------------------------------------------------------------------------
# Create Members
# ---------------------------------------------------------------------------

calculator = Agent(
    name="Financial Calculator",
    role="Performs financial calculations including interest, loans, and projections",
    model=OpenAIResponses(id="gpt-5-mini"),
    tools=[calculate_compound_interest, calculate_monthly_payment],
    instructions=[
        "You are a financial calculator.",
        "Use the provided tools to perform precise calculations.",
        "Always show the full calculation results.",
    ],
)

risk_assessor = Agent(
    name="Risk Assessor",
    role="Evaluates financial risk based on client metrics",
    model=OpenAIResponses(id="gpt-5-mini"),
    tools=[assess_risk_score],
    instructions=[
        "You are a financial risk assessor.",
        "Use the risk assessment tool to evaluate client financial health.",
        "Provide clear interpretation of the results.",
    ],
)

advisor = Agent(
    name="Financial Advisor",
    role="Provides financial advice and recommendations",
    model=OpenAIResponses(id="gpt-5-mini"),
    instructions=[
        "You are a financial advisor.",
        "Based on calculations and risk assessments, provide actionable advice.",
        "Be specific with recommendations and explain your reasoning.",
    ],
)

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------

finance_team = Team(
    name="Financial Advisory Team",
    mode=TeamMode.tasks,
    model=OpenAIResponses(id="gpt-5.2"),
    members=[calculator, risk_assessor, advisor],
    instructions=[
        "You are a financial advisory team leader.",
        "For financial advice requests:",
        "1. Use the Financial Calculator for any number crunching",
        "2. Use the Risk Assessor to evaluate the client's risk profile",
        "3. These two tasks are independent -- run them in parallel",
        "4. Then have the Financial Advisor synthesize findings into recommendations",
        "Always use the proper tools for calculations -- do not estimate.",
    ],
    show_members_responses=True,
    markdown=True,
    max_iterations=10,
)

# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    finance_team.print_response(
        "I'm considering buying a house for $450,000 with a 20% down payment. "
        "I can get a 30-year mortgage at 6.5%. My credit score is 720, "
        "debt-to-income ratio is 0.25, and I've been at my job for 4 years. "
        "I also want to know what $50,000 invested at 8% for 20 years would grow to. "
        "Give me a complete financial picture and your recommendation."
    )
