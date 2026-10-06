import json
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from agno.tools.court_rules import CourtRulesTools

BASE_URL = "https://api.courtrules.app"
HEADERS = {"Authorization": "Bearer test-key", "Accept": "application/json", "User-Agent": "agno"}

COURTS: Dict[str, Any] = {
    "courts": [
        {
            "district_id": "edny",
            "name": "Eastern District of New York",
            "circuit": "2nd Circuit",
            "state": "New York",
            "status": "live",
            "judges_mapped": 30,
            "judges_profiled": 12,
        },
        {
            "district_id": "sdny",
            "name": "Southern District of New York",
            "circuit": "2nd Circuit",
            "state": "New York",
            "status": "live",
            "judges_mapped": 40,
        },
        {
            "district_id": "ca-los-angeles-superior",
            "name": "Superior Court of California, County of Los Angeles",
            "circuit": None,
            "state": "California",
            "status": "live",
            "judges_mapped": 400,
        },
        {
            "district_id": "wyd",
            "name": "District of Wyoming",
            "circuit": "10th Circuit",
            "state": "Wyoming",
            "status": "coming_soon",
            "judges_mapped": 5,
        },
    ],
    "meta": {"total_districts": 4, "districts_with_data": 3, "total_judges_mapped": 475},
}

JUDGES: Dict[str, Any] = {
    "district_id": "edny",
    "judges": [
        {
            "slug": "nicholas-g-garaufis",
            "name": "Nicholas G. Garaufis",
            "has_profile": True,
            "has_rules": True,
            "status": "active",
            "judge_type": "District Judge",
            "bio": "A long biography that a model does not need.",
            "chambers": "Courtroom 4F",
            "profile_url": "https://www.courtrules.app/judges/edny/nicholas-g-garaufis",
        },
        {
            "slug": "carol-bagley-amon",
            "name": "Carol Bagley Amon",
            "has_profile": True,
            "has_rules": True,
            "status": "active",
            "judge_type": "Senior Judge",
            "bio": None,
            "chambers": None,
            "profile_url": None,
        },
    ],
    "meta": {"total": 2, "profiled": 2, "with_rules": 2, "court_level_rules": True},
}

EDNY_RULES: Dict[str, Any] = {
    "judge": {"slug": "nicholas-g-garaufis", "name": "Nicholas G. Garaufis"},
    "rules": {
        "frcp": [{"rule_key": "FormatConstraint:caption", "citation": "FRCP 10(a)", "summary": "Caption required."}],
        "local_rules": [],
        "standing_order": [
            {"category": "PAGE_LIMIT", "summary": "Support briefs limited to 25 pages", "source": "Garaufis SO IV.B"}
        ],
    },
    "meta": {"total_rules": 2},
}


def _extracted_rule(index: int = 1) -> Dict[str, Any]:
    return {
        "rule_id": f"00000000-0000-0000-0000-00000000000{index}",
        "district_id": "il-cook-circuit",
        "judge_slug": "il-cook-reilly-eve-m",
        "source_url": "https://www.cookcountycourt.org/rules.pdf",
        "source_url_key": "cook-rules",
        "document_version_id": "11111111-1111-1111-1111-111111111111",
        "doc_kind": "standing_order",
        "logic_type": "CourtesyCopyRule",
        "workflow_phase": "MOTION_PRACTICE",
        "content": {
            "source_text": "Courtesy copies are required for motions over 15 pages.",
            "summary": "Deliver a courtesy copy of motions over 15 pages.",
            "rule_tags": ["courtesy_copy"],
            "case_type_applicability": [],
            "workflow_phase": "MOTION_PRACTICE",
            "visual_severity": "WARNING",
            "structured_data": {"logic_type": "CourtesyCopyRule", "page_threshold": 15},
            "citation_source": {"page": 3, "section": "II.A"},
        },
    }


STATE_RULES: Dict[str, Any] = {
    "judge": {"slug": "il-cook-reilly-eve-m", "name": "Eve M. Reilly", "status": "active"},
    "district_id": "il-cook-circuit",
    "rules": {"court": [_extracted_rule(1), _extracted_rule(2)], "judge": [_extracted_rule(3)]},
    "meta": {"total_rules": 3, "court_rules": 2, "judge_rules": 1},
}

SEARCH: Dict[str, Any] = {
    "rules": [_extracted_rule(1)],
    "meta": {
        "total": 12,
        "returned": 1,
        "limit": 1,
        "offset": 0,
        "next_offset": 1,
        "district_id": "il-cook-circuit",
        "include_court_rules": True,
    },
}

HOLIDAYS: Dict[str, Any] = {
    "holidays": [
        {
            "district_id": "edny",
            "calendar_year": 2026,
            "holiday_date": "2026-01-01",
            "holiday_name": "New Year's Day",
            "source_url": "https://www.nyed.uscourts.gov/holiday-schedule",
            "last_checked_at": "2026-05-13T12:00:00.000Z",
        }
    ],
    "meta": {"total": 1, "district_id": "edny", "year": 2026, "limit": 100},
}


def _response(payload: Any) -> MagicMock:
    response = MagicMock(spec=httpx.Response)
    response.status_code = 200
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    return response


def _failed_response(status_code: int, payload: Any = None, headers: Any = None) -> MagicMock:
    request = httpx.Request("GET", f"{BASE_URL}/api/v1/courts")
    response = MagicMock(spec=httpx.Response)
    response.status_code = status_code
    response.headers = headers or {}
    if payload is None:
        response.json.side_effect = ValueError("not json")
    else:
        response.json.return_value = payload
    response.raise_for_status.side_effect = httpx.HTTPStatusError("failed", request=request, response=response)
    return response


def _sync_client(mock_client_class: MagicMock, response: MagicMock) -> MagicMock:
    client = mock_client_class.return_value.__enter__.return_value
    client.get.return_value = response
    return client


def _async_client(mock_client_class: MagicMock, response: MagicMock) -> MagicMock:
    client = mock_client_class.return_value.__aenter__.return_value
    client.get = AsyncMock(return_value=response)
    return client


@pytest.fixture
def tools() -> CourtRulesTools:
    return CourtRulesTools(api_key="test-key")


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------


def test_initialization_registers_sync_and_async_tools(tools):
    assert tools.name == "court_rules_tools"
    assert set(tools.functions) == {
        "list_courts",
        "list_judges",
        "get_judge_rules",
        "search_filing_rules",
        "list_court_holidays",
    }
    assert set(tools.async_functions) == set(tools.functions)


def test_initialization_reads_api_key_from_environment():
    with patch.dict("os.environ", {"COURT_RULES_API_KEY": "env-key"}):
        tools = CourtRulesTools()

    assert tools.api_key == "env-key"


def test_explicit_api_key_overrides_environment():
    with patch.dict("os.environ", {"COURT_RULES_API_KEY": "env-key"}):
        tools = CourtRulesTools(api_key="direct-key")

    assert tools.api_key == "direct-key"


def test_base_url_trailing_slash_is_removed():
    tools = CourtRulesTools(api_key="test-key", base_url="https://example.test/")

    assert tools.base_url == "https://example.test"


def test_disabled_tool_is_not_registered():
    tools = CourtRulesTools(api_key="test-key", enable_list_court_holidays=False)

    assert "list_court_holidays" not in tools.functions
    assert "list_court_holidays" not in tools.async_functions
    assert "search_filing_rules" in tools.functions


def test_all_flag_registers_every_tool():
    tools = CourtRulesTools(
        api_key="test-key",
        enable_list_courts=False,
        enable_list_judges=False,
        enable_get_judge_rules=False,
        enable_search_filing_rules=False,
        enable_list_court_holidays=False,
        all=True,
    )

    assert len(tools.functions) == 5
    assert len(tools.async_functions) == 5


def test_instructions_are_added_by_default_and_can_be_overridden():
    default = CourtRulesTools(api_key="test-key")
    custom = CourtRulesTools(api_key="test-key", instructions="Custom guidance.", add_instructions=False)

    assert default.add_instructions is True
    assert "list_courts" in (default.instructions or "")
    assert custom.instructions == "Custom guidance."
    assert custom.add_instructions is False


def test_search_tool_schema_lists_rule_types(tools):
    function = tools.functions["search_filing_rules"]
    function.process_entrypoint()
    properties = function.to_dict()["parameters"]["properties"]

    assert "PageWordLimitRule" in properties["logic_type"]["enum"]


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------


@patch("agno.tools.court_rules.httpx.Client")
def test_list_courts_sends_bearer_token(mock_client_class, tools):
    client = _sync_client(mock_client_class, _response(COURTS))

    tools.list_courts()

    client.get.assert_called_once_with(f"{BASE_URL}/api/v1/courts", headers=HEADERS, params={})


@patch("agno.tools.court_rules.httpx.Client")
def test_list_courts_uses_configured_base_url(mock_client_class):
    client = _sync_client(mock_client_class, _response(COURTS))
    tools = CourtRulesTools(api_key="test-key", base_url="https://example.test/")

    tools.list_courts()

    assert client.get.call_args.args[0] == "https://example.test/api/v1/courts"


@patch("agno.tools.court_rules.httpx.Client")
def test_list_courts_filters_by_words_in_name_state_or_id(mock_client_class, tools):
    _sync_client(mock_client_class, _response(COURTS))

    by_name = json.loads(tools.list_courts(query="eastern district new york"))
    by_id = json.loads(tools.list_courts(query="EDNY"))
    by_state = json.loads(tools.list_courts(query="california"))

    assert [c["district_id"] for c in by_name["courts"]] == ["edny"]
    assert [c["district_id"] for c in by_id["courts"]] == ["edny"]
    assert [c["district_id"] for c in by_state["courts"]] == ["ca-los-angeles-superior"]


@patch("agno.tools.court_rules.httpx.Client")
def test_list_courts_hides_courts_without_rules_unless_asked(mock_client_class, tools):
    _sync_client(mock_client_class, _response(COURTS))

    live_only = json.loads(tools.list_courts(query="wyoming"))
    everything = json.loads(tools.list_courts(query="wyoming", only_live=False))

    assert live_only["courts"] == []
    assert [c["district_id"] for c in everything["courts"]] == ["wyd"]


@patch("agno.tools.court_rules.httpx.Client")
def test_list_courts_pages_results(mock_client_class, tools):
    _sync_client(mock_client_class, _response(COURTS))

    first = json.loads(tools.list_courts(limit=2))
    second = json.loads(tools.list_courts(limit=2, offset=2))

    assert [c["district_id"] for c in first["courts"]] == ["edny", "sdny"]
    assert first["meta"] == {"total_matches": 3, "returned": 2, "offset": 0, "next_offset": 2}
    assert [c["district_id"] for c in second["courts"]] == ["ca-los-angeles-superior"]
    assert second["meta"]["next_offset"] is None


@patch("agno.tools.court_rules.httpx.Client")
def test_list_judges_sends_district_and_drops_bio(mock_client_class, tools):
    client = _sync_client(mock_client_class, _response(JUDGES))

    result = json.loads(tools.list_judges(" edny "))

    client.get.assert_called_once_with(f"{BASE_URL}/api/v1/judges", headers=HEADERS, params={"district_id": "edny"})
    assert result["district_id"] == "edny"
    assert result["meta"] == {"total_in_court": 2, "matched": 2, "returned": 2, "court_level_rules": True}
    assert result["judges"][0] == {
        "slug": "nicholas-g-garaufis",
        "name": "Nicholas G. Garaufis",
        "judge_type": "District Judge",
        "status": "active",
        "has_rules": True,
        "has_profile": True,
        "chambers": "Courtroom 4F",
        "profile_url": "https://www.courtrules.app/judges/edny/nicholas-g-garaufis",
    }
    assert "bio" not in result["judges"][0]
    assert "chambers" not in result["judges"][1]


@patch("agno.tools.court_rules.httpx.Client")
def test_list_judges_filters_by_name_and_limit(mock_client_class, tools):
    _sync_client(mock_client_class, _response(JUDGES))

    by_name = json.loads(tools.list_judges("edny", name="amon"))
    limited = json.loads(tools.list_judges("edny", limit=1))

    assert [j["slug"] for j in by_name["judges"]] == ["carol-bagley-amon"]
    assert len(limited["judges"]) == 1
    assert "note" in limited


@patch("agno.tools.court_rules.httpx.Client")
def test_required_arguments_are_checked_before_any_request(mock_client_class, tools):
    assert json.loads(tools.list_judges("  ")) == {"error": "district_id is required."}
    assert json.loads(tools.get_judge_rules("edny", "")) == {"error": "judge_slug is required."}
    assert json.loads(tools.list_court_holidays("")) == {"error": "district_id is required."}
    mock_client_class.assert_not_called()


@patch("agno.tools.court_rules.httpx.Client")
def test_get_judge_rules_sends_scope_and_motion_type(mock_client_class, tools):
    client = _sync_client(mock_client_class, _response(EDNY_RULES))

    result = json.loads(
        tools.get_judge_rules("edny", "nicholas-g-garaufis", document_scope="brief_support", motion_type="Rule_56")
    )

    client.get.assert_called_once_with(
        f"{BASE_URL}/api/v1/rules",
        headers=HEADERS,
        params={
            "district_id": "edny",
            "judge_slug": "nicholas-g-garaufis",
            "document_scope": "brief_support",
            "motion_type": "Rule_56",
        },
    )
    assert result["judge"]["slug"] == "nicholas-g-garaufis"
    assert result["rules"]["standing_order"][0]["source"] == "Garaufis SO IV.B"
    assert result["rules"]["frcp"] == EDNY_RULES["rules"]["frcp"]
    assert result["meta"] == {"total_rules": 2}
    assert "truncated" not in result


@patch("agno.tools.court_rules.httpx.Client")
def test_get_judge_rules_omits_unset_filters(mock_client_class, tools):
    client = _sync_client(mock_client_class, _response(EDNY_RULES))

    tools.get_judge_rules("edny", "nicholas-g-garaufis")

    assert client.get.call_args.kwargs["params"] == {"district_id": "edny", "judge_slug": "nicholas-g-garaufis"}


@patch("agno.tools.court_rules.httpx.Client")
def test_get_judge_rules_condenses_extracted_rules(mock_client_class, tools):
    _sync_client(mock_client_class, _response(STATE_RULES))

    result = json.loads(tools.get_judge_rules("il-cook-circuit", "il-cook-reilly-eve-m"))

    assert result["district_id"] == "il-cook-circuit"
    assert len(result["rules"]["court"]) == 2
    assert len(result["rules"]["judge"]) == 1
    assert result["rules"]["judge"][0] == {
        "district_id": "il-cook-circuit",
        "judge_slug": "il-cook-reilly-eve-m",
        "logic_type": "CourtesyCopyRule",
        "workflow_phase": "MOTION_PRACTICE",
        "severity": "WARNING",
        "summary": "Deliver a courtesy copy of motions over 15 pages.",
        "source_text": "Courtesy copies are required for motions over 15 pages.",
        "structured_data": {"logic_type": "CourtesyCopyRule", "page_threshold": 15},
        "citation_source": {"page": 3, "section": "II.A"},
        "source_url": "https://www.cookcountycourt.org/rules.pdf",
        "doc_kind": "standing_order",
        "tags": ["courtesy_copy"],
    }
    assert result["meta"] == {"total_rules": 3, "court_rules": 2, "judge_rules": 1}


@patch("agno.tools.court_rules.httpx.Client")
def test_get_judge_rules_cuts_long_groups_and_says_so(mock_client_class):
    _sync_client(mock_client_class, _response(STATE_RULES))
    tools = CourtRulesTools(api_key="test-key", max_rules=1)

    result = json.loads(tools.get_judge_rules("il-cook-circuit", "il-cook-reilly-eve-m"))

    assert len(result["rules"]["court"]) == 1
    assert len(result["rules"]["judge"]) == 1
    assert result["truncated"] == {"court": {"returned": 1, "total": 2}}
    assert "search_filing_rules" in result["note"]


@patch("agno.tools.court_rules.httpx.Client")
def test_search_filing_rules_maps_parameters(mock_client_class, tools):
    client = _sync_client(mock_client_class, _response(SEARCH))

    result = json.loads(
        tools.search_filing_rules(
            query=" courtesy copies ",
            district_id="il-cook-circuit",
            judge_slug="court",
            logic_type="CourtesyCopyRule",
            limit=5,
            offset=10,
        )
    )

    client.get.assert_called_once_with(
        f"{BASE_URL}/api/v1/extracted-rules",
        headers=HEADERS,
        params={
            "q": "courtesy copies",
            "district_id": "il-cook-circuit",
            "judge_slug": "court",
            "logic_type": "CourtesyCopyRule",
            "limit": 5,
            "offset": 10,
        },
    )
    assert result["meta"]["total"] == 12
    assert result["meta"]["next_offset"] == 1
    assert result["rules"][0]["summary"] == "Deliver a courtesy copy of motions over 15 pages."
    assert "rule_id" not in result["rules"][0]
    assert "document_version_id" not in result["rules"][0]


@patch("agno.tools.court_rules.httpx.Client")
def test_search_filing_rules_clamps_limit_and_offset(mock_client_class, tools):
    client = _sync_client(mock_client_class, _response(SEARCH))

    tools.search_filing_rules(query="fees", limit=500, offset=-5)
    assert client.get.call_args.kwargs["params"] == {"q": "fees", "limit": 50, "offset": 0}

    tools.search_filing_rules(query="fees", limit=0)
    assert client.get.call_args.kwargs["params"]["limit"] == 1


@patch("agno.tools.court_rules.httpx.Client")
def test_search_filing_rules_needs_something_to_search_for(mock_client_class, tools):
    blank = json.loads(tools.search_filing_rules(query="   ", district_id=" "))
    nothing = json.loads(tools.search_filing_rules())

    assert blank == nothing == {"error": "Provide a query, district_id, judge_slug or logic_type to search for."}
    mock_client_class.assert_not_called()


@patch("agno.tools.court_rules.httpx.Client")
def test_search_filing_rules_rejects_a_query_over_200_characters(mock_client_class, tools):
    result = json.loads(tools.search_filing_rules(query="x" * 201))

    assert result == {"error": "query must be 200 characters or fewer."}
    mock_client_class.assert_not_called()


@patch("agno.tools.court_rules.httpx.Client")
def test_list_court_holidays_sends_district_and_year(mock_client_class, tools):
    client = _sync_client(mock_client_class, _response(HOLIDAYS))

    result = json.loads(tools.list_court_holidays("edny", year=2026))

    client.get.assert_called_once_with(
        f"{BASE_URL}/api/v1/holidays", headers=HEADERS, params={"district_id": "edny", "year": 2026}
    )
    assert result["holidays"][0]["holiday_name"] == "New Year's Day"
    assert result["holidays"][0]["source_url"] == "https://www.nyed.uscourts.gov/holiday-schedule"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


@patch("agno.tools.court_rules.httpx.Client")
def test_missing_api_key_returns_actionable_error_without_a_request(mock_client_class):
    with patch.dict("os.environ", {}, clear=True):
        tools = CourtRulesTools()

    result = json.loads(tools.list_courts())

    assert "COURT_RULES_API_KEY" in result["error"]
    assert result["suggestion"] == "Get a key at https://console.courtrules.app."
    mock_client_class.return_value.__enter__.return_value.get.assert_not_called()


@patch("agno.tools.court_rules.httpx.Client")
def test_http_error_keeps_the_api_error_and_suggestion(mock_client_class, tools):
    body = {
        "error": "Compliance checks are not available for this court yet.",
        "suggestion": "Read the judge's rules with GET /api/v1/rules.",
        "docs_url": "https://docs.courtrules.app/api-reference/extracted-rules",
    }
    _sync_client(mock_client_class, _failed_response(422, body))

    result = json.loads(tools.search_filing_rules(query="fees"))

    assert result == {
        "error": "Compliance checks are not available for this court yet.",
        "status_code": 422,
        "suggestion": "Read the judge's rules with GET /api/v1/rules.",
        "docs_url": "https://docs.courtrules.app/api-reference/extracted-rules",
    }


@patch("agno.tools.court_rules.httpx.Client")
def test_validation_error_details_are_returned(mock_client_class, tools):
    details = [{"path": "q", "message": "Too long"}]
    _sync_client(mock_client_class, _failed_response(400, {"error": "Invalid request", "details": details}))

    result = json.loads(tools.search_filing_rules(query="fees"))

    assert result["error"] == "Invalid request"
    assert result["details"] == details


@patch("agno.tools.court_rules.httpx.Client")
def test_unauthorized_response_points_to_the_console(mock_client_class, tools):
    _sync_client(mock_client_class, _failed_response(403, {"error": "Invalid API key"}))

    result = json.loads(tools.list_courts())

    assert result["error"] == "Invalid API key"
    assert result["status_code"] == 403
    assert "console.courtrules.app" in result["suggestion"]


@patch("agno.tools.court_rules.httpx.Client")
def test_rate_limit_response_reports_retry_after(mock_client_class, tools):
    _sync_client(mock_client_class, _failed_response(429, {"error": "Rate limit exceeded"}, {"Retry-After": "12"}))

    result = json.loads(tools.list_courts())

    assert result["status_code"] == 429
    assert result["retry_after"] == "12"


@patch("agno.tools.court_rules.httpx.Client")
def test_error_without_a_json_body_still_reports_the_status(mock_client_class, tools):
    _sync_client(mock_client_class, _failed_response(502))

    result = json.loads(tools.list_courts())

    assert result == {"error": "Court Rules API request failed with status 502", "status_code": 502}


@patch("agno.tools.court_rules.httpx.Client")
def test_network_error_is_returned_not_raised(mock_client_class, tools):
    client = mock_client_class.return_value.__enter__.return_value
    client.get.side_effect = httpx.ConnectError("connection refused")

    result = json.loads(tools.list_courts())

    assert result == {"error": "Court Rules API request failed", "detail": "connection refused"}


@patch("agno.tools.court_rules.httpx.Client")
def test_success_response_that_is_not_json_is_an_error(mock_client_class, tools):
    response = _response(None)
    response.json.side_effect = ValueError("not json")
    _sync_client(mock_client_class, response)

    result = json.loads(tools.list_courts())

    assert result == {"error": "Court Rules API returned a response that is not valid JSON."}


# ---------------------------------------------------------------------------
# Async
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("agno.tools.court_rules.httpx.AsyncClient")
async def test_async_list_courts_uses_the_same_request(mock_client_class, tools):
    client = _async_client(mock_client_class, _response(COURTS))

    result = json.loads(await tools.alist_courts(query="eastern district new york"))

    client.get.assert_awaited_once_with(f"{BASE_URL}/api/v1/courts", headers=HEADERS, params={})
    assert [c["district_id"] for c in result["courts"]] == ["edny"]


@pytest.mark.asyncio
@patch("agno.tools.court_rules.httpx.AsyncClient")
async def test_async_search_filing_rules_maps_parameters(mock_client_class, tools):
    client = _async_client(mock_client_class, _response(SEARCH))

    result = json.loads(await tools.asearch_filing_rules(query="courtesy copies", district_id="il-cook-circuit"))

    client.get.assert_awaited_once_with(
        f"{BASE_URL}/api/v1/extracted-rules",
        headers=HEADERS,
        params={"q": "courtesy copies", "district_id": "il-cook-circuit", "limit": 10, "offset": 0},
    )
    assert result["rules"][0]["logic_type"] == "CourtesyCopyRule"


@pytest.mark.asyncio
@patch("agno.tools.court_rules.httpx.AsyncClient")
async def test_async_error_paths(mock_client_class, tools):
    client = _async_client(mock_client_class, _failed_response(422, {"error": "Too broad", "suggestion": "Narrow it."}))

    api_error = json.loads(await tools.asearch_filing_rules(query="fees"))
    client.get = AsyncMock(side_effect=httpx.ReadTimeout("slow"))
    network_error = json.loads(await tools.alist_courts())
    missing_argument = json.loads(await tools.alist_judges(""))

    assert api_error == {"error": "Too broad", "status_code": 422, "suggestion": "Narrow it."}
    assert network_error == {"error": "Court Rules API request failed", "detail": "slow"}
    assert missing_argument == {"error": "district_id is required."}


@pytest.mark.asyncio
@patch("agno.tools.court_rules.httpx.AsyncClient")
async def test_async_missing_api_key_returns_error_without_a_request(mock_client_class):
    with patch.dict("os.environ", {}, clear=True):
        tools = CourtRulesTools()

    result = json.loads(await tools.alist_court_holidays("edny"))

    assert "COURT_RULES_API_KEY" in result["error"]
    mock_client_class.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method, args, payload",
    [
        ("list_courts", {"query": "new york"}, COURTS),
        ("list_judges", {"district_id": "edny", "name": "amon"}, JUDGES),
        ("get_judge_rules", {"district_id": "il-cook-circuit", "judge_slug": "il-cook-reilly-eve-m"}, STATE_RULES),
        ("search_filing_rules", {"query": "courtesy", "district_id": "il-cook-circuit"}, SEARCH),
        ("list_court_holidays", {"district_id": "edny", "year": 2026}, HOLIDAYS),
    ],
)
async def test_async_tools_match_sync_tools(method, args, payload, tools):
    with patch("agno.tools.court_rules.httpx.Client") as sync_client_class:
        _sync_client(sync_client_class, _response(payload))
        expected = getattr(tools, method)(**args)

    with patch("agno.tools.court_rules.httpx.AsyncClient") as async_client_class:
        _async_client(async_client_class, _response(payload))
        actual = await getattr(tools, f"a{method}")(**args)

    assert actual == expected
    assert "error" not in json.loads(actual)
