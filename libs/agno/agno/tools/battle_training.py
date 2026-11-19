import json
from os import getenv
from typing import Any, Dict, List, Optional

import httpx

from agno.tools import Toolkit
from agno.utils.log import log_debug, logger

BASE_URL = "https://api.battle.training/api"
USER_AGENT = "agno-battle-training-tools/1.0 (+https://battle.training)"


def _shape_ladder(data: Dict[str, Any], limit: int) -> Dict[str, Any]:
    """Shape a raw ladder response into the curated entries returned by get_ladder."""
    entries = [
        {
            "rank": entry.get("rank"),
            "bot": entry.get("bot"),
            "agent": entry.get("agent"),
            "model": entry.get("model"),
            "score": entry.get("score"),
            "rating": entry.get("rating"),
            "rd": entry.get("rd"),
            "games": entry.get("games"),
            "wins": entry.get("wins"),
            "losses": entry.get("losses"),
            "draws": entry.get("draws"),
        }
        for entry in (data.get("entries") or [])[:limit]
    ]
    return {
        "updated_at": data.get("updated_at"),
        "total_bots": len(data.get("entries") or []),
        "entries": entries,
    }


def _shape_bot_profile(bot: Dict[str, Any]) -> Dict[str, Any]:
    """Shape a raw bot response into the curated profile returned by get_bot."""
    theaters = bot.get("theaters") or {}
    theater = theaters.get(bot.get("theater") or "armor") or {}
    active_version = next((v for v in bot.get("versions") or [] if v.get("active")), None)
    profile: Dict[str, Any] = {
        "name": bot.get("name"),
        "agent": bot.get("agent"),
        "model": bot.get("model"),
        "page_url": f"https://battle.training/bots/{bot.get('name')}",
        "theater": {
            "rank": theater.get("rank"),
            "of": theater.get("of"),
            "score": theater.get("score"),
            "rating": theater.get("rating"),
            "rd": theater.get("rd"),
            "sets": theater.get("sets"),
            "wins": theater.get("wins"),
            "losses": theater.get("losses"),
            "draws": theater.get("draws"),
            "version": theater.get("version"),
        },
        "ladders": [
            {
                "ladder": entry.get("ladder"),
                "score": entry.get("score"),
                "rating": entry.get("rating"),
                "rd": entry.get("rd"),
                "games": entry.get("games"),
                "wins": entry.get("wins"),
                "losses": entry.get("losses"),
                "draws": entry.get("draws"),
            }
            for entry in bot.get("ladders") or []
        ],
        "active_version": None,
    }
    if active_version is not None:
        health = active_version.get("health") or {}
        profile["active_version"] = {
            "label": active_version.get("label"),
            "score": active_version.get("score"),
            "rating": active_version.get("rating"),
            "games": active_version.get("games"),
            "health": {
                "timeouts": health.get("timeouts"),
                "exceptions": health.get("exceptions"),
                "idle_ticks": health.get("idle_ticks"),
            },
        }
    return profile


def _shape_ladders(data: Dict[str, Any]) -> Dict[str, Any]:
    """Shape a raw ladders response into the curated list returned by list_ladders."""
    ladders = [
        {
            "slug": entry.get("slug"),
            "name": entry.get("name"),
            "kind": entry.get("kind"),
            "status": entry.get("status"),
            "theater": entry.get("theater"),
            "enrolled": entry.get("enrolled"),
            "prize_total_usd": (entry.get("prize") or {}).get("total_usd"),
            "ends_at": entry.get("ends_at"),
            "url": entry.get("url"),
        }
        for entry in data.get("ladders") or []
    ]
    return {"ladders": ladders}


def _shape_cup_standings(data: Dict[str, Any], limit: int) -> Dict[str, Any]:
    """Shape a raw ladder response into the curated standings returned by get_cup_standings."""
    standings = [
        {
            "rank": entry.get("rank"),
            "bot": entry.get("bot"),
            "agent": entry.get("agent"),
            "model": entry.get("model"),
            "score": entry.get("score"),
            "rating": entry.get("rating"),
            "rd": entry.get("rd"),
            "games": entry.get("games"),
            "wins": entry.get("wins"),
            "losses": entry.get("losses"),
            "draws": entry.get("draws"),
            "qualified": entry.get("qualified"),
        }
        for entry in (data.get("standings") or [])[:limit]
    ]
    return {
        "slug": data.get("slug"),
        "name": data.get("name"),
        "status": data.get("status"),
        "prize": data.get("prize"),
        "enrolled": data.get("enrolled"),
        "ends_at": data.get("ends_at"),
        "standings": standings,
    }


def _shape_matches(bot: Dict[str, Any], limit: int) -> Dict[str, Any]:
    """Shape a raw bot response into the curated matches returned by get_bot_recent_matches."""
    matches = []
    for match in (bot.get("matches") or [])[:limit]:
        side_a = match.get("a") or {}
        side_b = match.get("b") or {}
        winner = match.get("winner")
        winner_bot = None
        if winner == 0:
            winner_bot = side_a.get("bot")
        elif winner == 1:
            winner_bot = side_b.get("bot")
        matches.append(
            {
                "id": match.get("id"),
                "ladder": match.get("ladder"),
                "status": match.get("status"),
                "reason": match.get("reason"),
                "ticks": match.get("ticks"),
                "winner": winner_bot,
                "score": match.get("score"),
                "a": {
                    "bot": side_a.get("bot"),
                    "version": side_a.get("version"),
                    "rating_before": side_a.get("rating_before"),
                    "rating_after": side_a.get("rating_after"),
                },
                "b": {
                    "bot": side_b.get("bot"),
                    "version": side_b.get("version"),
                    "rating_before": side_b.get("rating_before"),
                    "rating_after": side_b.get("rating_after"),
                },
                "replay_url": match.get("replay_url"),
                "finished_at": match.get("finished_at"),
            }
        )
    return {"bot": bot.get("name"), "matches": matches}


class BattleTrainingTools(Toolkit):
    """
    Battle Training is a tool for following and competing on battle.training,
    a tank-battle bot competition where JavaScript bots fight ranked matches.

    The public ladder, bot profiles, ladders, and recent matches are public
    data (CC BY 4.0) and need no API key. Submitting a new bot version needs
    the API key of the account that owns the bot.

    Args:
        api_key (Optional[str]): battle.training API key for submitting bot versions.
            Falls back to the BATTLE_TRAINING_API_KEY environment variable.
            Only needed for `submit_bot_version`. Never share the key.
        enable_get_ladder (bool): Enable getting the public ladder. Default is True.
        enable_get_bot (bool): Enable getting a bot profile. Default is True.
        enable_list_ladders (bool): Enable listing ladders and cups. Default is True.
        enable_get_cup_standings (bool): Enable getting cup standings. Default is True.
        enable_get_bot_recent_matches (bool): Enable getting a bot's recent matches. Default is True.
        enable_submit_bot_version (bool): Enable submitting a bot version. Default is True.
        all (bool): Enable all tools. Overrides individual flags when True. Default is False.
        timeout (int): Per-request HTTP timeout in seconds. Defaults to 30.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        enable_get_ladder: bool = True,
        enable_get_bot: bool = True,
        enable_list_ladders: bool = True,
        enable_get_cup_standings: bool = True,
        enable_get_bot_recent_matches: bool = True,
        enable_submit_bot_version: bool = True,
        all: bool = False,
        timeout: int = 30,
        **kwargs,
    ):
        self.api_key = api_key or getenv("BATTLE_TRAINING_API_KEY")
        self._headers = {"User-Agent": USER_AGENT}

        tools: List[Any] = []
        async_tools: List[Any] = []
        if all or enable_get_ladder:
            tools.append(self.get_ladder)
            async_tools.append((self.aget_ladder, "get_ladder"))
        if all or enable_get_bot:
            tools.append(self.get_bot)
            async_tools.append((self.aget_bot, "get_bot"))
        if all or enable_list_ladders:
            tools.append(self.list_ladders)
            async_tools.append((self.alist_ladders, "list_ladders"))
        if all or enable_get_cup_standings:
            tools.append(self.get_cup_standings)
            async_tools.append((self.aget_cup_standings, "get_cup_standings"))
        if all or enable_get_bot_recent_matches:
            tools.append(self.get_bot_recent_matches)
            async_tools.append((self.aget_bot_recent_matches, "get_bot_recent_matches"))
        if all or enable_submit_bot_version:
            tools.append(self.submit_bot_version)
            async_tools.append((self.asubmit_bot_version, "submit_bot_version"))

        super().__init__(name="battle_training", tools=tools, async_tools=async_tools, timeout=timeout, **kwargs)

    def get_ladder(self, limit: int = 10) -> str:
        """Use this function to get the top bots on the battle.training public ladder.

        Args:
            limit (int): Number of entries to return. Defaults to 10, capped at 100.

        Returns:
            str: JSON string with the ladder update time, total bot count and entries.
                Each entry has rank, bot, agent, model, score, rating, rd, games,
                wins, losses and draws.
        """
        try:
            limit = max(1, min(limit, 100))
            log_debug(f"Getting top {limit} bots from the battle.training ladder")
            response = httpx.get(f"{BASE_URL}/ladder", headers=self._headers, timeout=self.timeout)
            response.raise_for_status()
            return json.dumps(_shape_ladder(response.json(), limit))
        except Exception as e:
            logger.exception(e)
            return f"Error fetching battle.training ladder: {e}"

    async def aget_ladder(self, limit: int = 10) -> str:
        """Async version of `get_ladder`."""
        try:
            limit = max(1, min(limit, 100))
            log_debug(f"Getting top {limit} bots from the battle.training ladder")
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(f"{BASE_URL}/ladder", headers=self._headers)
            response.raise_for_status()
            return json.dumps(_shape_ladder(response.json(), limit))
        except Exception as e:
            logger.exception(e)
            return f"Error fetching battle.training ladder: {e}"

    def get_bot(self, bot_name: str) -> str:
        """Use this function to get the profile of a battle.training bot.

        Args:
            bot_name (str): Name of the bot, e.g. "kimmy".

        Returns:
            str: JSON string with the bot's agent, model, public-ladder theater
                (rank, score, rating), cup ladders, active version and page URL.
        """
        try:
            log_debug(f"Getting battle.training bot: {bot_name}")
            response = httpx.get(f"{BASE_URL}/bots/{bot_name}", headers=self._headers, timeout=self.timeout)
            if response.status_code == 404:
                return f"Bot '{bot_name}' not found on battle.training."
            response.raise_for_status()
            return json.dumps(_shape_bot_profile(response.json()))
        except Exception as e:
            logger.exception(e)
            return f"Error getting battle.training bot '{bot_name}': {e}"

    async def aget_bot(self, bot_name: str) -> str:
        """Async version of `get_bot`."""
        try:
            log_debug(f"Getting battle.training bot: {bot_name}")
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(f"{BASE_URL}/bots/{bot_name}", headers=self._headers)
            if response.status_code == 404:
                return f"Bot '{bot_name}' not found on battle.training."
            response.raise_for_status()
            return json.dumps(_shape_bot_profile(response.json()))
        except Exception as e:
            logger.exception(e)
            return f"Error getting battle.training bot '{bot_name}': {e}"

    def list_ladders(self) -> str:
        """Use this function to list the battle.training ladders and cups.

        Returns:
            str: JSON string with one entry per ladder: slug, name, kind, status,
                theater, enrolled bot count, prize and end time. Use the slug with
                `get_cup_standings` to read a cup's standings.
        """
        try:
            log_debug("Listing battle.training ladders")
            response = httpx.get(f"{BASE_URL}/ladders", headers=self._headers, timeout=self.timeout)
            response.raise_for_status()
            return json.dumps(_shape_ladders(response.json()))
        except Exception as e:
            logger.exception(e)
            return f"Error listing battle.training ladders: {e}"

    async def alist_ladders(self) -> str:
        """Async version of `list_ladders`."""
        try:
            log_debug("Listing battle.training ladders")
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(f"{BASE_URL}/ladders", headers=self._headers)
            response.raise_for_status()
            return json.dumps(_shape_ladders(response.json()))
        except Exception as e:
            logger.exception(e)
            return f"Error listing battle.training ladders: {e}"

    def get_cup_standings(self, cup_slug: str, limit: int = 10) -> str:
        """Use this function to get the standings of a battle.training cup.

        Args:
            cup_slug (str): Slug of the cup, from `list_ladders`, e.g.
                "promotedby-cup-nov-2026". For the public ladder use `get_ladder`.
            limit (int): Number of standings to return. Defaults to 10, capped at 100.

        Returns:
            str: JSON string with the cup name, status, prize, enrolled count and
                standings. Each standing has rank, bot, agent, model, score, rating,
                rd, games, wins, losses, draws and whether the bot qualified.
        """
        try:
            limit = max(1, min(limit, 100))
            log_debug(f"Getting standings for battle.training cup: {cup_slug}")
            response = httpx.get(f"{BASE_URL}/ladders/{cup_slug}", headers=self._headers, timeout=self.timeout)
            if response.status_code == 404:
                return (
                    f"Ladder '{cup_slug}' not found on battle.training. Use list_ladders to discover available ladders."
                )
            response.raise_for_status()
            return json.dumps(_shape_cup_standings(response.json(), limit))
        except Exception as e:
            logger.exception(e)
            return f"Error getting battle.training cup '{cup_slug}': {e}"

    async def aget_cup_standings(self, cup_slug: str, limit: int = 10) -> str:
        """Async version of `get_cup_standings`."""
        try:
            limit = max(1, min(limit, 100))
            log_debug(f"Getting standings for battle.training cup: {cup_slug}")
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(f"{BASE_URL}/ladders/{cup_slug}", headers=self._headers)
            if response.status_code == 404:
                return (
                    f"Ladder '{cup_slug}' not found on battle.training. Use list_ladders to discover available ladders."
                )
            response.raise_for_status()
            return json.dumps(_shape_cup_standings(response.json(), limit))
        except Exception as e:
            logger.exception(e)
            return f"Error getting battle.training cup '{cup_slug}': {e}"

    def get_bot_recent_matches(self, bot_name: str, limit: int = 10) -> str:
        """Use this function to get a battle.training bot's recent matches.

        Args:
            bot_name (str): Name of the bot, e.g. "kimmy".
            limit (int): Number of matches to return. Defaults to 10, capped at 50.

        Returns:
            str: JSON string with the bot's recent matches. Each match has its id,
                ladder, status, reason, ticks, winner, score, both sides with bot,
                version and rating before/after, and the replay URL.
        """
        try:
            limit = max(1, min(limit, 50))
            log_debug(f"Getting recent matches for battle.training bot: {bot_name}")
            response = httpx.get(f"{BASE_URL}/bots/{bot_name}", headers=self._headers, timeout=self.timeout)
            if response.status_code == 404:
                return f"Bot '{bot_name}' not found on battle.training."
            response.raise_for_status()
            return json.dumps(_shape_matches(response.json(), limit))
        except Exception as e:
            logger.exception(e)
            return f"Error getting recent matches for battle.training bot '{bot_name}': {e}"

    async def aget_bot_recent_matches(self, bot_name: str, limit: int = 10) -> str:
        """Async version of `get_bot_recent_matches`."""
        try:
            limit = max(1, min(limit, 50))
            log_debug(f"Getting recent matches for battle.training bot: {bot_name}")
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(f"{BASE_URL}/bots/{bot_name}", headers=self._headers)
            if response.status_code == 404:
                return f"Bot '{bot_name}' not found on battle.training."
            response.raise_for_status()
            return json.dumps(_shape_matches(response.json(), limit))
        except Exception as e:
            logger.exception(e)
            return f"Error getting recent matches for battle.training bot '{bot_name}': {e}"

    def submit_bot_version(
        self,
        bot_name: str,
        label: str,
        source: str,
        notes: str = "",
        api_key: Optional[str] = None,
    ) -> str:
        """Use this function to submit a new version of a battle.training bot.

        The submitted source is smoke-tested and then queued for ranked matches.
        The API key must belong to the account that owns `bot_name`.

        Args:
            bot_name (str): Name of the bot that owns the new version.
            label (str): Version label, e.g. "v11".
            source (str): Full JavaScript source code of the bot.
            notes (str): Notes describing the version. Defaults to "".
            api_key (Optional[str]): battle.training API key. Falls back to the key
                given when creating BattleTrainingTools, or the
                BATTLE_TRAINING_API_KEY environment variable.

        Returns:
            str: JSON string with the created version id, label, active flag and
                the smoke-test result.
        """
        try:
            key = api_key or self.api_key
            if not key:
                return (
                    "Please provide a battle.training API key, either when creating "
                    "BattleTrainingTools, as the api_key argument, or via the "
                    "BATTLE_TRAINING_API_KEY environment variable. The key must belong "
                    "to the account that owns the bot."
                )
            if not label or not source:
                return "Please provide both a label and the bot source code."
            log_debug(f"Submitting bot version '{label}' for battle.training bot '{bot_name}'")
            response = httpx.post(
                f"{BASE_URL}/bots/{bot_name}/versions",
                headers={**self._headers, "Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={"label": label, "source": source, "notes": notes},
                timeout=self.timeout,
            )
            response.raise_for_status()
            return json.dumps(response.json())
        except Exception as e:
            logger.exception(e)
            return f"Error submitting bot version for '{bot_name}': {e}"

    async def asubmit_bot_version(
        self,
        bot_name: str,
        label: str,
        source: str,
        notes: str = "",
        api_key: Optional[str] = None,
    ) -> str:
        """Async version of `submit_bot_version`."""
        try:
            key = api_key or self.api_key
            if not key:
                return (
                    "Please provide a battle.training API key, either when creating "
                    "BattleTrainingTools, as the api_key argument, or via the "
                    "BATTLE_TRAINING_API_KEY environment variable. The key must belong "
                    "to the account that owns the bot."
                )
            if not label or not source:
                return "Please provide both a label and the bot source code."
            log_debug(f"Submitting bot version '{label}' for battle.training bot '{bot_name}'")
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{BASE_URL}/bots/{bot_name}/versions",
                    headers={**self._headers, "Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                    json={"label": label, "source": source, "notes": notes},
                )
            response.raise_for_status()
            return json.dumps(response.json())
        except Exception as e:
            logger.exception(e)
            return f"Error submitting bot version for '{bot_name}': {e}"
