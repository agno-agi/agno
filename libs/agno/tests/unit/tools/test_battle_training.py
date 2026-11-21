"""Unit tests for BattleTrainingTools class."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from agno.tools.battle_training import BattleTrainingTools


@pytest.fixture
def battle_training_tools():
    """Create a BattleTrainingTools instance with all tools enabled."""
    return BattleTrainingTools()


LADDER_PAYLOAD = {
    "updated_at": 1795225476589,
    "snapshot_at": 1795224128147,
    "entries": [
        {
            "rank": 1,
            "rank_delta": 0,
            "bot": "daemon-amber",
            "version": "v22-neon-nova",
            "handle": "daemon-amber",
            "house": False,
            "operator": False,
            "agent": "antigravity",
            "model": "gemini-4-argon",
            "x": None,
            "operator_x": None,
            "score": 2551,
            "rating": 2702,
            "rd": 76,
            "games": 34,
            "wins": 22,
            "losses": 5,
            "draws": 7,
            "last_played": 1795225026197,
            "active": True,
            "joined": 1793544212932,
        },
        {
            "rank": 2,
            "rank_delta": 0,
            "bot": "ephemeral-falconer",
            "version": "e28-0e0c3abc",
            "handle": "ephemeral",
            "house": False,
            "operator": False,
            "agent": "claude-code",
            "model": "claude-opus-5-5",
            "x": None,
            "operator_x": None,
            "score": 2463,
            "rating": 2550,
            "rd": 43,
            "games": 107,
            "wins": 66,
            "losses": 17,
            "draws": 24,
            "last_played": 1795225026197,
            "active": True,
            "joined": 1794937044898,
        },
    ],
}

BOT_PAYLOAD = {
    "name": "ephemeral-falconer",
    "handle": "ephemeral",
    "agent": "claude-code",
    "model": "claude-opus-5-5",
    "house": False,
    "operator": False,
    "created_at": 1794937044898,
    "theater": "armor",
    "x": None,
    "operator_x": None,
    "theaters": {
        "armor": {
            "ladder": "public",
            "name": "Public ladder",
            "rank": 2,
            "of": 378,
            "score": 2463,
            "rating": 2550,
            "rd": 43,
            "wins": 66,
            "losses": 17,
            "draws": 24,
            "sets": 107,
            "version": "e28-0e0c3abc",
            "url": "https://battle.training/ladder",
        }
    },
    "honours": [],
    "ladders": [
        {
            "ladder": "promotedby-cup-nov-2026",
            "rating": 1795,
            "rd": 58,
            "games": 72,
            "wins": 51,
            "losses": 12,
            "draws": 9,
            "last_played": 1795225322934,
            "enrolled_at": 1795114548445,
            "score": 1680,
            "rank": 2,
            "of": 294,
            "prize_usd": None,
        }
    ],
    "versions": [
        {
            "id": "ver_450f8d5810ac",
            "label": "e28-0e0c3abc",
            "active": True,
            "smoke_ok": True,
            "score": 2463,
            "rating": 2550,
            "rd": 43,
            "games": 107,
            "wins": 66,
            "losses": 17,
            "draws": 24,
            "health": {"timeouts": 0, "exceptions": 0, "idle_ticks": 0},
        },
        {
            "id": "ver_93d86ab9da54",
            "label": "e19-2b76745c",
            "active": False,
            "smoke_ok": True,
            "score": 1917,
            "rating": 2219,
            "rd": 151,
            "games": 7,
            "wins": 7,
            "losses": 0,
            "draws": 0,
            "health": {"timeouts": 0, "exceptions": 0, "idle_ticks": 0},
        },
    ],
    "matches": [
        {"id": "m_82933e3231b2", "ladder": "promotedby-cup-nov-2026", "status": "done", "seed": 2435369478},
        {"id": "m_1111111111a1", "ladder": "public", "status": "done", "seed": 123},
    ],
}

AGENTS_PAYLOAD = {
    "note": "score = mean leaderboard score of the agent's best five active bots; house bots excluded",
    "agents": [
        {
            "id": "claude-code",
            "score": 2240,
            "bots": 36,
            "players": 18,
            "games": 13184,
            "wins": 4992,
            "losses": 4898,
            "draws": 3294,
            "top_bot": "ephemeral-falconer",
            "models": ["claude-opus-5-5"],
        },
        {
            "id": "codex",
            "score": 2151,
            "bots": 66,
            "players": 54,
            "games": 33438,
            "wins": 13355,
            "losses": 12899,
            "draws": 7184,
            "top_bot": "sovereign-squad",
            "models": ["GPT-6"],
        },
    ],
}

STATUS_PAYLOAD = {
    "generated_at": "2026-11-21T01:47:34.757Z",
    "about": "battle.training is an arena where AI coding agents write the programs that command tank squads",
    "arena": {"bots": 379, "players": 313, "bots_playing_now": 128, "sets_last_hour": 770},
    "ladder": {
        "name": "Public ladder (Armor, Season 2)",
        "url": "https://battle.training/ladder",
        "ranked": 378,
        "updated_at": "2026-11-21T01:47:35.050Z",
        "top": [
            {
                "rank": 1,
                "bot": "daemon-amber",
                "version": "v22-neon-nova",
                "agent": "antigravity",
                "model": "gemini-4-argon",
                "score": 2551,
                "record": "22-5-7",
                "sets": 34,
                "url": "https://battle.training/bots/daemon-amber",
            }
        ],
    },
}

LADDERS_PAYLOAD = {
    "ladders": [
        {
            "slug": "public",
            "name": "Public ladder",
            "kind": "public",
            "status": "open",
            "starts_at": None,
            "ends_at": None,
            "rules_version": "s2.0.0",
            "theater": "armor",
            "prize": None,
            "sponsor": None,
            "entry": None,
            "enrolled": 378,
            "description_md": None,
            "url": "https://battle.training/cup/public",
        },
        {
            "slug": "promotedby-cup-nov-2026",
            "name": "promotedby.ai November Cup",
            "kind": "cup",
            "status": "open",
            "starts_at": 1793491200000,
            "ends_at": 1796083199000,
            "rules_version": "s2.0.0",
            "theater": "armor",
            "prize": {"total_usd": 250, "split_usd": [150, 70, 30], "currency": "USDC", "network": "Base"},
            "sponsor": {"name": "promotedby.ai"},
            "entry": {"fee_usd": 0, "one_bot_per_account": True, "min_sets_to_qualify": 100},
            "enrolled": 283,
            "description_md": "## Official rules",
            "url": "https://battle.training/cup/promotedby-cup-nov-2026",
        },
    ]
}

CUP_STANDINGS_PAYLOAD = {
    "slug": "promotedby-cup-nov-2026",
    "name": "promotedby.ai November Cup",
    "kind": "cup",
    "status": "open",
    "prize": {"total_usd": 250, "split_usd": [150, 70, 30], "currency": "USDC", "network": "Base"},
    "enrolled": 283,
    "standings": LADDER_PAYLOAD["entries"],
}


def _mock_response(payload):
    response = MagicMock()
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    return response


class TestBattleTrainingToolsInitialization:
    """Tests for BattleTrainingTools initialization."""

    def test_default_initialization(self):
        tools = BattleTrainingTools()

        function_names = [func.name for func in tools.functions.values()]

        assert "get_arena_status" in function_names
        assert "get_ladder" in function_names
        assert "get_bot" in function_names
        assert "get_agent_standings" in function_names
        assert "get_ladders" in function_names
        assert "get_ladder_standings" in function_names
        assert tools.name == "battle_training_tools"

    def test_initialization_with_all_flag(self):
        tools = BattleTrainingTools(
            enable_get_arena_status=False,
            enable_get_ladder=False,
            enable_get_bot=False,
            enable_get_agent_standings=False,
            enable_get_ladders=False,
            enable_get_ladder_standings=False,
            all=True,
        )

        function_names = [func.name for func in tools.functions.values()]

        assert len(function_names) == 6

    def test_initialization_single_tool(self):
        tools = BattleTrainingTools(
            enable_get_arena_status=False,
            enable_get_bot=False,
            enable_get_agent_standings=False,
            enable_get_ladders=False,
            enable_get_ladder_standings=False,
        )

        function_names = [func.name for func in tools.functions.values()]

        assert function_names == ["get_ladder"]
        assert len(tools.tools) == 1

    def test_initialization_no_tools_enabled(self):
        tools = BattleTrainingTools(
            enable_get_arena_status=False,
            enable_get_ladder=False,
            enable_get_bot=False,
            enable_get_agent_standings=False,
            enable_get_ladders=False,
            enable_get_ladder_standings=False,
        )

        assert tools.tools == []

    def test_async_tools_registered(self):
        tools = BattleTrainingTools()

        async_function_names = [func.name for func in tools.async_functions.values()]

        assert "get_ladder" in async_function_names
        assert "get_bot" in async_function_names

    def test_base_url_trailing_slash_stripped(self):
        tools = BattleTrainingTools(base_url="https://api.battle.training/")
        assert tools.base_url == "https://api.battle.training"


class TestGetArenaStatus:
    def test_get_arena_status_success(self, battle_training_tools):
        with patch("agno.tools.battle_training.httpx.Client") as mock_client_class:
            client = mock_client_class.return_value.__enter__.return_value
            client.get.return_value = _mock_response(STATUS_PAYLOAD)

            result = battle_training_tools.get_arena_status()

        assert result["bots"] == 379
        assert result["players"] == 313
        assert result["bots_playing_now"] == 128
        assert result["sets_last_hour"] == 770
        assert result["ranked_bots"] == 378
        assert result["top"][0]["bot"] == "daemon-amber"
        client.get.assert_called_once_with(
            "https://api.battle.training/api/status", headers=battle_training_tools.headers
        )


class TestGetLadder:
    def test_get_ladder_success(self, battle_training_tools):
        with patch("agno.tools.battle_training.httpx.Client") as mock_client_class:
            client = mock_client_class.return_value.__enter__.return_value
            client.get.return_value = _mock_response(LADDER_PAYLOAD)

            result = battle_training_tools.get_ladder()

        assert result["total_ranked"] == 2
        assert len(result["entries"]) == 2
        first = result["entries"][0]
        assert first["rank"] == 1
        assert first["bot"] == "daemon-amber"
        assert first["agent"] == "antigravity"
        assert first["rating_deviation"] == 76
        # Raw payload fields that are not part of the trimmed shape are dropped.
        assert "rank_delta" not in first
        assert "joined" not in first

    def test_get_ladder_top_n_slices(self, battle_training_tools):
        with patch("agno.tools.battle_training.httpx.Client") as mock_client_class:
            client = mock_client_class.return_value.__enter__.return_value
            client.get.return_value = _mock_response(LADDER_PAYLOAD)

            result = battle_training_tools.get_ladder(top_n=1)

        assert len(result["entries"]) == 1
        assert result["entries"][0]["bot"] == "daemon-amber"
        assert result["total_ranked"] == 2

    def test_get_ladder_invalid_top_n(self, battle_training_tools):
        with patch("agno.tools.battle_training.httpx.Client") as mock_client_class:
            result = battle_training_tools.get_ladder(top_n=0)

        assert result == {"error": "top_n must be at least 1"}
        mock_client_class.assert_not_called()


class TestGetBot:
    def test_get_bot_success(self, battle_training_tools):
        with patch("agno.tools.battle_training.httpx.Client") as mock_client_class:
            client = mock_client_class.return_value.__enter__.return_value
            client.get.return_value = _mock_response(BOT_PAYLOAD)

            result = battle_training_tools.get_bot("ephemeral-falconer")

        assert result["name"] == "ephemeral-falconer"
        assert result["agent"] == "claude-code"
        assert result["theaters"]["armor"]["rank"] == 2
        assert result["cups"][0]["ladder"] == "promotedby-cup-nov-2026"
        assert result["cups"][0]["rank"] == 2
        assert result["active_version"]["label"] == "e28-0e0c3abc"
        assert result["active_version"]["health"] == {"timeouts": 0, "exceptions": 0, "idle_ticks": 0}
        assert len(result["recent_matches"]) == 2
        assert result["url"] == "https://battle.training/bots/ephemeral-falconer"
        client.get.assert_called_once_with(
            "https://api.battle.training/api/bots/ephemeral-falconer",
            headers=battle_training_tools.headers,
        )

    def test_get_bot_empty_name(self, battle_training_tools):
        with patch("agno.tools.battle_training.httpx.Client") as mock_client_class:
            result = battle_training_tools.get_bot("  ")

        assert result == {"error": "bot_name must not be empty"}
        mock_client_class.assert_not_called()

    def test_get_bot_not_found(self, battle_training_tools):
        request = httpx.Request("GET", "https://api.battle.training/api/bots/nope")
        response = MagicMock(spec=httpx.Response)
        response.status_code = 404
        response.json.return_value = {"error": "bot not found"}
        response.raise_for_status.side_effect = httpx.HTTPStatusError("not found", request=request, response=response)

        with patch("agno.tools.battle_training.httpx.Client") as mock_client_class:
            client = mock_client_class.return_value.__enter__.return_value
            client.get.return_value = response

            result = battle_training_tools.get_bot("nope")

        assert result == {
            "error": "battle.training API request failed",
            "status_code": 404,
            "detail": "bot not found",
        }


class TestGetAgentStandings:
    def test_get_agent_standings_success(self, battle_training_tools):
        with patch("agno.tools.battle_training.httpx.Client") as mock_client_class:
            client = mock_client_class.return_value.__enter__.return_value
            client.get.return_value = _mock_response(AGENTS_PAYLOAD)

            result = battle_training_tools.get_agent_standings()

        assert len(result["agents"]) == 2
        assert result["agents"][0]["agent"] == "claude-code"
        assert result["agents"][0]["top_bot"] == "ephemeral-falconer"
        assert result["agents"][1]["agent"] == "codex"

    def test_get_agent_standings_top_n(self, battle_training_tools):
        with patch("agno.tools.battle_training.httpx.Client") as mock_client_class:
            client = mock_client_class.return_value.__enter__.return_value
            client.get.return_value = _mock_response(AGENTS_PAYLOAD)

            result = battle_training_tools.get_agent_standings(top_n=1)

        assert len(result["agents"]) == 1


class TestGetLadders:
    def test_get_ladders_success(self, battle_training_tools):
        with patch("agno.tools.battle_training.httpx.Client") as mock_client_class:
            client = mock_client_class.return_value.__enter__.return_value
            client.get.return_value = _mock_response(LADDERS_PAYLOAD)

            result = battle_training_tools.get_ladders()

        assert len(result["ladders"]) == 2
        cup = result["ladders"][1]
        assert cup["slug"] == "promotedby-cup-nov-2026"
        assert cup["kind"] == "cup"
        assert cup["enrolled"] == 283
        # The long markdown description is not part of the trimmed shape.
        assert "description_md" not in cup


class TestGetLadderStandings:
    def test_get_ladder_standings_success(self, battle_training_tools):
        with patch("agno.tools.battle_training.httpx.Client") as mock_client_class:
            client = mock_client_class.return_value.__enter__.return_value
            client.get.return_value = _mock_response(CUP_STANDINGS_PAYLOAD)

            result = battle_training_tools.get_ladder_standings("promotedby-cup-nov-2026", top_n=1)

        assert result["ladder"] == "promotedby-cup-nov-2026"
        assert result["total_ranked"] == 2
        assert len(result["standings"]) == 1
        assert result["standings"][0]["bot"] == "daemon-amber"

    def test_get_ladder_standings_empty_slug(self, battle_training_tools):
        result = battle_training_tools.get_ladder_standings("")
        assert result == {"error": "slug must not be empty"}


class TestErrorHandling:
    def test_request_error_returns_error_dict(self, battle_training_tools):
        with patch("agno.tools.battle_training.httpx.Client") as mock_client_class:
            client = mock_client_class.return_value.__enter__.return_value
            client.get.side_effect = httpx.ConnectError("connection refused")

            result = battle_training_tools.get_ladders()

        assert result["error"] == "battle.training API request failed"
        assert "connection refused" in result["detail"]


class TestAsyncTools:
    @pytest.mark.asyncio
    @patch("agno.tools.battle_training.httpx.AsyncClient")
    async def test_aget_ladder_uses_same_contract(self, mock_client_class, battle_training_tools):
        client = mock_client_class.return_value.__aenter__.return_value
        client.get = AsyncMock(return_value=_mock_response(LADDER_PAYLOAD))

        result = await battle_training_tools.aget_ladder(top_n=1)

        assert result["total_ranked"] == 2
        assert len(result["entries"]) == 1
        client.get.assert_awaited_once_with(
            "https://api.battle.training/api/ladder", headers=battle_training_tools.headers
        )

    @pytest.mark.asyncio
    @patch("agno.tools.battle_training.httpx.AsyncClient")
    async def test_aget_bot(self, mock_client_class, battle_training_tools):
        client = mock_client_class.return_value.__aenter__.return_value
        client.get = AsyncMock(return_value=_mock_response(BOT_PAYLOAD))

        result = await battle_training_tools.aget_bot("ephemeral-falconer")

        assert result["name"] == "ephemeral-falconer"
        assert result["active_version"]["label"] == "e28-0e0c3abc"

    @pytest.mark.asyncio
    async def test_aget_ladder_invalid_top_n(self, battle_training_tools):
        result = await battle_training_tools.aget_ladder(top_n=0)
        assert result == {"error": "top_n must be at least 1"}
