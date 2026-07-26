import json
from os import getenv
from typing import Any, Dict, List, Optional

import httpx

from agno.tools import Toolkit
from agno.utils.log import log_debug, logger


class LiveTennisTools(Toolkit):
    """
    LiveTennisTools is a toolkit for live and historical tennis data from the
    Live Tennis API (https://livetennisapi.com): live scores, match details,
    player search and upcoming fixtures across the ATP and WTA tours.

    Get a free API key (1,000 requests/day) at https://livetennisapi.com/subscribe/free.

    Args:
        api_key (Optional[str]): Live Tennis API key. Falls back to the
            LIVETENNISAPI_KEY environment variable.
        base_url (str): Base URL of the Live Tennis API. Default is the public v1 API.
        enable_get_live_matches (bool): Register the get_live_matches tool. Default is True.
        enable_get_match (bool): Register the get_match tool. Default is True.
        enable_get_match_score (bool): Register the get_match_score tool. Default is True.
        enable_search_players (bool): Register the search_players tool. Default is True.
        enable_get_player (bool): Register the get_player tool. Default is True.
        enable_get_upcoming_fixtures (bool): Register the get_upcoming_fixtures tool. Default is True.
        all (bool): Register all tools regardless of the individual enable_* flags. Default is False.
        timeout (int): Per-request HTTP timeout in seconds. Default is 30.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = "https://api.livetennisapi.com/api/public/v1",
        enable_get_live_matches: bool = True,
        enable_get_match: bool = True,
        enable_get_match_score: bool = True,
        enable_search_players: bool = True,
        enable_get_player: bool = True,
        enable_get_upcoming_fixtures: bool = True,
        all: bool = False,
        timeout: int = 30,
        **kwargs,
    ):
        resolved_api_key = api_key or getenv("LIVETENNISAPI_KEY")
        if not resolved_api_key:
            raise ValueError(
                "Live Tennis API key is required. Provide it as an argument or set the "
                "LIVETENNISAPI_KEY environment variable. "
                "Get a free key at https://livetennisapi.com/subscribe/free"
            )
        self.api_key: str = resolved_api_key

        self.base_url = base_url.rstrip("/")

        tools: List[Any] = []
        if all or enable_get_live_matches:
            tools.append(self.get_live_matches)
        if all or enable_get_match:
            tools.append(self.get_match)
        if all or enable_get_match_score:
            tools.append(self.get_match_score)
        if all or enable_search_players:
            tools.append(self.search_players)
        if all or enable_get_player:
            tools.append(self.get_player)
        if all or enable_get_upcoming_fixtures:
            tools.append(self.get_upcoming_fixtures)

        super().__init__(name="livetennis_tools", tools=tools, timeout=timeout, **kwargs)

    def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        """Make an authenticated GET request to the Live Tennis API.

        Args:
            path (str): API path relative to the base URL, e.g. "/matches".
            params (Optional[Dict[str, Any]]): Query parameters for the request.

        Returns:
            Any: The decoded JSON response, or a dict with an "error" key on failure.
        """
        url = f"{self.base_url}{path}"
        try:
            response = httpx.get(
                url,
                params=params,
                headers={"x-api-key": self.api_key},
                timeout=self.timeout,
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                logger.error(f"Live Tennis API request unauthorized: {url}")
                return {
                    "error": "Unauthorized: invalid or missing API key. "
                    "Get a free key at https://livetennisapi.com/subscribe/free"
                }
            logger.error(f"Live Tennis API request failed with status {e.response.status_code}: {url}")
            return {"error": f"HTTP {e.response.status_code}: {e.response.text}"}
        except httpx.HTTPError as e:
            logger.error(f"Error making request to {url}: {e}")
            return {"error": str(e)}

    def get_live_matches(self, tour: Optional[str] = None, limit: int = 20) -> str:
        """Get tennis matches that are currently in progress, with live scores.

        Args:
            tour (Optional[str]): Filter by tour, e.g. "atp" or "wta". Default is all tours.
            limit (int): Maximum number of matches to return. Default is 20.

        Returns:
            str: JSON string with the list of live matches (players, tournament, current score).
        """
        log_debug(f"Getting live tennis matches (tour={tour}, limit={limit})")
        params: Dict[str, Any] = {"status": "live", "limit": max(1, limit)}
        if tour is not None and tour.strip():
            params["tour"] = tour.strip().lower()
        return json.dumps(self._get("/matches", params), indent=2)

    def get_match(self, match_id: str) -> str:
        """Get full details for a specific tennis match by its match ID.

        Args:
            match_id (str): The ID of the match, as returned by get_live_matches or
                get_upcoming_fixtures.

        Returns:
            str: JSON string with the match details (players, tournament, round, status, start time).
        """
        if not match_id or not match_id.strip():
            return json.dumps({"error": "match_id cannot be empty"})
        log_debug(f"Getting tennis match: {match_id}")
        return json.dumps(self._get(f"/matches/{match_id.strip()}"), indent=2)

    def get_match_score(self, match_id: str) -> str:
        """Get the current score for a specific tennis match by its match ID.

        Args:
            match_id (str): The ID of the match, as returned by get_live_matches or
                get_upcoming_fixtures.

        Returns:
            str: JSON string with the match score (sets, games, and current game points).
        """
        if not match_id or not match_id.strip():
            return json.dumps({"error": "match_id cannot be empty"})
        log_debug(f"Getting score for tennis match: {match_id}")
        return json.dumps(self._get(f"/matches/{match_id.strip()}/score"), indent=2)

    def search_players(self, query: str, limit: int = 10) -> str:
        """Search for tennis players by name.

        Args:
            query (str): Full or partial player name to search for, e.g. "Alcaraz".
            limit (int): Maximum number of players to return. Default is 10.

        Returns:
            str: JSON string with the matching players (name, player ID, tour, ranking).
        """
        if not query or not query.strip():
            return json.dumps({"error": "query cannot be empty"})
        log_debug(f"Searching tennis players: {query}")
        params = {"search": query.strip(), "limit": max(1, limit)}
        return json.dumps(self._get("/players", params), indent=2)

    def get_player(self, player_id: str) -> str:
        """Get profile details for a specific tennis player by their player ID.

        Args:
            player_id (str): The ID of the player, as returned by search_players.

        Returns:
            str: JSON string with the player profile (name, country, ranking, tour).
        """
        if not player_id or not player_id.strip():
            return json.dumps({"error": "player_id cannot be empty"})
        log_debug(f"Getting tennis player: {player_id}")
        return json.dumps(self._get(f"/players/{player_id.strip()}"), indent=2)

    def get_upcoming_fixtures(self, limit: int = 10) -> str:
        """Get upcoming scheduled tennis fixtures (matches that have not started yet).

        Args:
            limit (int): Maximum number of fixtures to return. Default is 10.

        Returns:
            str: JSON string with the upcoming fixtures (players, tournament, scheduled start time).
        """
        log_debug(f"Getting upcoming tennis fixtures (limit={limit})")
        params = {"limit": max(1, limit)}
        return json.dumps(self._get("/fixtures", params), indent=2)
