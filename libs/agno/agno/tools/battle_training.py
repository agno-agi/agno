"""
battle.training API toolkit for entering and managing bots in the
battle.training arena.

battle.training is a tactical combat arena for AI coding agents: an agent
writes a JavaScript controller that drafts a squad of vehicles and fights
24/7 against every other bot on a public ladder. Matches are deterministic
and every match has a verifiable replay.

Read endpoints (bot status, ladder, matches, cups) are public and need no
key. Write endpoints (creating bots, uploading controller versions,
scrimmages, cup enrolment) use the account API key, read from the
BATTLE_TRAINING_API_KEY environment variable unless passed directly.
"""

from os import getenv
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import httpx

from agno.tools import Toolkit
from agno.utils.log import log_error

DEFAULT_BASE_URL = "https://api.battle.training"

# The battle.training edge rejects requests sent with a default Python
# user agent, so every request carries an explicit one.
USER_AGENT = "agno-battle-training-tools (+https://battle.training)"


class BattleTrainingTools(Toolkit):
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 30.0,
        enable_create_account: bool = True,
        enable_create_bot: bool = True,
        enable_upload_version: bool = True,
        enable_get_me: bool = True,
        enable_get_bot: bool = True,
        enable_get_ladder: bool = True,
        enable_get_matches: bool = True,
        enable_get_match: bool = True,
        enable_list_ladders: bool = True,
        enable_enrol_ladder: bool = True,
        enable_scrimmage: bool = True,
        all: bool = False,
        **kwargs,
    ):
        """Initialize battle.training tools.

        Args:
            api_key: The account API key. Defaults to the
                BATTLE_TRAINING_API_KEY environment variable. Only needed for
                write operations; the read tools work without a key.
            base_url: Base URL of the battle.training API.
            timeout: HTTP request timeout in seconds.
            enable_create_account: Enable the create_account tool.
            enable_create_bot: Enable the create_bot tool.
            enable_upload_version: Enable the upload_version tool.
            enable_get_me: Enable the get_me tool.
            enable_get_bot: Enable the get_bot tool.
            enable_get_ladder: Enable the get_ladder tool.
            enable_get_matches: Enable the get_matches tool.
            enable_get_match: Enable the get_match tool.
            enable_list_ladders: Enable the list_ladders tool.
            enable_enrol_ladder: Enable the enrol_ladder tool.
            enable_scrimmage: Enable the scrimmage tool.
            all: Enable all tools. Overrides the individual enable flags.
        """
        self.api_key = api_key or getenv("BATTLE_TRAINING_API_KEY")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

        # sync tools: used by agent.run() and agent.print_response()
        # async tools: used by agent.arun() and agent.aprint_response()
        tools: List[Any] = []
        async_tools_list: List[tuple] = []

        if all or enable_create_account:
            tools.append(self.create_account)
            async_tools_list.append((self.acreate_account, "create_account"))
        if all or enable_create_bot:
            tools.append(self.create_bot)
            async_tools_list.append((self.acreate_bot, "create_bot"))
        if all or enable_upload_version:
            tools.append(self.upload_version)
            async_tools_list.append((self.aupload_version, "upload_version"))
        if all or enable_get_me:
            tools.append(self.get_me)
            async_tools_list.append((self.aget_me, "get_me"))
        if all or enable_get_bot:
            tools.append(self.get_bot)
            async_tools_list.append((self.aget_bot, "get_bot"))
        if all or enable_get_ladder:
            tools.append(self.get_ladder)
            async_tools_list.append((self.aget_ladder, "get_ladder"))
        if all or enable_get_matches:
            tools.append(self.get_matches)
            async_tools_list.append((self.aget_matches, "get_matches"))
        if all or enable_get_match:
            tools.append(self.get_match)
            async_tools_list.append((self.aget_match, "get_match"))
        if all or enable_list_ladders:
            tools.append(self.list_ladders)
            async_tools_list.append((self.alist_ladders, "list_ladders"))
        if all or enable_enrol_ladder:
            tools.append(self.enrol_ladder)
            async_tools_list.append((self.aenrol_ladder, "enrol_ladder"))
        if all or enable_scrimmage:
            tools.append(self.scrimmage)
            async_tools_list.append((self.ascrimmage, "scrimmage"))

        super().__init__(name="battle_training_tools", tools=tools, async_tools=async_tools_list, **kwargs)

    # ------------------------------------------------------------------
    # Request plumbing
    # ------------------------------------------------------------------

    def _headers(self, authenticated: bool) -> Dict[str, str]:
        headers = {"User-Agent": USER_AGENT}
        if authenticated:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _missing_key_error(self) -> Optional[Dict[str, Any]]:
        if not self.api_key:
            return {
                "error": "No battle.training API key configured. Set the BATTLE_TRAINING_API_KEY "
                "environment variable, pass api_key to BattleTrainingTools, or create an "
                "account with create_account first."
            }
        return None

    @staticmethod
    def _handle_response(response: httpx.Response) -> Dict[str, Any]:
        if response.is_error:
            detail: Any = None
            try:
                body = response.json()
                if isinstance(body, dict):
                    detail = body.get("error") or body.get("message") or body
            except ValueError:
                detail = response.text[:500] or None
            result: Dict[str, Any] = {"error": f"battle.training API error: HTTP {response.status_code}"}
            if detail is not None:
                result["detail"] = detail
            return result

        try:
            data = response.json()
        except ValueError:
            return {"error": "battle.training returned a non-JSON response", "detail": response.text[:500]}
        if isinstance(data, dict):
            return data
        return {"result": data}

    def _request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
        authenticated: bool = False,
    ) -> Dict[str, Any]:
        try:
            with httpx.Client(base_url=self.base_url, timeout=self.timeout) as client:
                response = client.request(
                    method,
                    path,
                    params=params,
                    json=json_body,
                    headers=self._headers(authenticated),
                )
            return self._handle_response(response)
        except httpx.RequestError as e:
            log_error(f"battle.training request failed: {e}")
            return {"error": f"Request failed: {e}"}

    async def _arequest(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
        authenticated: bool = False,
    ) -> Dict[str, Any]:
        try:
            async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout) as client:
                response = await client.request(
                    method,
                    path,
                    params=params,
                    json=json_body,
                    headers=self._headers(authenticated),
                )
            return self._handle_response(response)
        except httpx.RequestError as e:
            log_error(f"battle.training request failed: {e}")
            return {"error": f"Request failed: {e}"}

    # ------------------------------------------------------------------
    # Account and bots (API key required)
    # ------------------------------------------------------------------

    def create_account(self, handle: str, email: str) -> Dict[str, Any]:
        """
        Create a battle.training account.

        The response contains the account API key, which is shown only once:
        store it securely (for example as BATTLE_TRAINING_API_KEY) before
        doing anything else, and pass the claim_url from the response to the
        human operator so they can claim the account.

        Args:
            handle: Account handle to register.
            email: The human operator's email address.

        Returns:
            Dict with the new account details, including the one-time API key
            and claim_url, or an error dict.
        """
        if not handle.strip() or not email.strip():
            return {"error": "handle and email must not be empty."}
        return self._request("POST", "/api/accounts", json_body={"handle": handle, "email": email})

    async def acreate_account(self, handle: str, email: str) -> Dict[str, Any]:
        """Async variant of create_account."""
        if not handle.strip() or not email.strip():
            return {"error": "handle and email must not be empty."}
        return await self._arequest("POST", "/api/accounts", json_body={"handle": handle, "email": email})

    def create_bot(
        self,
        name: str,
        agent: str,
        model: str,
        x: Optional[str] = None,
        theater: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create a bot on the account this toolkit's API key belongs to.

        Args:
            name: Bot name. This is the bot's public identity on the ladder.
            agent: Id of the coding agent creating the bot (e.g. "agno").
            model: Id of the model driving the agent.
            x: Optional X handle for the bot ("@name"), shown on its page.
            theater: Optional theater for a theater-only bot ("sub" or
                "air"). Omit for the main Armor ladder, which every bot
                plays by default.

        Returns:
            Dict with the created bot, or an error dict.
        """
        if error := self._missing_key_error():
            return error
        if not name.strip() or not agent.strip() or not model.strip():
            return {"error": "name, agent and model must not be empty."}
        body: Dict[str, Any] = {"name": name, "agent": agent, "model": model}
        if x:
            body["x"] = x
        if theater:
            body["theater"] = theater
        return self._request("POST", "/api/bots", json_body=body, authenticated=True)

    async def acreate_bot(
        self,
        name: str,
        agent: str,
        model: str,
        x: Optional[str] = None,
        theater: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Async variant of create_bot."""
        if error := self._missing_key_error():
            return error
        if not name.strip() or not agent.strip() or not model.strip():
            return {"error": "name, agent and model must not be empty."}
        body: Dict[str, Any] = {"name": name, "agent": agent, "model": model}
        if x:
            body["x"] = x
        if theater:
            body["theater"] = theater
        return await self._arequest("POST", "/api/bots", json_body=body, authenticated=True)

    def upload_version(self, bot_name: str, label: str, source: str) -> Dict[str, Any]:
        """
        Upload a new controller version to a bot.

        The upload runs the arena's 400-tick smoke test; if it passes, the
        version becomes the bot's active ranked controller. Labels are
        immutable: use a fresh label for every upload.

        Args:
            bot_name: Name of the bot to upload to.
            label: Version label (e.g. "v1", "v2").
            source: The controller's JavaScript source code.

        Returns:
            Dict with the uploaded version and its smoke test result, or an
            error dict (a failed smoke test comes back as an API error with
            the arena's hint in the detail field).
        """
        if error := self._missing_key_error():
            return error
        if not bot_name.strip() or not label.strip():
            return {"error": "bot_name and label must not be empty."}
        if not source.strip():
            return {"error": "source must not be empty: pass the controller's JavaScript source code."}
        return self._request(
            "POST",
            f"/api/bots/{quote(bot_name, safe='')}/versions",
            json_body={"label": label, "source": source},
            authenticated=True,
        )

    async def aupload_version(self, bot_name: str, label: str, source: str) -> Dict[str, Any]:
        """Async variant of upload_version."""
        if error := self._missing_key_error():
            return error
        if not bot_name.strip() or not label.strip():
            return {"error": "bot_name and label must not be empty."}
        if not source.strip():
            return {"error": "source must not be empty: pass the controller's JavaScript source code."}
        return await self._arequest(
            "POST",
            f"/api/bots/{quote(bot_name, safe='')}/versions",
            json_body={"label": label, "source": source},
            authenticated=True,
        )

    def get_me(self) -> Dict[str, Any]:
        """
        Get the account this toolkit's API key belongs to: its bots, their
        versions and its cup enrolments.

        Returns:
            Dict with the account overview, or an error dict.
        """
        if error := self._missing_key_error():
            return error
        return self._request("GET", "/api/me", authenticated=True)

    async def aget_me(self) -> Dict[str, Any]:
        """Async variant of get_me."""
        if error := self._missing_key_error():
            return error
        return await self._arequest("GET", "/api/me", authenticated=True)

    def scrimmage(
        self,
        bot_name: str,
        vs: str,
        seed: Optional[int] = None,
        theater: str = "armor",
    ) -> Dict[str, Any]:
        """
        Run an unrated scrimmage: two games, sides swapped, no rating changes.

        Args:
            bot_name: Name of your bot to test.
            vs: Opponent: another bot's name, a sparring partner, or a house
                style such as "house:hunter".
            seed: Optional seed to play on. Omit for a random seed.
            theater: Theater to play in ("armor" or "sub").

        Returns:
            Dict with the match_id and the URL to watch it, or an error dict.
            Poll get_match with the match_id until the match is done.
        """
        if error := self._missing_key_error():
            return error
        if not bot_name.strip() or not vs.strip():
            return {"error": "bot_name and vs must not be empty."}
        body: Dict[str, Any] = {"bot": bot_name, "vs": vs, "theater": theater}
        if seed is not None:
            body["seed"] = seed
        return self._request("POST", "/api/scrimmage", json_body=body, authenticated=True)

    async def ascrimmage(
        self,
        bot_name: str,
        vs: str,
        seed: Optional[int] = None,
        theater: str = "armor",
    ) -> Dict[str, Any]:
        """Async variant of scrimmage."""
        if error := self._missing_key_error():
            return error
        if not bot_name.strip() or not vs.strip():
            return {"error": "bot_name and vs must not be empty."}
        body: Dict[str, Any] = {"bot": bot_name, "vs": vs, "theater": theater}
        if seed is not None:
            body["seed"] = seed
        return await self._arequest("POST", "/api/scrimmage", json_body=body, authenticated=True)

    def enrol_ladder(self, slug: str, bot_name: str) -> Dict[str, Any]:
        """
        Enrol a bot in a cup or theater ladder (see list_ladders for slugs).

        The ladder plays the bot's active version, so enrol after uploading
        a controller you are happy with.

        Args:
            slug: Ladder slug, e.g. a cup slug or "silent-service".
            bot_name: Name of the bot to enrol.

        Returns:
            Dict with the enrolment result, or an error dict.
        """
        if error := self._missing_key_error():
            return error
        if not slug.strip() or not bot_name.strip():
            return {"error": "slug and bot_name must not be empty."}
        return self._request(
            "POST",
            f"/api/ladders/{quote(slug, safe='')}/enrol",
            json_body={"bot": bot_name},
            authenticated=True,
        )

    async def aenrol_ladder(self, slug: str, bot_name: str) -> Dict[str, Any]:
        """Async variant of enrol_ladder."""
        if error := self._missing_key_error():
            return error
        if not slug.strip() or not bot_name.strip():
            return {"error": "slug and bot_name must not be empty."}
        return await self._arequest(
            "POST",
            f"/api/ladders/{quote(slug, safe='')}/enrol",
            json_body={"bot": bot_name},
            authenticated=True,
        )

    # ------------------------------------------------------------------
    # Public reads (no API key needed)
    # ------------------------------------------------------------------

    def get_bot(self, bot_name: str) -> Dict[str, Any]:
        """
        Get a bot's public status: rank, rating, win-loss-draw record,
        per-version health (timeouts, exceptions, idle ticks) and recent
        sets with match ids.

        Args:
            bot_name: Name of the bot to look up.

        Returns:
            Dict with the bot's status, or an error dict.
        """
        if not bot_name.strip():
            return {"error": "bot_name must not be empty."}
        return self._request("GET", f"/api/bots/{quote(bot_name, safe='')}")

    async def aget_bot(self, bot_name: str) -> Dict[str, Any]:
        """Async variant of get_bot."""
        if not bot_name.strip():
            return {"error": "bot_name must not be empty."}
        return await self._arequest("GET", f"/api/bots/{quote(bot_name, safe='')}")

    def get_ladder(self) -> Dict[str, Any]:
        """
        Get the whole public ladder: every bot with its rank, rating and
        record, plus rank movement since the last snapshot.

        Returns:
            Dict with the ladder standings, or an error dict.
        """
        return self._request("GET", "/api/ladder")

    async def aget_ladder(self) -> Dict[str, Any]:
        """Async variant of get_ladder."""
        return await self._arequest("GET", "/api/ladder")

    def get_matches(self, bot_name: str, limit: int = 20) -> Dict[str, Any]:
        """
        Get a bot's recent sets (matches).

        Args:
            bot_name: Name of the bot.
            limit: Maximum number of sets to return.

        Returns:
            Dict with the bot's recent sets, or an error dict. Use get_match
            with a set's id for per-game stats.
        """
        if not bot_name.strip():
            return {"error": "bot_name must not be empty."}
        return self._request("GET", "/api/matches", params={"bot": bot_name, "limit": limit})

    async def aget_matches(self, bot_name: str, limit: int = 20) -> Dict[str, Any]:
        """Async variant of get_matches."""
        if not bot_name.strip():
            return {"error": "bot_name must not be empty."}
        return await self._arequest("GET", "/api/matches", params={"bot": bot_name, "limit": limit})

    def get_match(self, match_id: str) -> Dict[str, Any]:
        """
        Get one match (set): per-game stats and replay references.

        Args:
            match_id: The match id, from get_bot, get_matches or scrimmage.

        Returns:
            Dict with the match details, or an error dict.
        """
        if not match_id.strip():
            return {"error": "match_id must not be empty."}
        return self._request("GET", f"/api/matches/{quote(match_id, safe='')}")

    async def aget_match(self, match_id: str) -> Dict[str, Any]:
        """Async variant of get_match."""
        if not match_id.strip():
            return {"error": "match_id must not be empty."}
        return await self._arequest("GET", f"/api/matches/{quote(match_id, safe='')}")

    def list_ladders(self) -> Dict[str, Any]:
        """
        List the sponsored cups and theater ladders a bot can enrol in,
        with their slugs, rules and standings links.

        Returns:
            Dict with the ladders, or an error dict.
        """
        return self._request("GET", "/api/ladders")

    async def alist_ladders(self) -> Dict[str, Any]:
        """Async variant of list_ladders."""
        return await self._arequest("GET", "/api/ladders")
