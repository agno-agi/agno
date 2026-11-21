from typing import Any, Dict, List, Optional
from urllib.parse import quote

import httpx

from agno.tools import Toolkit
from agno.utils.log import log_debug


class BattleTrainingTools(Toolkit):
    """Tools for reading the battle.training arena: ladders, bots, cups and agent standings.

    battle.training is a tactical combat arena where AI coding agents write
    JavaScript controllers that draft a squad of vehicles and fight around the
    clock on public ladders. Matches are deterministic and every replay is
    re-simulated and verified in the browser, so the ladder doubles as a
    running comparison of which coding agents and models write the strongest
    bots.

    Every endpoint used here is public and read-only: no account or API key is
    required. Responses are trimmed to the fields an agent needs to reason
    about standings, so a full 378-bot ladder does not flood the context.

    Args:
        base_url: battle.training API base URL.
        timeout: Per-request timeout in seconds.
        enable_get_arena_status: Register the arena status tool.
        enable_get_ladder: Register the public ladder tool.
        enable_get_bot: Register the bot profile tool.
        enable_get_agent_standings: Register the agent standings tool.
        enable_get_ladders: Register the ladder/cup listing tool.
        enable_get_ladder_standings: Register the ladder/cup standings tool.
        all: Register all tools regardless of individual flags.
    """

    def __init__(
        self,
        base_url: str = "https://api.battle.training",
        timeout: float = 30.0,
        enable_get_arena_status: bool = True,
        enable_get_ladder: bool = True,
        enable_get_bot: bool = True,
        enable_get_agent_standings: bool = True,
        enable_get_ladders: bool = True,
        enable_get_ladder_standings: bool = True,
        all: bool = False,
        **kwargs,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = httpx.Timeout(timeout)
        self.headers = {
            "Accept": "application/json",
            # The arena edge rejects requests without a normal User-Agent.
            "User-Agent": "agno-battle-training-tools",
        }

        tools: List[Any] = []
        async_tools: List[tuple] = []
        if all or enable_get_arena_status:
            tools.append(self.get_arena_status)
            async_tools.append((self.aget_arena_status, "get_arena_status"))
        if all or enable_get_ladder:
            tools.append(self.get_ladder)
            async_tools.append((self.aget_ladder, "get_ladder"))
        if all or enable_get_bot:
            tools.append(self.get_bot)
            async_tools.append((self.aget_bot, "get_bot"))
        if all or enable_get_agent_standings:
            tools.append(self.get_agent_standings)
            async_tools.append((self.aget_agent_standings, "get_agent_standings"))
        if all or enable_get_ladders:
            tools.append(self.get_ladders)
            async_tools.append((self.aget_ladders, "get_ladders"))
        if all or enable_get_ladder_standings:
            tools.append(self.get_ladder_standings)
            async_tools.append((self.aget_ladder_standings, "get_ladder_standings"))

        name = kwargs.pop("name", "battle_training_tools")
        super().__init__(name=name, tools=tools, async_tools=async_tools, **kwargs)

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _error(response: httpx.Response) -> Dict[str, Any]:
        try:
            detail = response.json().get("error", response.text)
        except (ValueError, AttributeError):
            detail = response.text
        return {
            "error": "battle.training API request failed",
            "status_code": response.status_code,
            "detail": detail,
        }

    def _request(self, path: str) -> Dict[str, Any]:
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.get(f"{self.base_url}/{path}", headers=self.headers)
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as error:
            return self._error(error.response)
        except httpx.RequestError as error:
            return {"error": "battle.training API request failed", "detail": str(error)}

    async def _arequest(self, path: str) -> Dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(f"{self.base_url}/{path}", headers=self.headers)
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as error:
            return self._error(error.response)
        except httpx.RequestError as error:
            return {"error": "battle.training API request failed", "detail": str(error)}

    # ------------------------------------------------------------------
    # Response shaping
    # ------------------------------------------------------------------

    @staticmethod
    def _ladder_entry(entry: Dict[str, Any]) -> Dict[str, Any]:
        """Trim one ladder/standings entry to the fields worth reasoning about."""
        return {
            "rank": entry.get("rank"),
            "bot": entry.get("bot"),
            "version": entry.get("version"),
            "agent": entry.get("agent"),
            "model": entry.get("model"),
            "score": entry.get("score"),
            "rating": entry.get("rating"),
            "rating_deviation": entry.get("rd"),
            "games": entry.get("games"),
            "wins": entry.get("wins"),
            "losses": entry.get("losses"),
            "draws": entry.get("draws"),
            "active": entry.get("active"),
        }

    def _shape_arena_status(self, data: Dict[str, Any]) -> Dict[str, Any]:
        if "error" in data:
            return data
        arena = data.get("arena", {})
        ladder = data.get("ladder", {})
        return {
            "generated_at": data.get("generated_at"),
            "bots": arena.get("bots"),
            "players": arena.get("players"),
            "bots_playing_now": arena.get("bots_playing_now"),
            "sets_last_hour": arena.get("sets_last_hour"),
            "ladder": ladder.get("name"),
            "ranked_bots": ladder.get("ranked"),
            "top": ladder.get("top", [])[:10],
        }

    def _shape_ladder(self, data: Dict[str, Any], top_n: int) -> Dict[str, Any]:
        if "error" in data:
            return data
        entries = data.get("entries", [])
        return {
            "ladder": "public",
            "theater": "armor",
            "total_ranked": len(entries),
            "updated_at": data.get("updated_at"),
            "entries": [self._ladder_entry(entry) for entry in entries[:top_n]],
        }

    def _shape_bot(self, data: Dict[str, Any]) -> Dict[str, Any]:
        if "error" in data:
            return data
        active_version: Optional[Dict[str, Any]] = None
        for version in data.get("versions", []):
            if version.get("active"):
                active_version = {
                    "label": version.get("label"),
                    "score": version.get("score"),
                    "rating": version.get("rating"),
                    "games": version.get("games"),
                    "wins": version.get("wins"),
                    "losses": version.get("losses"),
                    "draws": version.get("draws"),
                    "health": version.get("health"),
                }
                break
        cups = [
            {
                "ladder": cup.get("ladder"),
                "rank": cup.get("rank"),
                "of": cup.get("of"),
                "score": cup.get("score"),
                "rating": cup.get("rating"),
                "games": cup.get("games"),
                "wins": cup.get("wins"),
                "losses": cup.get("losses"),
                "draws": cup.get("draws"),
            }
            for cup in data.get("ladders", [])
        ]
        recent_matches = [
            {"id": match.get("id"), "ladder": match.get("ladder"), "status": match.get("status")}
            for match in data.get("matches", [])[:5]
        ]
        return {
            "name": data.get("name"),
            "handle": data.get("handle"),
            "agent": data.get("agent"),
            "model": data.get("model"),
            "house": data.get("house"),
            "theater": data.get("theater"),
            "theaters": data.get("theaters", {}),
            "cups": cups,
            "active_version": active_version,
            "recent_matches": recent_matches,
            "url": f"https://battle.training/bots/{data.get('name')}",
        }

    def _shape_agent_standings(self, data: Dict[str, Any], top_n: int) -> Dict[str, Any]:
        if "error" in data:
            return data
        agents = [
            {
                "agent": agent.get("id"),
                "score": agent.get("score"),
                "bots": agent.get("bots"),
                "players": agent.get("players"),
                "games": agent.get("games"),
                "wins": agent.get("wins"),
                "losses": agent.get("losses"),
                "draws": agent.get("draws"),
                "top_bot": agent.get("top_bot"),
                "models": agent.get("models", []),
            }
            for agent in data.get("agents", [])[:top_n]
        ]
        return {"note": data.get("note"), "agents": agents}

    def _shape_ladders(self, data: Dict[str, Any]) -> Dict[str, Any]:
        if "error" in data:
            return data
        ladders = [
            {
                "slug": ladder.get("slug"),
                "name": ladder.get("name"),
                "kind": ladder.get("kind"),
                "status": ladder.get("status"),
                "theater": ladder.get("theater"),
                "rules_version": ladder.get("rules_version"),
                "enrolled": ladder.get("enrolled"),
                "prize": ladder.get("prize"),
                "ends_at": ladder.get("ends_at"),
                "url": ladder.get("url"),
            }
            for ladder in data.get("ladders", [])
        ]
        return {"ladders": ladders}

    def _shape_ladder_standings(self, data: Dict[str, Any], slug: str, top_n: int) -> Dict[str, Any]:
        if "error" in data:
            return data
        standings = data.get("standings", [])
        return {
            "ladder": data.get("slug", slug),
            "name": data.get("name"),
            "kind": data.get("kind"),
            "status": data.get("status"),
            "prize": data.get("prize"),
            "enrolled": data.get("enrolled"),
            "total_ranked": len(standings),
            "standings": [self._ladder_entry(entry) for entry in standings[:top_n]],
        }

    @staticmethod
    def _validate_top_n(top_n: int) -> Optional[Dict[str, Any]]:
        if top_n < 1:
            return {"error": "top_n must be at least 1"}
        return None

    # ------------------------------------------------------------------
    # Tools (sync)
    # ------------------------------------------------------------------

    def get_arena_status(self) -> Dict[str, Any]:
        """Use this function to get the state of the battle.training arena in one read.

        Returns how many bots and players are in the arena, how many sets were
        played in the last hour, and the current top 10 of the public ladder.

        Returns:
            Dict[str, Any]: Arena counts and the ladder top 10, or an error dict.
        """
        log_debug("Getting battle.training arena status")
        return self._shape_arena_status(self._request("api/status"))

    def get_ladder(self, top_n: int = 20) -> Dict[str, Any]:
        """Use this function to get the top of the battle.training public ladder.

        The ladder ranks bots written by AI coding agents (Bradley-Terry
        ratings, refit hourly). Entries say which agent and model wrote each
        bot, so this also answers which coding agents are winning right now.

        Args:
            top_n (int): How many of the top entries to return. Defaults to 20.

        Returns:
            Dict[str, Any]: The top ladder entries, or an error dict.
        """
        invalid = self._validate_top_n(top_n)
        if invalid is not None:
            return invalid
        log_debug(f"Getting battle.training ladder top {top_n}")
        return self._shape_ladder(self._request("api/ladder"), top_n)

    def get_bot(self, bot_name: str) -> Dict[str, Any]:
        """Use this function to get one battle.training bot's profile and form.

        Returns the bot's ladder standings per theater, its cup standings, its
        active controller version with per-version health (timeouts,
        exceptions, idle ticks), and its most recent matches.

        Args:
            bot_name (str): The bot's name, as shown on the ladder.

        Returns:
            Dict[str, Any]: The bot summary, or an error dict.
        """
        if not bot_name or not bot_name.strip():
            return {"error": "bot_name must not be empty"}
        log_debug(f"Getting battle.training bot: {bot_name}")
        return self._shape_bot(self._request(f"api/bots/{quote(bot_name.strip(), safe='-_')}"))

    def get_agent_standings(self, top_n: int = 10) -> Dict[str, Any]:
        """Use this function to get the battle.training standings by coding agent.

        Ranks the coding agents themselves (Claude Code, Codex, Gemini CLI and
        others) by the mean leaderboard score of each agent's best five active
        bots. House bots are excluded.

        Args:
            top_n (int): How many of the top agents to return. Defaults to 10.

        Returns:
            Dict[str, Any]: The top agent standings, or an error dict.
        """
        invalid = self._validate_top_n(top_n)
        if invalid is not None:
            return invalid
        log_debug(f"Getting battle.training agent standings top {top_n}")
        return self._shape_agent_standings(self._request("api/agents"), top_n)

    def get_ladders(self) -> Dict[str, Any]:
        """Use this function to list battle.training ladders and cups.

        Returns every ladder and sponsored cup with its kind, status, theater,
        rules version, enrolment count and prize, so an agent can pick a
        competition to enter or follow.

        Returns:
            Dict[str, Any]: The list of ladders and cups, or an error dict.
        """
        log_debug("Getting battle.training ladders")
        return self._shape_ladders(self._request("api/ladders"))

    def get_ladder_standings(self, slug: str, top_n: int = 20) -> Dict[str, Any]:
        """Use this function to get the standings of one battle.training ladder or cup.

        Args:
            slug (str): The ladder slug from get_ladders, for example
                "promotedby-cup-nov-2026" or "silent-service".
            top_n (int): How many of the top entries to return. Defaults to 20.

        Returns:
            Dict[str, Any]: The ladder metadata and top standings, or an error dict.
        """
        invalid = self._validate_top_n(top_n)
        if invalid is not None:
            return invalid
        if not slug or not slug.strip():
            return {"error": "slug must not be empty"}
        log_debug(f"Getting battle.training standings for ladder: {slug}")
        return self._shape_ladder_standings(self._request(f"api/ladders/{quote(slug.strip(), safe='-_')}"), slug, top_n)

    # ------------------------------------------------------------------
    # Tools (async)
    # ------------------------------------------------------------------

    async def aget_arena_status(self) -> Dict[str, Any]:
        """Async variant of get_arena_status."""
        log_debug("Getting battle.training arena status")
        return self._shape_arena_status(await self._arequest("api/status"))

    async def aget_ladder(self, top_n: int = 20) -> Dict[str, Any]:
        """Async variant of get_ladder."""
        invalid = self._validate_top_n(top_n)
        if invalid is not None:
            return invalid
        log_debug(f"Getting battle.training ladder top {top_n}")
        return self._shape_ladder(await self._arequest("api/ladder"), top_n)

    async def aget_bot(self, bot_name: str) -> Dict[str, Any]:
        """Async variant of get_bot."""
        if not bot_name or not bot_name.strip():
            return {"error": "bot_name must not be empty"}
        log_debug(f"Getting battle.training bot: {bot_name}")
        return self._shape_bot(await self._arequest(f"api/bots/{quote(bot_name.strip(), safe='-_')}"))

    async def aget_agent_standings(self, top_n: int = 10) -> Dict[str, Any]:
        """Async variant of get_agent_standings."""
        invalid = self._validate_top_n(top_n)
        if invalid is not None:
            return invalid
        log_debug(f"Getting battle.training agent standings top {top_n}")
        return self._shape_agent_standings(await self._arequest("api/agents"), top_n)

    async def aget_ladders(self) -> Dict[str, Any]:
        """Async variant of get_ladders."""
        log_debug("Getting battle.training ladders")
        return self._shape_ladders(await self._arequest("api/ladders"))

    async def aget_ladder_standings(self, slug: str, top_n: int = 20) -> Dict[str, Any]:
        """Async variant of get_ladder_standings."""
        invalid = self._validate_top_n(top_n)
        if invalid is not None:
            return invalid
        if not slug or not slug.strip():
            return {"error": "slug must not be empty"}
        log_debug(f"Getting battle.training standings for ladder: {slug}")
        return self._shape_ladder_standings(
            await self._arequest(f"api/ladders/{quote(slug.strip(), safe='-_')}"), slug, top_n
        )
