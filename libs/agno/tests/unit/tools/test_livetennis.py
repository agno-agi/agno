"""Unit tests for LiveTennisTools"""

import json
from unittest.mock import MagicMock, patch

import httpx
import pytest

from agno.tools.livetennis import LiveTennisTools

BASE_URL = "https://api.livetennisapi.com/api/public/v1"


def make_response(json_data, status_code=200):
    """Build a MagicMock httpx response with the given JSON body and status."""
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = json_data
    if status_code >= 400:
        response.raise_for_status.side_effect = httpx.HTTPStatusError(
            f"HTTP {status_code}", request=MagicMock(), response=response
        )
    else:
        response.raise_for_status.return_value = None
    return response


@pytest.fixture
def tools():
    """Create a LiveTennisTools instance with a test API key."""
    return LiveTennisTools(api_key="test-api-key")


class TestLiveTennisToolsInitialization:
    """Tests for LiveTennisTools initialization"""

    def test_default_initialization(self, tools):
        """Default initialization registers all six tools"""
        assert tools.name == "livetennis_tools"
        assert tools.api_key == "test-api-key"
        assert set(tools.functions.keys()) == {
            "get_live_matches",
            "get_match",
            "get_match_score",
            "search_players",
            "get_player",
            "get_upcoming_fixtures",
        }

    def test_api_key_from_env(self, monkeypatch):
        """The API key is read from LIVETENNISAPI_KEY when not passed explicitly"""
        monkeypatch.setenv("LIVETENNISAPI_KEY", "env-key")
        tools = LiveTennisTools()
        assert tools.api_key == "env-key"

    def test_missing_api_key_raises(self, monkeypatch):
        """A missing API key fails fast with a pointer to the env var"""
        monkeypatch.delenv("LIVETENNISAPI_KEY", raising=False)
        with pytest.raises(ValueError, match="LIVETENNISAPI_KEY"):
            LiveTennisTools()

    def test_disabled_flag_unregisters_tool(self):
        """A disabled enable_* flag keeps that function out of the registry"""
        tools = LiveTennisTools(api_key="k", enable_get_live_matches=False)
        assert "get_live_matches" not in tools.functions
        assert "get_match" in tools.functions

    def test_all_flag_overrides_individual_flags(self):
        """all=True registers every tool regardless of the individual enable_* flags"""
        tools = LiveTennisTools(
            api_key="k",
            enable_get_live_matches=False,
            enable_get_match=False,
            enable_get_match_score=False,
            enable_search_players=False,
            enable_get_player=False,
            enable_get_upcoming_fixtures=False,
            all=True,
        )
        assert len(tools.functions) == 6

    def test_base_url_trailing_slash_normalized(self):
        """A trailing slash on base_url does not produce double slashes in request URLs"""
        tools = LiveTennisTools(api_key="k", base_url=f"{BASE_URL}/")
        assert tools.base_url == BASE_URL


class TestGetLiveMatches:
    """Tests for get_live_matches"""

    def test_success(self, tools):
        """get_live_matches hits /matches with status=live and returns the payload"""
        matches = [{"id": "m1", "players": ["A", "B"]}]
        with patch("agno.tools.livetennis.httpx.get", return_value=make_response(matches)) as mock_get:
            result = tools.get_live_matches()

        mock_get.assert_called_once_with(
            f"{BASE_URL}/matches",
            params={"status": "live", "limit": 20},
            headers={"x-api-key": "test-api-key"},
            timeout=30,
        )
        assert json.loads(result) == matches

    def test_tour_filter_normalized(self, tools):
        """The tour filter is stripped, lowercased, and forwarded"""
        with patch("agno.tools.livetennis.httpx.get", return_value=make_response([])) as mock_get:
            tools.get_live_matches(tour=" ATP ", limit=5)

        assert mock_get.call_args.kwargs["params"] == {"status": "live", "limit": 5, "tour": "atp"}

    def test_blank_tour_omitted(self, tools):
        """A blank tour string is not sent as a filter"""
        with patch("agno.tools.livetennis.httpx.get", return_value=make_response([])) as mock_get:
            tools.get_live_matches(tour="  ")

        assert "tour" not in mock_get.call_args.kwargs["params"]

    def test_limit_clamped_to_minimum(self, tools):
        """A non-positive limit is clamped to 1"""
        with patch("agno.tools.livetennis.httpx.get", return_value=make_response([])) as mock_get:
            tools.get_live_matches(limit=0)

        assert mock_get.call_args.kwargs["params"]["limit"] == 1

    def test_unauthorized(self, tools):
        """A 401 maps to a clear unauthorized error with the free-key URL"""
        response = make_response({"error": "unauthorized"}, status_code=401)
        with patch("agno.tools.livetennis.httpx.get", return_value=response):
            result = tools.get_live_matches()

        payload = json.loads(result)
        assert "Unauthorized" in payload["error"]
        assert "livetennisapi.com/subscribe/free" in payload["error"]

    def test_http_error(self, tools):
        """A non-401 HTTP error surfaces the status code"""
        response = make_response({"error": "boom"}, status_code=500)
        response.text = "internal error"
        with patch("agno.tools.livetennis.httpx.get", return_value=response):
            result = tools.get_live_matches()

        assert "HTTP 500" in json.loads(result)["error"]

    def test_network_error(self, tools):
        """A transport-level failure returns an error payload instead of raising"""
        with patch("agno.tools.livetennis.httpx.get", side_effect=httpx.ConnectError("connection refused")):
            result = tools.get_live_matches()

        assert "connection refused" in json.loads(result)["error"]


class TestGetMatch:
    """Tests for get_match"""

    def test_success(self, tools):
        """get_match hits /matches/{id} and returns the payload"""
        match = {"id": "m1", "tournament": "Wimbledon"}
        with patch("agno.tools.livetennis.httpx.get", return_value=make_response(match)) as mock_get:
            result = tools.get_match("m1")

        mock_get.assert_called_once_with(
            f"{BASE_URL}/matches/m1",
            params=None,
            headers={"x-api-key": "test-api-key"},
            timeout=30,
        )
        assert json.loads(result) == match

    def test_empty_match_id(self, tools):
        """An empty match_id fails closed and never calls the API"""
        with patch("agno.tools.livetennis.httpx.get") as mock_get:
            result = tools.get_match("  ")

        assert "match_id" in json.loads(result)["error"]
        mock_get.assert_not_called()


class TestGetMatchScore:
    """Tests for get_match_score"""

    def test_success(self, tools):
        """get_match_score hits /matches/{id}/score and returns the payload"""
        score = {"sets": [[6, 4], [3, 3]], "serving": "home"}
        with patch("agno.tools.livetennis.httpx.get", return_value=make_response(score)) as mock_get:
            result = tools.get_match_score("m1")

        assert mock_get.call_args.args[0] == f"{BASE_URL}/matches/m1/score"
        assert json.loads(result) == score

    def test_empty_match_id(self, tools):
        """An empty match_id fails closed and never calls the API"""
        with patch("agno.tools.livetennis.httpx.get") as mock_get:
            result = tools.get_match_score("")

        assert "match_id" in json.loads(result)["error"]
        mock_get.assert_not_called()


class TestSearchPlayers:
    """Tests for search_players"""

    def test_success(self, tools):
        """search_players hits /players with search + limit and returns the payload"""
        players = [{"id": "p1", "name": "Carlos Alcaraz"}]
        with patch("agno.tools.livetennis.httpx.get", return_value=make_response(players)) as mock_get:
            result = tools.search_players("Alcaraz")

        mock_get.assert_called_once_with(
            f"{BASE_URL}/players",
            params={"search": "Alcaraz", "limit": 10},
            headers={"x-api-key": "test-api-key"},
            timeout=30,
        )
        assert json.loads(result) == players

    def test_query_stripped(self, tools):
        """Whitespace around the query is stripped before it is sent"""
        with patch("agno.tools.livetennis.httpx.get", return_value=make_response([])) as mock_get:
            tools.search_players("  Sinner  ", limit=3)

        assert mock_get.call_args.kwargs["params"] == {"search": "Sinner", "limit": 3}

    def test_empty_query(self, tools):
        """An empty query fails closed and never calls the API"""
        with patch("agno.tools.livetennis.httpx.get") as mock_get:
            result = tools.search_players("   ")

        assert "query" in json.loads(result)["error"]
        mock_get.assert_not_called()


class TestGetPlayer:
    """Tests for get_player"""

    def test_success(self, tools):
        """get_player hits /players/{id} and returns the payload"""
        player = {"id": "p1", "name": "Iga Swiatek", "tour": "wta"}
        with patch("agno.tools.livetennis.httpx.get", return_value=make_response(player)) as mock_get:
            result = tools.get_player("p1")

        assert mock_get.call_args.args[0] == f"{BASE_URL}/players/p1"
        assert json.loads(result) == player

    def test_empty_player_id(self, tools):
        """An empty player_id fails closed and never calls the API"""
        with patch("agno.tools.livetennis.httpx.get") as mock_get:
            result = tools.get_player("")

        assert "player_id" in json.loads(result)["error"]
        mock_get.assert_not_called()


class TestGetUpcomingFixtures:
    """Tests for get_upcoming_fixtures"""

    def test_success(self, tools):
        """get_upcoming_fixtures hits /fixtures with the limit and returns the payload"""
        fixtures = [{"id": "f1", "start_time": "2026-07-25T13:00:00Z"}]
        with patch("agno.tools.livetennis.httpx.get", return_value=make_response(fixtures)) as mock_get:
            result = tools.get_upcoming_fixtures(limit=5)

        mock_get.assert_called_once_with(
            f"{BASE_URL}/fixtures",
            params={"limit": 5},
            headers={"x-api-key": "test-api-key"},
            timeout=30,
        )
        assert json.loads(result) == fixtures

    def test_limit_clamped_to_minimum(self, tools):
        """A non-positive limit is clamped to 1"""
        with patch("agno.tools.livetennis.httpx.get", return_value=make_response([])) as mock_get:
            tools.get_upcoming_fixtures(limit=-3)

        assert mock_get.call_args.kwargs["params"]["limit"] == 1


class TestTimeoutForwarding:
    """The toolkit-level timeout is forwarded to each HTTP request"""

    def test_custom_timeout(self):
        tools = LiveTennisTools(api_key="k", timeout=5)
        with patch("agno.tools.livetennis.httpx.get", return_value=make_response([])) as mock_get:
            tools.get_upcoming_fixtures()

        assert mock_get.call_args.kwargs["timeout"] == 5
