"""
Team media on delegated member runs
=====================================

Shows ``add_team_media_to_delegation`` on :class:`Team`: when the leader delegates,
prior team-level run inputs and team-visible message attachments can be merged into
``member_agent.run`` / ``arun`` kwargs (``images``, ``videos``, ``audio``, ``files``),
bounded by ``num_history_runs`` / ``num_history_messages``.

Requires a persisted session (``db``) so earlier team runs exist in ``TeamSession``.

First turn uploads an image; second turn asks the leader to delegate to the vision
member about that earlier image. With the flag on, the member receives the historical
image in kwargs, not only the current text turn.
"""

from uuid import uuid4

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.media import Image
from agno.models.openai import OpenAIResponses
from agno.team import Team

# ---------------------------------------------------------------------------
# Members
# ---------------------------------------------------------------------------
vision_member = Agent(
    name="Image Analyst",
    role="Answer questions about images using the images passed into your run.",
    model=OpenAIResponses(id="gpt-5.4"),
    instructions=[
        "Use the images supplied to your run when answering.",
        "If no image is supplied, say you cannot see one.",
    ],
)

# ---------------------------------------------------------------------------
# Team
# ---------------------------------------------------------------------------
team = Team(
    name="Vision delegation demo",
    model=OpenAIResponses(id="gpt-5.4"),
    members=[vision_member],
    instructions=[
        "You coordinate a single vision specialist.",
        "When the user asks about an image from an earlier turn, call delegate_task_to_member",
        "with the Image Analyst member id and a clear task (for example: describe the image).",
    ],
    db=SqliteDb(db_file="tmp/team_media_delegation.db"),
    add_history_to_context=True,
    add_team_media_to_delegation=True,
    num_history_runs=5,
)

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    session_id = f"session_{uuid4()}"
    sample_image_url = (
        "https://upload.wikimedia.org/wikipedia/commons/thumb/d/dd/"
        "Gfp-wisconsin-madison-the-nature-boardwalk.jpg/"
        "2560px-Gfp-wisconsin-madison-the-nature-boardwalk.jpg"
    )

    team.print_response(
        "Here is a landscape reference image for our session.",
        images=[Image(url=sample_image_url)],
        stream=True,
        session_id=session_id,
    )

    team.print_response(
        "Delegate to the Image Analyst: in one sentence, what setting does the image show?",
        stream=True,
        session_id=session_id,
    )
