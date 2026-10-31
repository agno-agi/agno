"""
Apify Tools: Job Search
=============================

Search job listings through an Apify Actor, with a capped run and trimmed results.

ApifyTools turns an Actor's input schema into tool parameters and returns the
run's whole dataset as JSON. This recipe adds a tool hook that caps how many
items a run may return before it starts, and keeps only the fields the agent
needs afterwards, so a broad search stays small in context and cheap to run.

Setup (ApifyTools reads the dict responses of apify-client 2.x):
    uv pip install agno "apify-client<3" requests openai
    export APIFY_API_TOKEN=your_apify_api_token
    export OPENAI_API_KEY=your_openai_api_key
"""

import json

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.apify import ApifyTools

# Swap these two lines to use another job Actor: its id, and the name and value
# of the input that caps how many items one run returns.
JOB_ACTOR = "johnvc/linkedin-jobs-api"
ITEM_CAP = ("maxJobs", 10)

# Output name -> the Actor's dataset field.
KEEP_FIELDS = {
    "title": "title",
    "company": "companyName",
    "location": "location",
    "posted": "postedDate",
    "link": "jobUrl",
}


def cap_and_trim(function_name: str, func: callable, args: dict):
    """Clamp the item cap before the run, then trim each dataset item."""
    if not function_name.startswith("apify_actor_"):
        return func(**args)

    # Agno runs the tool with this same args dict, so set the cap on it in place.
    cap_name, cap_value = ITEM_CAP
    params = args["kwargs"] if isinstance(args.get("kwargs"), dict) else args
    requested = params.get(cap_name) or cap_value
    params[cap_name] = min(int(requested), cap_value)

    result = func(**args)
    try:
        items = json.loads(result)
    except (TypeError, ValueError):
        return result

    trimmed = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if "error" in item:
            trimmed.append(item)  # keep tool errors visible to the model
        elif item.get("result_type", "job") == "job":
            trimmed.append({key: item.get(field) for key, field in KEEP_FIELDS.items()})
    return json.dumps(trimmed)


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
    tools=[ApifyTools(actors=[JOB_ACTOR])],
    tool_hooks=[cap_and_trim],
    instructions=[
        "Search for jobs with the Apify tool. Fill the keyword, location and posting window from the request.",
        "Answer with a table of title, company, location, posted date and link.",
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response(
        "Remote Python data engineering roles in Germany posted in the past week."
    )
