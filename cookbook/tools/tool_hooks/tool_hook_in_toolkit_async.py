"""Show how to use a tool execution hook with async functions, to run logic before and after a tool is called."""

import asyncio
import json
from inspect import iscoroutinefunction
from typing import Any, Callable, Dict

from agno.agent import Agent
from agno.tools import Toolkit
from agno.utils.log import logger


class CustomerDBTools(Toolkit):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.register(self.retrieve_customer_profile)
        self.register(self.delete_customer_profile)

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


async def validation_hook(
    function_name: str, function_call: Callable, arguments: Dict[str, Any]
):
    if function_name == "delete_customer_profile":
        cust_id = arguments.get("customer_id")
        if cust_id == "123":
            raise ValueError("Cannot delete customer profile for ID 123")

    if function_name == "retrieve_customer_profile":
        cust_id = arguments.get("customer_id")
        if cust_id == "123":
            raise ValueError("Cannot retrieve customer profile for ID 123")

    if iscoroutinefunction(function_call):
        result = await function_call(**arguments)
    else:
        result = function_call(**arguments)

    logger.info(
        f"Validation hook: {function_name} with arguments {arguments} returned {result}"
    )

    return result


agent = Agent(tools=[CustomerDBTools()], tool_hooks=[validation_hook])

asyncio.run(agent.aprint_response("I am customer 456, please retrieve my profile."))
asyncio.run(agent.aprint_response("I am customer 456, please delete my profile."))
