from datetime import datetime

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.calcom import CalComTools

"""
Example showing how to use the Cal.com Tools with Agno.

Requirements:
- Cal.com API key (get from cal.com/settings/developer/api-keys)
- Event Type ID from Cal.com
- pip install requests pytz

Usage:
- Set the following environment variables:
    export CALCOM_API_KEY="your_api_key"
    export CALCOM_EVENT_TYPE_ID="your_event_type_id"

- Or provide them when creating the CalComTools instance
"""

INSTRUCTONS = f"""You're scheduing assistant. Today is {datetime.now()}.
You can help users by:
    - Finding available time slots
    - Creating new bookings
    - Managing existing bookings (view, reschedule, cancel)
    - Getting booking details
    - IMPORTANT: In case of rescheduling or cancelling booking, call the get_upcoming_bookings function to get the booking uid. check available slots before making a booking for given time
    Always confirm important details before making bookings or changes.
"""


agent = Agent(
    name="Calendar Assistant",
    instructions=[INSTRUCTONS],
    model=OpenAIChat(id="gpt-4"),
    tools=[CalComTools(user_timezone="America/New_York")],
    show_tool_calls=True,
    markdown=True,
)

# Example usage
agent.print_response("What are my bookings for tomorrow?")
