import asyncio
import json

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.calculator import CalculatorTools
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.toolkit import Toolkit
from agno.utils.log import logger


class CustomerDBTools(Toolkit):
    def __init__(self, *args, **kwargs):
        super().__init__(
            name="customer_db",
            tools=[self.retrieve_customer_profile, self.delete_customer_profile],
            *args,
            **kwargs,
        )

    async def retrieve_customer_profile(self, customer_id: str):
        """
        Retrieves a customer profile from the database.

        Args:
            customer_id: The ID of the customer to retrieve.

        Returns:
            A string containing the customer profile.
        """
        logger.info(f"Looking up customer profile for {customer_id}")
        return json.dumps(
            {
                "customer_id": customer_id,
                "name": "John Doe",
                "email": "john.doe@example.com",
            }
        )

    def delete_customer_profile(self, customer_id: str):
        """
        Deletes a customer profile from the database.

        Args:
            customer_id: The ID of the customer to delete.
        """
        logger.info(f"Deleting customer profile for {customer_id}")
        return f"Customer profile for {customer_id}"


agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[CustomerDBTools(include_tools=["retrieve_customer_profile"])],
    show_tool_calls=True,
)

asyncio.run(
    agent.aprint_response(
        "Retrieve the customer profile for customer ID 123 and delete it.",  # The agent shouldn't be able to delete the profile
        markdown=True,
    )
)
