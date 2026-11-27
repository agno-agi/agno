"""What a Claude or Codex agent says when its subscription's usage limit is reached.

Each harness reports the limit in its own shape. The agents read that shape and call here for
one plain sentence that names the agent, the limit and when it resets.
"""

import re
from datetime import datetime, timezone
from typing import Any, Optional

from agno.utils.log import log_warning

# Words a failure carries when it may be a limit the agent did not recognise as one.
_LIMIT_LIKE = re.compile(r"limit|quota|\b429\b|too many requests|out of credits", re.IGNORECASE)


def resets_at_text(resets_at: Any) -> Optional[str]:
    """A Unix time in seconds as "2026-11-28 14:00 UTC"; None when the harness gave no usable time."""
    if isinstance(resets_at, bool) or not isinstance(resets_at, (int, float)) or resets_at <= 0:
        return None
    try:
        return datetime.fromtimestamp(resets_at, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    except (OverflowError, OSError, ValueError):
        return None


def limit_message(
    agent_id: str, subscription: str, window: Optional[str], resets_at: Any, said: Optional[str], harness: str
) -> str:
    """The message of a run that failed because the agent's subscription limit is reached.

    ``window`` names the limit when the harness says which one, such as "five-hour" or "weekly".
    ``said`` is the harness's own text, kept after the sentence so nothing it reported is lost.
    """
    limit = f"{subscription} subscription limit" + (f" (the {window} limit)" if window else "")
    when = resets_at_text(resets_at)
    message = f"{agent_id} has reached its {limit}" + (f"; it resets at {when}" if when else "")
    message += ". No API key was used."
    detail = str(said).strip() if said else ""
    return f"{message} {harness} said: {detail}" if detail else message


def note_possible_limit(agent_id: str, text: Any) -> None:
    """Log a failure of an agent on a subscription that reads like a limit and was not recognised as one.

    A real limit cannot be produced on demand, so the shapes this code reads come from the SDKs
    and their documentation. This line shows the real text when a harness reports one differently.
    """
    shown = str(text)
    if _LIMIT_LIKE.search(shown):
        log_warning(
            f"{agent_id} runs on a subscription and failed with what may be a usage limit that was not "
            f"recognised as one: {shown[:500]}"
        )
