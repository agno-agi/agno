"""Show how to use a tool execution hook, to run logic before and after a tool is called."""

import json
from typing import Any, Callable, Dict

from agno.agent import Agent
from agno.tools.toolkit import Toolkit


class CustomerDBTools(Toolkit):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.register(self.retrieve_customer_profile)

    def retrieve_customer_profile(self, customer: str):
        """
        Retrieves a customer profile from the database.

        Args:
            customer: The ID of the customer to retrieve.

        Returns:
            A string containing the customer profile.
        """
        return customer


def grab_customer_profile_hook(
    agent: Agent, function_name: str, function_call: Callable, arguments: Dict[str, Any]
):
    cust_id = arguments.get("customer")
    if cust_id not in agent.session_state["customer_profiles"]:
        raise ValueError(f"Customer profile for {cust_id} not found")
    customer_profile = agent.session_state["customer_profiles"][cust_id]

    # Replace the customer_id with the customer_profile
    arguments["customer"] = json.dumps(customer_profile)
    # Call the function with the updated arguments
    result = function_call(**arguments)

    return result


agent = Agent(
    tools=[CustomerDBTools()],
    tool_hooks=[grab_customer_profile_hook],
    session_state={
        "customer_profiles": {
            "456": {"name": "John Doe", "email": "john.doe@example.com"}
        }
    },
)

# This should work
agent.print_response("I am customer 456, please retrieve my profile.")

# This should fail
agent.print_response("I am customer 123, please retrieve my profile.")
