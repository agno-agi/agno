import json
from typing import Any, Dict

from agno.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.models.openai import OpenAIChat
from agno.run import RunContext
from agno.tools.toolkit import Toolkit
from agno.utils.log import log_info, log_warning


class CustomerDBTools(Toolkit):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.register(self.process_customer_request)

    def process_customer_request(
        self,
        agent: Agent,
        customer_id: str,
        action: str = "retrieve",
        name: str = "John Doe",
    ):
        log_warning("Tool called, this shouldn't happen.")
        return "This should not be seen."


def customer_management_hook(run_context: RunContext, arguments: Dict[str, Any]):
    if run_context.session_state is None:
        run_context.session_state = {}

    action = arguments.get("action", "retrieve")
    cust_id = arguments.get("customer_id")
    name = arguments.get("name", None)

    if not cust_id:
        raise ValueError("customer_id is required.")

    if action == "create":
        run_context.session_state["customer_profiles"][cust_id] = {"name": name}
        log_info(f"Hook: UPDATED session_state for customer '{cust_id}'.")
        return f"Success! Customer {cust_id} has been created."

    if action == "retrieve":
        profile = run_context.session_state.get("customer_profiles", {}).get(cust_id)
        if profile:
            log_info(f"Hook: FOUND customer '{cust_id}' in session_state.")
            return f"Profile for {cust_id}: {json.dumps(profile)}"
        else:
            raise ValueError(f"Customer '{cust_id}' not found.")

    log_info(f"Session state: {run_context.session_state}")


def run_test():
    agent = Agent(
        model=OpenAIChat(id="gpt-4o"),
        tools=[CustomerDBTools()],
        tool_hooks=[customer_management_hook],
        session_state={"customer_profiles": {"123": {"name": "Jane Doe"}}},
        instructions="Your profiles: {customer_profiles}. Use `process_customer_request`. Use either create or retrieve as action for the tool.",
        resolve_in_context=True,
        db=InMemoryDb(),
    )

    prompt = "First, create customer 789 named 'Tom'. Then, retrieve Tom's profile. Step by step."
    log_info(f"📝 Prompting: '{prompt}'")
    agent.print_response(prompt, stream=False)

    log_info("\n--- TEST ANALYSIS ---")
    log_info(
        "Check logs for the second tool call. The system prompt will NOT contain customer '789'."
    )


if __name__ == "__main__":
    run_test()
