from typing import Optional, Union

from agno.agent import Agent
from agno.models.google import Gemini
from pydantic import BaseModel, Field


class ContactInfo(BaseModel):
    """Contact information with structured properties"""

    contact_name: str = Field(description="Name of the contact person")
    contact_method: str = Field(
        description="Preferred communication method",
        enum=["email", "phone", "teams", "slack"],
    )
    contact_details: str = Field(description="Email address or phone number")


class EventSchema(BaseModel):
    event_id: str = Field(description="Unique event identifier")
    event_name: str = Field(description="Name of the event")

    event_date: str = Field(
        description="Event date in YYYY-MM-DD format",
        format="date",
    )

    start_time: str = Field(
        description="Event start time in HH:MM format",
        format="time",
    )

    duration: str = Field(
        description="Event duration in ISO 8601 format (e.g., PT2H30M)",
        format="duration",
    )

    status: str = Field(
        description="Current event status",
        enum=[
            "planning",
            "confirmed",
            "in_progress",
            "completed",
            "cancelled",
        ],
    )

    attendee_count: int = Field(
        description="Expected number of attendees",
        ge=1,
        le=10000,
    )

    budget_range: Union[float, str] = Field(
        description="Budget as number (USD) or 'TBD' if not determined"
    )

    optional_notes: Optional[str] = Field(
        description="Additional notes about the event (can be null)",
        default=None,
    )

    contact_info: ContactInfo = Field(
        description="Contact information with structured properties"
    )


structured_output_agent = Agent(
    name="Advanced Event Planner",
    model=Gemini(id="gemini-2.5-pro"),
    output_schema=EventSchema,
    instructions="""
    Create a detailed event plan that demonstrates all schema constraints:
    - Use proper date/time/duration formats
    - Set a realistic status from the enum options
    - Handle budget as either a number or 'TBD'
    - Include optional notes if relevant
    - Create contact info as a nested object
    """,
)

structured_output_agent.print_response(
    "Plan a corporate product launch event for 150 people next month"
)
