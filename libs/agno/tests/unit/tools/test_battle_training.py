"""Unit tests for BattleTrainingTools class."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agno.tools.battle_training import BattleTrainingTools

MOCK_LADDER = {
    "updated_at": "2026-11-19T17:00:00.000Z",
    "snapshot_at": "2026-11-19T17:00:00.000Z",
    "entries": [
        {
            "rank": 1,
            "bot": "ephemeral-falconer",
            "agent": "claude-code",
            "model": "claude-opus-5-5",
            "score": 2466,
            "rating": 2580,
            "rd": 57,
            "games": 64,
            "wins": 48,
            "losses": 5,
            "draws": 11,
        },
        {
            "rank": 2,
            "bot": "kimmy",
            "agent": "muse",
            "model": "muse-spark-1.3",
            "score": 1054,
            "rating": 1131,
            "rd": 38,
            "games": 81,
            "wins": 26,
            "losses": 30,
            "draws": 25,
        },
    ],
}

MOCK_BOT = {
    "name": "kimmy",
    "agent": "muse",
    "model": "muse-spark-1.3",
    "theater": "armor",
    "theaters": {
        "armor": {
            "rank": 214,
            "of": 362,
            "score": 1054,
            "rating": 1131,
            "rd": 38,
            "sets": 81,
            "wins": 26,
            "losses": 30,
            "draws": 25,
            "version": "v10",
        }
    },
    "ladders": [
        {
            "ladder": "promotedby-cup-nov-2026",
            "rating": 1169,
            "rd": 25,
            "games": 250,
            "wins": 71,
            "losses": 72,
            "draws": 107,
            "score": 1119,
        }
    ],
    "versions": [
        {
            "label": "v10",
            "active": True,
            "score": 1054,
            "rating": 1131,
            "games": 81,
            "health": {"timeouts": 0, "exceptions": 0, "idle_ticks": 0},
        },
        {"label": "v9", "active": False, "score": 900, "rating": 1000, "games": 40, "health": {}},
    ],
    "matches": [
        {
            "id": "m_8b05160485df",
            "ladder": "promotedby-cup-nov-2026",
            "status": "done",
            "reason": "set 2-0",
            "ticks": 9282,
            "winner": 0,
            "score": [37273, 28235],
            "a": {"bot": "kimmy", "version": "v10", "rating_before": 1157, "rating_after": 1169},
            "b": {"bot": "opus-4-8", "version": "v7", "rating_before": 1151, "rating_after": 1139},
            "replay_url": "https://api.battle.training/api/replays/m_8b05160485df",
            "finished_at": 1795109764214,
        }
    ],
}

MOCK_LADDERS = {
    "ladders": [
        {
            "slug": "public",
            "name": "Public ladder",
            "kind": "public",
            "status": "open",
            "theater": "armor",
            "enrolled": 362,
            "prize": None,
            "ends_at": None,
            "url": "https://battle.training/cup/public",
        },
        {
            "slug": "promotedby-cup-nov-2026",
            "name": "promotedby.ai November Cup",
            "kind": "cup",
            "status": "open",
            "theater": "armor",
            "enrolled": 266,
            "prize": {"total_usd": 250, "split_usd": [150, 70, 30]},
            "ends_at": 1796083199000,
            "url": "https://battle.training/cup/promotedby-cup-nov-2026",
        },
    ]
}

MOCK_CUP = {
    "slug": "promotedby-cup-nov-2026",
    "name": "promotedby.ai November Cup",
    "status": "open",
    "prize": {"total_usd": 250, "split_usd": [150, 70, 30]},
    "enrolled": 266,
    "ends_at": 1796083199000,
    "standings": [
        {
            "rank": 1,
            "bot": "bazookabot-lab",
            "agent": "claude-code",
            "model": "claude-opus-4-8",
            "score": 1720,
            "rating": 1720,
            "rd": 40,
            "games": 300,
            "wins": 150,
            "losses": 60,
            "draws": 90,
            "qualified": True,
        },
        {
            "rank": 2,
            "bot": "kimmy",
            "agent": "muse",
            "model": "muse-spark-1.3",
            "score": 1119,
            "rating": 1169,
            "rd": 25,
            "games": 250,
            "wins": 71,
            "losses": 72,
            "draws": 107,
            "qualified": True,
        },
    ],
}

MOCK_SUBMIT_RESPONSE = {
    "version_id": "ver_0ff8bb95c208",
    "label": "v10",
    "active": True,
    "smoke": {"stage": "match", "ticks": 400, "failures": 0, "timeouts": 0, "exceptions": 0},
    "status": "active: queued for ranked matches",
}

ALL_FUNCTIONS = [
    "get_ladder",
    "get_bot",
    "list_ladders",
    "get_cup_standings",
    "get_bot_recent_matches",
    "submit_bot_version",
]


@pytest.fixture
def battle_training_tools():
    """Create a BattleTrainingTools instance with all tools enabled."""
    return BattleTrainingTools()


@pytest.fixture
def ladder_only_tools():
    """Create a BattleTrainingTools instance with only get_ladder enabled."""
    return BattleTrainingTools(
        enable_get_ladder=True,
        enable_get_bot=False,
        enable_list_ladders=False,
        enable_get_cup_standings=False,
        enable_get_bot_recent_matches=False,
        enable_submit_bot_version=False,
    )


def _mock_response(payload, status_code=200):
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = payload
    return response


def _mock_async_client(mock_client_class, method, payload, status_code=200):
    """Point a mocked httpx.AsyncClient at a canned response."""
    client = MagicMock()
    setattr(client, method, AsyncMock(return_value=_mock_response(payload, status_code)))
    mock_client_class.return_value.__aenter__.return_value = client
    return client


class TestBattleTrainingToolsInitialization:
    """Tests for BattleTrainingTools initialization."""

    def test_default_initialization(self):
        """Test default initialization enables all tools."""
        tools = BattleTrainingTools()

        function_names = [func.name for func in tools.functions.values()]

        for name in ALL_FUNCTIONS:
            assert name in function_names
        assert tools.name == "battle_training"

    def test_initialization_with_all_flag(self):
        """Test initialization with all=True enables all tools."""
        tools = BattleTrainingTools(
            enable_get_ladder=False,
            enable_get_bot=False,
            enable_list_ladders=False,
            enable_get_cup_standings=False,
            enable_get_bot_recent_matches=False,
            enable_submit_bot_version=False,
            all=True,
        )

        function_names = [func.name for func in tools.functions.values()]

        for name in ALL_FUNCTIONS:
            assert name in function_names

    def test_initialization_ladder_only(self, ladder_only_tools):
        """Test initialization with only get_ladder enabled."""
        function_names = [func.name for func in ladder_only_tools.functions.values()]

        assert "get_ladder" in function_names
        assert "get_bot" not in function_names
        assert "submit_bot_version" not in function_names

    def test_initialization_no_tools_enabled(self):
        """Test initialization with no tools enabled."""
        tools = BattleTrainingTools(
            enable_get_ladder=False,
            enable_get_bot=False,
            enable_list_ladders=False,
            enable_get_cup_standings=False,
            enable_get_bot_recent_matches=False,
            enable_submit_bot_version=False,
        )

        function_names = [func.name for func in tools.functions.values()]

        for name in ALL_FUNCTIONS:
            assert name not in function_names

    def test_toolkit_name(self):
        """Test that toolkit has correct name."""
        tools = BattleTrainingTools()
        assert tools.name == "battle_training"

    def test_api_key_from_constructor(self):
        """Test API key is stored from the constructor."""
        tools = BattleTrainingTools(api_key="test-key")
        assert tools.api_key == "test-key"

    def test_api_key_defaults_to_none(self, monkeypatch):
        """Test API key is None when neither argument nor env var is set."""
        monkeypatch.delenv("BATTLE_TRAINING_API_KEY", raising=False)
        tools = BattleTrainingTools()
        assert tools.api_key is None

    def test_async_functions_match_sync_functions(self, battle_training_tools):
        """Test every sync tool has an async variant registered under the same name."""
        assert set(battle_training_tools.async_functions) == set(battle_training_tools.functions)

    def test_async_functions_follow_enabled_flags(self, ladder_only_tools):
        """Test async variants follow the same enable flags as sync tools."""
        assert set(ladder_only_tools.async_functions) == {"get_ladder"}


class TestGetLadder:
    """Tests for get_ladder method."""

    def test_get_ladder_default_limit(self, battle_training_tools):
        """Test getting the ladder with the default limit."""
        with patch(
            "agno.tools.battle_training.httpx.get",
            return_value=_mock_response(MOCK_LADDER),
        ):
            result = battle_training_tools.get_ladder()

        data = json.loads(result)
        assert data["total_bots"] == 2
        assert len(data["entries"]) == 2
        assert data["entries"][0]["bot"] == "ephemeral-falconer"
        assert data["entries"][0]["rating"] == 2580
        assert data["entries"][1]["bot"] == "kimmy"

    def test_get_ladder_respects_limit(self, battle_training_tools):
        """Test getting the ladder with a custom limit."""
        with patch(
            "agno.tools.battle_training.httpx.get",
            return_value=_mock_response(MOCK_LADDER),
        ):
            result = battle_training_tools.get_ladder(limit=1)

        data = json.loads(result)
        assert len(data["entries"]) == 1
        assert data["entries"][0]["bot"] == "ephemeral-falconer"

    def test_get_ladder_empty_response(self, battle_training_tools):
        """Test handling of an empty ladder."""
        with patch(
            "agno.tools.battle_training.httpx.get",
            return_value=_mock_response({"updated_at": None, "entries": []}),
        ):
            result = battle_training_tools.get_ladder()

        data = json.loads(result)
        assert data["total_bots"] == 0
        assert data["entries"] == []

    def test_get_ladder_error_handling(self, battle_training_tools):
        """Test error handling when the API call fails."""
        with patch(
            "agno.tools.battle_training.httpx.get",
            side_effect=Exception("Network error"),
        ):
            result = battle_training_tools.get_ladder()

        assert "Error fetching battle.training ladder" in result
        assert "Network error" in result

    @pytest.mark.asyncio
    async def test_aget_ladder_success(self, battle_training_tools):
        """Test the async ladder variant returns the same shaped data."""
        with patch("agno.tools.battle_training.httpx.AsyncClient") as mock_client_class:
            _mock_async_client(mock_client_class, "get", MOCK_LADDER)
            result = await battle_training_tools.aget_ladder(limit=1)

        data = json.loads(result)
        assert len(data["entries"]) == 1
        assert data["entries"][0]["bot"] == "ephemeral-falconer"

    @pytest.mark.asyncio
    async def test_aget_ladder_error_handling(self, battle_training_tools):
        """Test the async ladder variant handles API errors."""
        with patch("agno.tools.battle_training.httpx.AsyncClient") as mock_client_class:
            client = MagicMock()
            client.get = AsyncMock(side_effect=Exception("Network error"))
            mock_client_class.return_value.__aenter__.return_value = client
            result = await battle_training_tools.aget_ladder()

        assert "Error fetching battle.training ladder" in result
        assert "Network error" in result


class TestGetBot:
    """Tests for get_bot method."""

    def test_get_bot_success(self, battle_training_tools):
        """Test successful bot profile retrieval."""
        with patch(
            "agno.tools.battle_training.httpx.get",
            return_value=_mock_response(MOCK_BOT),
        ):
            result = battle_training_tools.get_bot("kimmy")

        profile = json.loads(result)
        assert profile["name"] == "kimmy"
        assert profile["agent"] == "muse"
        assert profile["page_url"] == "https://battle.training/bots/kimmy"
        assert profile["theater"]["rank"] == 214
        assert profile["theater"]["of"] == 362
        assert profile["theater"]["rating"] == 1131
        assert profile["theater"]["version"] == "v10"
        assert len(profile["ladders"]) == 1
        assert profile["ladders"][0]["ladder"] == "promotedby-cup-nov-2026"
        assert profile["active_version"]["label"] == "v10"
        assert profile["active_version"]["health"]["timeouts"] == 0

    def test_get_bot_not_found(self, battle_training_tools):
        """Test handling of a non-existent bot (404)."""
        with patch(
            "agno.tools.battle_training.httpx.get",
            return_value=_mock_response({}, status_code=404),
        ):
            result = battle_training_tools.get_bot("nosuchbot")

        assert "not found" in result
        assert "nosuchbot" in result

    def test_get_bot_no_active_version(self, battle_training_tools):
        """Test a bot with no active version returns null for active_version."""
        payload = dict(MOCK_BOT)
        payload["versions"] = [dict(v, active=False) for v in MOCK_BOT["versions"]]
        with patch(
            "agno.tools.battle_training.httpx.get",
            return_value=_mock_response(payload),
        ):
            result = battle_training_tools.get_bot("kimmy")

        profile = json.loads(result)
        assert profile["active_version"] is None

    def test_get_bot_error_handling(self, battle_training_tools):
        """Test error handling when the API call fails."""
        with patch(
            "agno.tools.battle_training.httpx.get",
            side_effect=Exception("Network error"),
        ):
            result = battle_training_tools.get_bot("kimmy")

        assert "Error getting battle.training bot 'kimmy'" in result
        assert "Network error" in result

    @pytest.mark.asyncio
    async def test_aget_bot_success(self, battle_training_tools):
        """Test the async bot variant returns the same shaped data."""
        with patch("agno.tools.battle_training.httpx.AsyncClient") as mock_client_class:
            _mock_async_client(mock_client_class, "get", MOCK_BOT)
            result = await battle_training_tools.aget_bot("kimmy")

        profile = json.loads(result)
        assert profile["name"] == "kimmy"
        assert profile["theater"]["rank"] == 214

    @pytest.mark.asyncio
    async def test_aget_bot_not_found(self, battle_training_tools):
        """Test the async bot variant handles a 404."""
        with patch("agno.tools.battle_training.httpx.AsyncClient") as mock_client_class:
            _mock_async_client(mock_client_class, "get", {}, status_code=404)
            result = await battle_training_tools.aget_bot("nosuchbot")

        assert "not found" in result
        assert "nosuchbot" in result


class TestListLadders:
    """Tests for list_ladders method."""

    def test_list_ladders_success(self, battle_training_tools):
        """Test successful ladder listing."""
        with patch(
            "agno.tools.battle_training.httpx.get",
            return_value=_mock_response(MOCK_LADDERS),
        ):
            result = battle_training_tools.list_ladders()

        data = json.loads(result)
        assert len(data["ladders"]) == 2
        assert data["ladders"][0]["slug"] == "public"
        assert data["ladders"][0]["prize_total_usd"] is None
        assert data["ladders"][1]["slug"] == "promotedby-cup-nov-2026"
        assert data["ladders"][1]["prize_total_usd"] == 250
        assert data["ladders"][1]["enrolled"] == 266

    def test_list_ladders_error_handling(self, battle_training_tools):
        """Test error handling when the API call fails."""
        with patch(
            "agno.tools.battle_training.httpx.get",
            side_effect=Exception("Network error"),
        ):
            result = battle_training_tools.list_ladders()

        assert "Error listing battle.training ladders" in result
        assert "Network error" in result

    @pytest.mark.asyncio
    async def test_alist_ladders_success(self, battle_training_tools):
        """Test the async ladders variant returns the same shaped data."""
        with patch("agno.tools.battle_training.httpx.AsyncClient") as mock_client_class:
            _mock_async_client(mock_client_class, "get", MOCK_LADDERS)
            result = await battle_training_tools.alist_ladders()

        data = json.loads(result)
        assert len(data["ladders"]) == 2
        assert data["ladders"][1]["slug"] == "promotedby-cup-nov-2026"


class TestGetCupStandings:
    """Tests for get_cup_standings method."""

    def test_get_cup_standings_success(self, battle_training_tools):
        """Test successful cup standings retrieval."""
        with patch(
            "agno.tools.battle_training.httpx.get",
            return_value=_mock_response(MOCK_CUP),
        ):
            result = battle_training_tools.get_cup_standings("promotedby-cup-nov-2026")

        data = json.loads(result)
        assert data["slug"] == "promotedby-cup-nov-2026"
        assert data["name"] == "promotedby.ai November Cup"
        assert data["enrolled"] == 266
        assert len(data["standings"]) == 2
        assert data["standings"][0]["bot"] == "bazookabot-lab"
        assert data["standings"][1]["bot"] == "kimmy"
        assert data["standings"][1]["qualified"] is True

    def test_get_cup_standings_respects_limit(self, battle_training_tools):
        """Test getting cup standings with a custom limit."""
        with patch(
            "agno.tools.battle_training.httpx.get",
            return_value=_mock_response(MOCK_CUP),
        ):
            result = battle_training_tools.get_cup_standings("promotedby-cup-nov-2026", limit=1)

        data = json.loads(result)
        assert len(data["standings"]) == 1

    def test_get_cup_standings_not_found(self, battle_training_tools):
        """Test handling of an unknown ladder slug (404)."""
        with patch(
            "agno.tools.battle_training.httpx.get",
            return_value=_mock_response({}, status_code=404),
        ):
            result = battle_training_tools.get_cup_standings("nosuchcup")

        assert "not found" in result
        assert "nosuchcup" in result

    def test_get_cup_standings_error_handling(self, battle_training_tools):
        """Test error handling when the API call fails."""
        with patch(
            "agno.tools.battle_training.httpx.get",
            side_effect=Exception("Network error"),
        ):
            result = battle_training_tools.get_cup_standings("promotedby-cup-nov-2026")

        assert "Error getting battle.training cup" in result
        assert "Network error" in result

    @pytest.mark.asyncio
    async def test_aget_cup_standings_success(self, battle_training_tools):
        """Test the async cup standings variant returns the same shaped data."""
        with patch("agno.tools.battle_training.httpx.AsyncClient") as mock_client_class:
            _mock_async_client(mock_client_class, "get", MOCK_CUP)
            result = await battle_training_tools.aget_cup_standings("promotedby-cup-nov-2026")

        data = json.loads(result)
        assert data["slug"] == "promotedby-cup-nov-2026"
        assert data["standings"][1]["bot"] == "kimmy"


class TestGetBotRecentMatches:
    """Tests for get_bot_recent_matches method."""

    def test_get_bot_recent_matches_success(self, battle_training_tools):
        """Test successful recent matches retrieval."""
        with patch(
            "agno.tools.battle_training.httpx.get",
            return_value=_mock_response(MOCK_BOT),
        ):
            result = battle_training_tools.get_bot_recent_matches("kimmy")

        data = json.loads(result)
        assert data["bot"] == "kimmy"
        assert len(data["matches"]) == 1
        match = data["matches"][0]
        assert match["id"] == "m_8b05160485df"
        assert match["winner"] == "kimmy"
        assert match["a"]["rating_before"] == 1157
        assert match["a"]["rating_after"] == 1169
        assert match["b"]["bot"] == "opus-4-8"
        assert match["replay_url"].startswith("https://api.battle.training/api/replays/")

    def test_get_bot_recent_matches_respects_limit(self, battle_training_tools):
        """Test getting recent matches with a custom limit."""
        payload = dict(MOCK_BOT)
        payload["matches"] = MOCK_BOT["matches"] * 3
        with patch(
            "agno.tools.battle_training.httpx.get",
            return_value=_mock_response(payload),
        ):
            result = battle_training_tools.get_bot_recent_matches("kimmy", limit=2)

        data = json.loads(result)
        assert len(data["matches"]) == 2

    def test_get_bot_recent_matches_not_found(self, battle_training_tools):
        """Test handling of a non-existent bot (404)."""
        with patch(
            "agno.tools.battle_training.httpx.get",
            return_value=_mock_response({}, status_code=404),
        ):
            result = battle_training_tools.get_bot_recent_matches("nosuchbot")

        assert "not found" in result
        assert "nosuchbot" in result

    def test_get_bot_recent_matches_error_handling(self, battle_training_tools):
        """Test error handling when the API call fails."""
        with patch(
            "agno.tools.battle_training.httpx.get",
            side_effect=Exception("Network error"),
        ):
            result = battle_training_tools.get_bot_recent_matches("kimmy")

        assert "Error getting recent matches for battle.training bot 'kimmy'" in result
        assert "Network error" in result

    @pytest.mark.asyncio
    async def test_aget_bot_recent_matches_success(self, battle_training_tools):
        """Test the async recent matches variant returns the same shaped data."""
        with patch("agno.tools.battle_training.httpx.AsyncClient") as mock_client_class:
            _mock_async_client(mock_client_class, "get", MOCK_BOT)
            result = await battle_training_tools.aget_bot_recent_matches("kimmy")

        data = json.loads(result)
        assert len(data["matches"]) == 1
        assert data["matches"][0]["winner"] == "kimmy"


class TestSubmitBotVersion:
    """Tests for submit_bot_version method."""

    def test_submit_bot_version_success(self, battle_training_tools):
        """Test successful bot version submission."""
        mock_post = MagicMock(return_value=_mock_response(MOCK_SUBMIT_RESPONSE))
        tools = BattleTrainingTools(api_key="test-key")
        with patch("agno.tools.battle_training.httpx.post", mock_post):
            result = tools.submit_bot_version("kimmy", label="v11", source="export default {};", notes="Test version.")

        data = json.loads(result)
        assert data["version_id"] == "ver_0ff8bb95c208"
        assert data["label"] == "v10"
        assert data["active"] is True
        _, kwargs = mock_post.call_args
        assert "Bearer test-key" in kwargs["headers"]["Authorization"]
        assert kwargs["json"]["label"] == "v11"
        assert kwargs["json"]["source"] == "export default {};"
        assert kwargs["json"]["notes"] == "Test version."

    def test_submit_bot_version_per_call_key(self, battle_training_tools):
        """Test the per-call api_key argument overrides the stored key."""
        mock_post = MagicMock(return_value=_mock_response(MOCK_SUBMIT_RESPONSE))
        with patch("agno.tools.battle_training.httpx.post", mock_post):
            result = battle_training_tools.submit_bot_version(
                "kimmy", label="v11", source="export default {};", api_key="call-key"
            )

        data = json.loads(result)
        assert data["version_id"] == "ver_0ff8bb95c208"
        _, kwargs = mock_post.call_args
        assert "Bearer call-key" in kwargs["headers"]["Authorization"]

    def test_submit_bot_version_missing_key(self, monkeypatch):
        """Test submission without any API key returns a helpful message."""
        monkeypatch.delenv("BATTLE_TRAINING_API_KEY", raising=False)
        tools = BattleTrainingTools()
        with patch("agno.tools.battle_training.httpx.post") as mock_post:
            result = tools.submit_bot_version("kimmy", label="v11", source="export default {};")

        assert "Please provide a battle.training API key" in result
        mock_post.assert_not_called()

    def test_submit_bot_version_missing_label_or_source(self):
        """Test submission without a label or source returns a helpful message."""
        tools = BattleTrainingTools(api_key="test-key")
        with patch("agno.tools.battle_training.httpx.post") as mock_post:
            assert "Please provide both a label" in tools.submit_bot_version("kimmy", label="", source="x")
            assert "Please provide both a label" in tools.submit_bot_version("kimmy", label="v11", source="")

        mock_post.assert_not_called()

    def test_submit_bot_version_error_handling(self):
        """Test error handling when the API call fails."""
        tools = BattleTrainingTools(api_key="test-key")
        with patch(
            "agno.tools.battle_training.httpx.post",
            side_effect=Exception("Network error"),
        ):
            result = tools.submit_bot_version("kimmy", label="v11", source="export default {};")

        assert "Error submitting bot version for 'kimmy'" in result
        assert "Network error" in result

    @pytest.mark.asyncio
    async def test_asubmit_bot_version_success(self):
        """Test the async submission variant sends the same request."""
        tools = BattleTrainingTools(api_key="test-key")
        with patch("agno.tools.battle_training.httpx.AsyncClient") as mock_client_class:
            client = _mock_async_client(mock_client_class, "post", MOCK_SUBMIT_RESPONSE)
            result = await tools.asubmit_bot_version(
                "kimmy", label="v11", source="export default {};", notes="Test version."
            )

        data = json.loads(result)
        assert data["version_id"] == "ver_0ff8bb95c208"
        _, kwargs = client.post.call_args
        assert "Bearer test-key" in kwargs["headers"]["Authorization"]
        assert kwargs["json"]["label"] == "v11"

    @pytest.mark.asyncio
    async def test_asubmit_bot_version_missing_key(self, monkeypatch):
        """Test the async submission variant without any API key."""
        monkeypatch.delenv("BATTLE_TRAINING_API_KEY", raising=False)
        tools = BattleTrainingTools()
        with patch("agno.tools.battle_training.httpx.AsyncClient") as mock_client_class:
            client = MagicMock()
            client.post = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = client
            result = await tools.asubmit_bot_version("kimmy", label="v11", source="export default {};")

        assert "Please provide a battle.training API key" in result
        client.post.assert_not_called()


class TestToolkitIntegration:
    """Integration tests for BattleTrainingTools as a Toolkit."""

    def test_tools_list_populated(self, battle_training_tools):
        """Test that tools list is properly populated."""
        assert len(battle_training_tools.tools) == 6

    def test_tools_list_ladder_only(self, ladder_only_tools):
        """Test tools list with only get_ladder enabled."""
        assert len(ladder_only_tools.tools) == 1
        assert ladder_only_tools.tools[0].__name__ == "get_ladder"

    def test_functions_dict_populated(self, battle_training_tools):
        """Test that functions dict is properly populated."""
        function_names = list(battle_training_tools.functions.keys())
        for name in ALL_FUNCTIONS:
            assert name in function_names

    def test_async_functions_dict_populated(self, battle_training_tools):
        """Test that async functions dict mirrors the sync functions dict."""
        assert set(battle_training_tools.async_functions) == set(ALL_FUNCTIONS)
