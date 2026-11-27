"""Unit tests for DealportTools sync and async toolkit methods."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest

from agno.tools.dealport import DealportTools

TEST_UUID = "123e4567-e89b-12d3-a456-426614174000"


@pytest.fixture
def local_dealport_server():
    recorded: list[dict[str, Any]] = []
    response_state: dict[str, Any] = {"status": 200, "body": {"ok": True}, "headers": {}}

    class Handler(BaseHTTPRequestHandler):
        def _handle(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            raw_body = self.rfile.read(length) if length > 0 else b""
            parsed_url = urlsplit(self.path)
            recorded.append(
                {
                    "method": self.command,
                    "path": parsed_url.path,
                    "query": parse_qs(parsed_url.query),
                    "headers": dict(self.headers),
                    "body": json.loads(raw_body.decode("utf-8")) if raw_body else None,
                }
            )
            self.send_response(response_state["status"])
            for k, v in response_state["headers"].items():
                self.send_header(k, v)
            self.send_header("Content-Type", "application/json")
            payload = json.dumps(response_state["body"]).encode("utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self) -> None:
            self._handle()

        def do_POST(self) -> None:
            self._handle()

        def log_message(self, format: str, *args: Any) -> None:
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}/api/v1"
    try:
        yield base_url, recorded, response_state
    finally:
        server.shutdown()
        server.server_close()


def test_init_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEALPORT_API_KEY", raising=False)
    with pytest.raises(ValueError, match="DEALPORT_API_KEY"):
        DealportTools()
    with pytest.raises(ValueError, match="HTTPS"):
        DealportTools(api_key="dp_live_test", base_url="http://example.com/api/v1")
    with pytest.raises(ValueError, match="timeout"):
        DealportTools(api_key="dp_live_test", timeout=0)

    toolkit = DealportTools(api_key="dp_live_test")
    expected_names = {
        "preview_companies",
        "search_companies",
        "search_buildings",
        "get_record",
        "find_owner",
        "find_contact",
        "match_company_list",
        "get_balance",
    }
    assert set(toolkit.functions.keys()) == expected_names
    assert set(toolkit.async_functions.keys()) == expected_names


def test_sync_tools_lifecycle(local_dealport_server: Any) -> None:
    base_url, recorded, state = local_dealport_server
    tools = DealportTools(api_key="dp_live_secret_token", base_url=base_url)

    state["body"] = {"total": 128, "sample_companies": [{"id": TEST_UUID, "name": "Acme HVAC LLC"}]}
    preview = json.loads(tools.preview_companies(state="oh", naics="238220, 332710", independent=True))
    assert preview["total"] == 128
    assert recorded[-1]["method"] == "POST"
    assert recorded[-1]["path"] == "/api/v1/companies/preview"
    assert recorded[-1]["body"] == {"state": "OH", "naics": ["238220", "332710"], "independent": True}
    assert recorded[-1]["headers"]["Authorization"] == "Bearer dp_live_secret_token"

    state["body"] = {"companies": [{"id": TEST_UUID}]}
    search = json.loads(tools.search_companies(state="oh", min_employees=10, limit=5))
    assert search["companies"][0]["id"] == TEST_UUID
    assert recorded[-1]["method"] == "GET"
    assert recorded[-1]["query"]["state"] == ["OH"]
    assert recorded[-1]["query"]["limit"] == ["5"]

    state["body"] = {"buildings": [{"bbl": "1001230045"}]}
    bldgs = json.loads(tools.search_buildings(borough="mn", min_units=20, loan_holder="cmbs"))
    assert bldgs["buildings"][0]["bbl"] == "1001230045"
    assert recorded[-1]["query"]["borough"] == ["MN"]

    state["body"] = {"id": TEST_UUID, "name": "Acme HVAC LLC"}
    rec = json.loads(tools.get_record(TEST_UUID))
    assert rec["name"] == "Acme HVAC LLC"
    assert recorded[-1]["path"] == f"/api/v1/records/{TEST_UUID}"

    state["body"] = {"owner_name": "Jane Doe"}
    owner = json.loads(tools.find_owner(TEST_UUID, person="Jane Doe"))
    assert owner["owner_name"] == "Jane Doe"
    assert recorded[-1]["path"] == "/api/v1/owners"

    state["body"] = {"contacts": [{"name": "John Operations"}]}
    contact = json.loads(tools.find_contact(TEST_UUID))
    assert contact["contacts"][0]["name"] == "John Operations"
    assert recorded[-1]["path"] == "/api/v1/contacts"

    state["body"] = {"matches": [{"company_id": TEST_UUID}]}
    matched = json.loads(
        tools.match_company_list(items_json=json.dumps([{"name": "Acme HVAC LLC", "domain": "acmehvac.com"}]))
    )
    assert matched["matches"][0]["company_id"] == TEST_UUID
    assert recorded[-1]["body"]["watch"] is False

    state["body"] = {"balance_usd": 5.0}
    bal = json.loads(tools.get_balance())
    assert bal["balance_usd"] == 5.0
    assert recorded[-1]["path"] == "/api/v1/balance"


@pytest.mark.asyncio
async def test_async_tools_and_error_redaction(local_dealport_server: Any) -> None:
    base_url, recorded, state = local_dealport_server
    tools = DealportTools(api_key="dp_live_top_secret", base_url=base_url)

    state["body"] = {"total": 42}
    preview = json.loads(await tools.apreview_companies(state="tx"))
    assert preview["total"] == 42
    assert recorded[-1]["body"] == {"state": "TX"}

    state["body"] = {"balance_usd": 4.91}
    balance = json.loads(await tools.aget_balance())
    assert balance["balance_usd"] == 4.91

    assert "error" in json.loads(await tools.asearch_companies(state="TEXAS"))
    assert "error" in json.loads(await tools.asearch_buildings(borough="INVALID"))
    assert "error" in json.loads(await tools.aget_record("../balance"))
    assert "error" in json.loads(await tools.afind_owner("not-a-uuid"))
    assert "error" in json.loads(await tools.afind_contact("not-a-uuid"))
    assert "error" in json.loads(await tools.amatch_company_list())

    state["status"] = 401
    state["body"] = {"error": "Invalid token dp_live_top_secret"}
    err_resp = await tools.aget_balance()
    assert "dp_live_top_secret" not in err_resp
    assert "error" in json.loads(err_resp)
