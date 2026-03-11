from typing import List, Optional


class GoogleAuthRequired(Exception):
    """Raised when a Google toolkit needs OAuth credentials that don't exist yet.

    The Slack router catches this and sends a "Connect Google" button to the user.
    """

    # Tells function.py to re-raise instead of swallowing
    propagate = True

    def __init__(self, team_id: str, user_id: str, scopes: Optional[List[str]] = None):
        self.team_id = team_id
        self.user_id = user_id
        self.scopes = scopes
        super().__init__(f"Google auth required for team={team_id} user={user_id}")
