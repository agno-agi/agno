import json

import pytest

from agno.models.message import Message
from agno.models.openai.chat import OpenAIChat
from agno.models.openai.responses import OpenAIResponses
from agno.utils.models.cohere import format_messages as cohere_format
from agno.utils.models.tool_messages import normalize_tool_result_messages

try:
    from agno.models.deepseek.deepseek import DeepSeek

    HAS_DEEPSEEK = True
except ImportError:
    HAS_DEEPSEEK = False

requires_deepseek = pytest.mark.skipif(not HAS_DEEPSEEK, reason="deepseek model not importable")


# ---------------------------------------------------------------------------
# Helpers: build realistic message histories
# ---------------------------------------------------------------------------


def _user(content: str) -> Message:
    return Message(role="user", content=content)


def _assistant(content: str, tool_calls=None) -> Message:
    return Message(role="assistant", content=content, tool_calls=tool_calls)


def _assistant_with_calls(call_ids, names):
    return Message(
        role="assistant",
        content=None,
        tool_calls=[
            {
                "id": cid,
                "type": "function",
                "function": {"name": name, "arguments": json.dumps({"query": "test"})},
            }
            for cid, name in zip(call_ids, names)
        ],
    )


def _tool_canonical(tool_call_id, content, tool_name="func"):
    return Message(role="tool", content=content, tool_call_id=tool_call_id, tool_name=tool_name)


def _tool_gemini_combined(tool_calls_data):
    return Message(
        role="tool",
        content=[tc[2] for tc in tool_calls_data],
        tool_name=", ".join(tc[1] for tc in tool_calls_data),
        tool_calls=[{"tool_call_id": tc[0], "tool_name": tc[1], "content": tc[2]} for tc in tool_calls_data],
    )


def _db_round_trip(messages):
    return [Message.from_dict(m.to_dict()) for m in messages]


def _verify_openai_chat_valid(formatted):
    for msg in formatted:
        assert isinstance(msg, dict)
        assert "role" in msg
        if msg["role"] == "tool":
            assert "tool_call_id" in msg, f"tool message missing tool_call_id: {msg}"
            assert "content" in msg, f"tool message missing content: {msg}"
            assert isinstance(msg["content"], str), f"tool content not string: {type(msg['content'])}"


def _verify_openai_responses_valid(formatted):
    for item in formatted:
        assert isinstance(item, dict)
        if item.get("type") == "function_call_output":
            assert "call_id" in item, f"function_call_output missing call_id: {item}"
            assert "output" in item, f"function_call_output missing output: {item}"


# ===========================================================================
# Level 1: Single tool call session → switch provider
# ===========================================================================


class TestLevel1SingleToolSession:
    def _single_tool_session(self):
        return [
            _user("What's the stock price of TSLA?"),
            _assistant_with_calls(["call_1"], ["get_stock_price"]),
            _tool_canonical("call_1", '{"price": 250.42, "currency": "USD"}', "get_stock_price"),
            _assistant("TSLA is currently trading at $250.42 USD."),
        ]

    def test_format_for_openai_chat(self):
        session = self._single_tool_session()
        model = OpenAIChat(id="gpt-4o-mini")
        formatted = model._format_messages(session)
        _verify_openai_chat_valid(formatted)
        tool_msgs = [m for m in formatted if m["role"] == "tool"]
        assert len(tool_msgs) == 1
        assert tool_msgs[0]["tool_call_id"] == "call_1"

    def test_format_for_openai_responses(self):
        session = self._single_tool_session()
        model = OpenAIResponses(id="gpt-4o-mini")
        formatted = model._format_messages(session)
        _verify_openai_responses_valid(formatted)
        outputs = [m for m in formatted if m.get("type") == "function_call_output"]
        assert len(outputs) == 1
        assert outputs[0]["call_id"] == "call_1"

    def test_db_round_trip_then_openai_chat(self):
        session = self._single_tool_session()
        restored = _db_round_trip(session)
        model = OpenAIChat(id="gpt-4o-mini")
        formatted = model._format_messages(restored)
        _verify_openai_chat_valid(formatted)
        tool_msgs = [m for m in formatted if m["role"] == "tool"]
        assert len(tool_msgs) == 1

    def test_db_round_trip_then_openai_responses(self):
        session = self._single_tool_session()
        restored = _db_round_trip(session)
        model = OpenAIResponses(id="gpt-4o-mini")
        formatted = model._format_messages(restored)
        _verify_openai_responses_valid(formatted)


# ===========================================================================
# Level 2: Multi-tool parallel session → switch provider
# ===========================================================================


class TestLevel2MultiToolSession:
    def _multi_tool_session(self):
        return [
            _user("Compare TSLA and AAPL stock prices"),
            _assistant_with_calls(["call_1", "call_2"], ["get_stock_price", "get_stock_price"]),
            _tool_canonical("call_1", '{"price": 250.42, "ticker": "TSLA"}', "get_stock_price"),
            _tool_canonical("call_2", '{"price": 178.50, "ticker": "AAPL"}', "get_stock_price"),
            _assistant("TSLA is $250.42 and AAPL is $178.50."),
        ]

    def _gemini_format_multi_tool(self):
        return [
            _user("Compare TSLA and AAPL stock prices"),
            _assistant_with_calls(["call_1", "call_2"], ["get_stock_price", "get_stock_price"]),
            _tool_gemini_combined(
                [
                    ("call_1", "get_stock_price", '{"price": 250.42, "ticker": "TSLA"}'),
                    ("call_2", "get_stock_price", '{"price": 178.50, "ticker": "AAPL"}'),
                ]
            ),
            _assistant("TSLA is $250.42 and AAPL is $178.50."),
        ]

    def test_canonical_format_for_openai_chat(self):
        session = self._multi_tool_session()
        model = OpenAIChat(id="gpt-4o-mini")
        formatted = model._format_messages(session)
        _verify_openai_chat_valid(formatted)
        tool_msgs = [m for m in formatted if m["role"] == "tool"]
        assert len(tool_msgs) == 2

    def test_gemini_combined_splits_for_openai_chat(self):
        session = self._gemini_format_multi_tool()
        model = OpenAIChat(id="gpt-4o-mini")
        formatted = model._format_messages(session)
        _verify_openai_chat_valid(formatted)
        tool_msgs = [m for m in formatted if m["role"] == "tool"]
        assert len(tool_msgs) == 2
        assert {m["tool_call_id"] for m in tool_msgs} == {"call_1", "call_2"}

    def test_gemini_combined_splits_for_openai_responses(self):
        session = self._gemini_format_multi_tool()
        model = OpenAIResponses(id="gpt-4o-mini")
        formatted = model._format_messages(session)
        _verify_openai_responses_valid(formatted)
        outputs = [m for m in formatted if m.get("type") == "function_call_output"]
        assert len(outputs) == 2
        assert {o["call_id"] for o in outputs} == {"call_1", "call_2"}

    def test_gemini_combined_db_round_trip_then_split(self):
        session = self._gemini_format_multi_tool()
        restored = _db_round_trip(session)

        assert isinstance(restored[2].content, list)
        assert restored[2].tool_call_id is None

        model = OpenAIChat(id="gpt-4o-mini")
        formatted = model._format_messages(restored)
        _verify_openai_chat_valid(formatted)
        tool_msgs = [m for m in formatted if m["role"] == "tool"]
        assert len(tool_msgs) == 2

    def test_cohere_format_after_gemini_combined(self):
        session = self._gemini_format_multi_tool()
        normalized = normalize_tool_result_messages(session)
        formatted = cohere_format(normalized)
        tool_msgs = [m for m in formatted if m.get("role") == "tool"]
        assert len(tool_msgs) == 2
        for tm in tool_msgs:
            assert "tool_call_id" in tm


# ===========================================================================
# Level 3: Multi-turn conversation with DB storage round-trips
# ===========================================================================


class TestLevel3MultiTurnWithStorage:
    def _multi_turn_session(self):
        return [
            _user("What's TSLA at?"),
            _assistant_with_calls(["call_1"], ["get_stock_price"]),
            _tool_canonical("call_1", '{"price": 250.42}', "get_stock_price"),
            _assistant("TSLA is $250.42."),
            _user("And what about AAPL? Also search for recent news about it."),
            _assistant_with_calls(["call_2", "call_3"], ["get_stock_price", "search_news"]),
            _tool_canonical("call_2", '{"price": 178.50}', "get_stock_price"),
            _tool_canonical("call_3", '{"articles": ["Apple Q4 beat", "New iPhone launch"]}', "search_news"),
            _assistant("AAPL is $178.50. Recent news: Q4 earnings beat and new iPhone launch."),
            _user("Now compare their market caps"),
            _assistant_with_calls(["call_4", "call_5"], ["get_market_cap", "get_market_cap"]),
            _tool_canonical("call_4", '{"market_cap": "800B", "ticker": "TSLA"}', "get_market_cap"),
            _tool_canonical("call_5", '{"market_cap": "2.8T", "ticker": "AAPL"}', "get_market_cap"),
            _assistant("TSLA market cap: $800B. AAPL market cap: $2.8T."),
        ]

    def test_full_session_openai_chat(self):
        session = self._multi_turn_session()
        model = OpenAIChat(id="gpt-4o-mini")
        formatted = model._format_messages(session)
        _verify_openai_chat_valid(formatted)
        tool_msgs = [m for m in formatted if m["role"] == "tool"]
        assert len(tool_msgs) == 5
        ids = [m["tool_call_id"] for m in tool_msgs]
        assert ids == ["call_1", "call_2", "call_3", "call_4", "call_5"]

    def test_store_restore_store_restore(self):
        session = self._multi_turn_session()

        restored_1 = _db_round_trip(session[:4])
        turn_2 = restored_1 + session[4:9]

        restored_2 = _db_round_trip(turn_2)
        turn_3 = restored_2 + session[9:]

        restored_3 = _db_round_trip(turn_3)

        model = OpenAIChat(id="gpt-4o-mini")
        formatted = model._format_messages(restored_3)
        _verify_openai_chat_valid(formatted)
        tool_msgs = [m for m in formatted if m["role"] == "tool"]
        assert len(tool_msgs) == 5

    def test_switch_model_mid_session(self):
        session = self._multi_turn_session()

        chat_model = OpenAIChat(id="gpt-4o-mini")
        formatted_turn1 = chat_model._format_messages(session[:4])
        _verify_openai_chat_valid(formatted_turn1)

        responses_model = OpenAIResponses(id="gpt-4o-mini")
        formatted_full = responses_model._format_messages(session)
        _verify_openai_responses_valid(formatted_full)

        outputs = [m for m in formatted_full if m.get("type") == "function_call_output"]
        assert len(outputs) == 5

    def test_store_with_chat_restore_with_responses(self):
        session = self._multi_turn_session()

        chat_model = OpenAIChat(id="gpt-4o-mini")
        chat_model._format_messages(session[:4])

        restored = _db_round_trip(session)

        responses_model = OpenAIResponses(id="gpt-4o-mini")
        formatted = responses_model._format_messages(restored)
        _verify_openai_responses_valid(formatted)
        outputs = [m for m in formatted if m.get("type") == "function_call_output"]
        assert len(outputs) == 5


# ===========================================================================
# Level 4: Cross-provider chain (Gemini → OpenAI Chat → Responses → Cohere)
# ===========================================================================


class TestLevel4CrossProviderChain:
    def _gemini_session_turn1(self):
        return [
            _user("Search for AI news and get NVDA price"),
            _assistant_with_calls(["call_1", "call_2"], ["search_news", "get_stock_price"]),
            _tool_gemini_combined(
                [
                    ("call_1", "search_news", '{"articles": ["GPT-5 release", "Claude 4 launch"]}'),
                    ("call_2", "get_stock_price", '{"price": 890.00, "ticker": "NVDA"}'),
                ]
            ),
            _assistant("AI news: GPT-5 and Claude 4 launched. NVDA is at $890."),
        ]

    def test_gemini_to_openai_chat_to_responses(self):
        turn1 = self._gemini_session_turn1()

        chat_model = OpenAIChat(id="gpt-4o-mini")
        chat_formatted = chat_model._format_messages(turn1)
        _verify_openai_chat_valid(chat_formatted)
        chat_tools = [m for m in chat_formatted if m["role"] == "tool"]
        assert len(chat_tools) == 2

        stored = _db_round_trip(turn1)

        turn2 = stored + [
            _user("What else about NVDA?"),
            _assistant_with_calls(["call_3"], ["get_company_info"]),
            _tool_canonical("call_3", '{"sector": "Tech", "employees": 26000}', "get_company_info"),
            _assistant("NVDA is in the tech sector with 26,000 employees."),
        ]

        responses_model = OpenAIResponses(id="gpt-4o-mini")
        resp_formatted = responses_model._format_messages(turn2)
        _verify_openai_responses_valid(resp_formatted)
        outputs = [m for m in resp_formatted if m.get("type") == "function_call_output"]
        assert len(outputs) == 3

    def test_gemini_to_cohere_to_openai(self):
        turn1 = self._gemini_session_turn1()

        normalized = normalize_tool_result_messages(turn1)
        cohere_formatted = cohere_format(normalized)
        cohere_tools = [m for m in cohere_formatted if m.get("role") == "tool"]
        assert len(cohere_tools) == 2

        stored = _db_round_trip(turn1)

        turn2 = stored + [
            _user("Summarize everything"),
            _assistant("Here's a summary of what we found about AI and NVDA."),
        ]

        chat_model = OpenAIChat(id="gpt-4o-mini")
        final_formatted = chat_model._format_messages(turn2)
        _verify_openai_chat_valid(final_formatted)
        tool_msgs = [m for m in final_formatted if m["role"] == "tool"]
        assert len(tool_msgs) == 2

    def test_three_db_round_trips_preserve_content(self):
        session = self._gemini_session_turn1()

        for _ in range(3):
            session = _db_round_trip(session)

        model = OpenAIChat(id="gpt-4o-mini")
        formatted = model._format_messages(session)
        _verify_openai_chat_valid(formatted)
        tool_msgs = [m for m in formatted if m["role"] == "tool"]
        assert len(tool_msgs) == 2
        contents = {m["content"] for m in tool_msgs}
        assert any("GPT-5" in c for c in contents)
        assert any("890" in c for c in contents)

    @requires_deepseek
    def test_gemini_to_deepseek_to_openai_chat(self):
        turn1 = self._gemini_session_turn1()

        deepseek = DeepSeek(id="deepseek-chat")
        ds_formatted = deepseek._format_messages(turn1)
        _verify_openai_chat_valid(ds_formatted)

        stored = _db_round_trip(turn1)
        chat_model = OpenAIChat(id="gpt-4o-mini")
        chat_formatted = chat_model._format_messages(stored)
        _verify_openai_chat_valid(chat_formatted)


# ===========================================================================
# Level 5: Stress scenarios
# ===========================================================================


class TestLevel5StressScenarios:
    def test_50_parallel_tool_calls_gemini_to_openai(self):
        tool_data = [(f"call_{i}", f"tool_{i}", json.dumps({"result": f"data_{i}"})) for i in range(50)]
        session = [
            _user("Run all 50 tools"),
            _assistant_with_calls(
                [td[0] for td in tool_data],
                [td[1] for td in tool_data],
            ),
            _tool_gemini_combined(tool_data),
            _assistant("All 50 tools completed."),
        ]

        model = OpenAIChat(id="gpt-4o-mini")
        formatted = model._format_messages(session)
        _verify_openai_chat_valid(formatted)
        tool_msgs = [m for m in formatted if m["role"] == "tool"]
        assert len(tool_msgs) == 50

        stored = _db_round_trip(session)
        formatted_after = model._format_messages(stored)
        _verify_openai_chat_valid(formatted_after)
        tool_msgs_after = [m for m in formatted_after if m["role"] == "tool"]
        assert len(tool_msgs_after) == 50

    def test_deeply_nested_json_tool_results(self):
        nested_result = json.dumps(
            {
                "level1": {
                    "level2": {
                        "level3": {
                            "data": [1, 2, {"level4": True}],
                            "metadata": {"timestamp": 1234567890, "source": "api"},
                        }
                    },
                    "siblings": [{"a": 1}, {"b": 2}, {"c": [3, 4, 5]}],
                }
            }
        )

        session = [
            _user("Get nested data"),
            _assistant_with_calls(["call_1"], ["get_nested"]),
            _tool_canonical("call_1", nested_result, "get_nested"),
            _assistant("Got the nested data."),
        ]

        model = OpenAIChat(id="gpt-4o-mini")
        formatted = model._format_messages(session)
        _verify_openai_chat_valid(formatted)

        tool_msg = [m for m in formatted if m["role"] == "tool"][0]
        parsed = json.loads(tool_msg["content"])
        assert parsed["level1"]["level2"]["level3"]["data"][2]["level4"] is True

        stored = _db_round_trip(session)
        formatted_after = model._format_messages(stored)
        tool_msg_after = [m for m in formatted_after if m["role"] == "tool"][0]
        parsed_after = json.loads(tool_msg_after["content"])
        assert parsed_after == parsed

    def test_gemini_combined_with_nested_json_per_tool(self):
        tool_data = [
            ("call_1", "search", json.dumps({"results": [{"title": "AI", "score": 0.95}]})),
            ("call_2", "fetch", json.dumps({"html": "<p>content</p>", "status": 200})),
            ("call_3", "analyze", json.dumps({"sentiment": {"positive": 0.8, "negative": 0.2}})),
        ]
        session = [
            _user("Search, fetch, and analyze"),
            _assistant_with_calls(
                [td[0] for td in tool_data],
                [td[1] for td in tool_data],
            ),
            _tool_gemini_combined(tool_data),
            _assistant("Done."),
        ]

        for model_cls in [OpenAIChat, OpenAIResponses]:
            model = model_cls(id="gpt-4o-mini")
            formatted = model._format_messages(session)
            if model_cls == OpenAIChat:
                _verify_openai_chat_valid(formatted)
                tools = [m for m in formatted if m["role"] == "tool"]
                assert len(tools) == 3
                for t in tools:
                    json.loads(t["content"])
            else:
                _verify_openai_responses_valid(formatted)
                outputs = [m for m in formatted if m.get("type") == "function_call_output"]
                assert len(outputs) == 3

    def test_compressed_content_survives_full_pipeline(self):
        session = [
            _user("Get data"),
            _assistant_with_calls(["call_1", "call_2"], ["big_query", "small_query"]),
            _tool_gemini_combined(
                [
                    ("call_1", "big_query", "This is a very long result with lots of data..."),
                    ("call_2", "small_query", "Short result"),
                ]
            ),
            _assistant("Got it."),
        ]

        normalized = normalize_tool_result_messages(session, compress_tool_results=True)
        tool_msgs = [m for m in normalized if m.role == "tool"]
        assert len(tool_msgs) == 2
        assert tool_msgs[0].compressed_content is not None
        assert tool_msgs[1].compressed_content is not None

        stored = _db_round_trip(normalized)
        tool_msgs_restored = [m for m in stored if m.role == "tool"]
        assert tool_msgs_restored[0].compressed_content == tool_msgs[0].compressed_content
        assert tool_msgs_restored[1].compressed_content == tool_msgs[1].compressed_content

        model = OpenAIChat(id="gpt-4o-mini")
        formatted = model._format_messages(stored, compress_tool_results=True)
        _verify_openai_chat_valid(formatted)
        chat_tools = [m for m in formatted if m["role"] == "tool"]
        assert len(chat_tools) == 2

    def test_empty_and_none_content_mixed_session(self):
        session = [
            _user("Run tools"),
            _assistant_with_calls(["call_1", "call_2", "call_3"], ["a", "b", "c"]),
            _tool_canonical("call_1", "", "a"),
            _tool_canonical("call_2", None, "b"),
            _tool_canonical("call_3", '{"ok": true}', "c"),
            _assistant("Done."),
        ]

        model = OpenAIChat(id="gpt-4o-mini")
        formatted = model._format_messages(session)
        _verify_openai_chat_valid(formatted)
        tool_msgs = [m for m in formatted if m["role"] == "tool"]
        assert len(tool_msgs) == 3

        stored = _db_round_trip(session)
        formatted_after = model._format_messages(stored)
        tool_msgs_after = [m for m in formatted_after if m["role"] == "tool"]
        assert len(tool_msgs_after) == 3

    def test_10_turn_conversation_with_alternating_formats(self):
        session = []
        for turn in range(10):
            call_id = f"call_{turn}"
            tool_name = f"tool_{turn}"
            result = json.dumps({"turn": turn, "value": turn * 10})

            session.append(_user(f"Turn {turn}: run {tool_name}"))
            session.append(_assistant_with_calls([call_id], [tool_name]))

            if turn % 2 == 0:
                session.append(_tool_canonical(call_id, result, tool_name))
            else:
                session.append(_tool_gemini_combined([(call_id, tool_name, result)]))

            session.append(_assistant(f"Turn {turn} complete."))

        model = OpenAIChat(id="gpt-4o-mini")
        formatted = model._format_messages(session)
        _verify_openai_chat_valid(formatted)
        tool_msgs = [m for m in formatted if m["role"] == "tool"]
        assert len(tool_msgs) == 10

        stored = _db_round_trip(session)
        formatted_after = model._format_messages(stored)
        tool_msgs_after = [m for m in formatted_after if m["role"] == "tool"]
        assert len(tool_msgs_after) == 10

        for i, tm in enumerate(tool_msgs_after):
            parsed = json.loads(tm["content"])
            assert parsed["turn"] == i
            assert parsed["value"] == i * 10


# ===========================================================================
# Level 6: Field preservation through full pipeline
# ===========================================================================


class TestLevel6FieldPreservation:
    def test_provider_data_survives_normalize_store_format(self):
        msg = Message(
            role="tool",
            content=["r1", "r2"],
            provider_data={"gemini": {"safety_rating": "safe", "finish_reason": "STOP"}},
            tool_calls=[
                {"tool_call_id": "c1", "tool_name": "a", "content": "r1"},
                {"tool_call_id": "c2", "tool_name": "b", "content": "r2"},
            ],
        )
        session = [_user("test"), _assistant_with_calls(["c1", "c2"], ["a", "b"]), msg, _assistant("done")]

        normalized = normalize_tool_result_messages(session)
        tool_msgs = [m for m in normalized if m.role == "tool"]
        assert all(m.provider_data is not None for m in tool_msgs)

        stored = _db_round_trip(normalized)
        tool_msgs_stored = [m for m in stored if m.role == "tool"]
        assert all(m.provider_data is not None for m in tool_msgs_stored)
        assert tool_msgs_stored[0].provider_data["gemini"]["safety_rating"] == "safe"

    def test_from_history_flag_preserved(self):
        session = [
            _user("test"),
            _assistant_with_calls(["c1"], ["fn"]),
            _tool_gemini_combined([("c1", "fn", "result")]),
            _assistant("done"),
        ]

        for msg in session:
            msg.from_history = True

        normalized = normalize_tool_result_messages(session)
        tool_msgs = [m for m in normalized if m.role == "tool"]
        assert all(m.from_history is True for m in tool_msgs)

    def test_metrics_isolation_across_splits(self):
        combined = _tool_gemini_combined(
            [
                ("c1", "a", "r1"),
                ("c2", "b", "r2"),
                ("c3", "c", "r3"),
            ]
        )

        normalized = normalize_tool_result_messages([combined])
        assert len(normalized) == 3

        normalized[0].metrics.input_tokens = 100
        assert normalized[1].metrics.input_tokens != 100
        assert normalized[2].metrics.input_tokens != 100

    def test_created_at_consistent_across_splits(self):
        combined = _tool_gemini_combined([("c1", "a", "r1"), ("c2", "b", "r2")])
        original_ts = combined.created_at

        normalized = normalize_tool_result_messages([combined])
        assert all(m.created_at == original_ts for m in normalized)

    def test_tool_call_id_types_through_full_pipeline(self):
        msg = Message(
            role="tool",
            content=["r1", "r2"],
            tool_calls=[
                {"tool_call_id": 12345, "tool_name": "a", "content": "r1"},
                {"tool_call_id": "call_abc", "tool_name": "b", "content": "r2"},
            ],
        )
        session = [_user("test"), _assistant_with_calls(["12345", "call_abc"], ["a", "b"]), msg, _assistant("done")]

        model = OpenAIChat(id="gpt-4o-mini")
        formatted = model._format_messages(session)
        _verify_openai_chat_valid(formatted)
        tool_msgs = [m for m in formatted if m["role"] == "tool"]
        assert tool_msgs[0]["tool_call_id"] == "12345"
        assert tool_msgs[1]["tool_call_id"] == "call_abc"
