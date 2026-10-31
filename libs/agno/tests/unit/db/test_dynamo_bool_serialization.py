"""
Unit tests for boolean serialization in the DynamoDB utilities.

`bool` is a subclass of `int`, so an `isinstance(value, (int, float))` arm that
is checked before the `bool` arm swallows every boolean and writes
`{"N": "True"}` -- a value DynamoDB rejects, and one that cannot survive a
round-trip through `deserialize_from_dynamodb_item` either (`int("True")`
raises `ValueError`).
"""

from agno.db.dynamo.utils import deserialize_from_dynamodb_item, serialize_to_dynamo_item


class TestSerializeBool:
    """Booleans must be serialized as DynamoDB BOOL, not N."""

    def test_true_is_serialized_as_bool(self):
        assert serialize_to_dynamo_item({"flag": True}) == {"flag": {"BOOL": True}}

    def test_false_is_serialized_as_bool(self):
        assert serialize_to_dynamo_item({"flag": False}) == {"flag": {"BOOL": False}}

    def test_bool_round_trips(self):
        data = {"enabled": True, "archived": False}
        assert deserialize_from_dynamodb_item(serialize_to_dynamo_item(data)) == data

    def test_bool_stays_a_bool_after_round_trip(self):
        restored = deserialize_from_dynamodb_item(serialize_to_dynamo_item({"flag": True}))
        assert isinstance(restored["flag"], bool)


class TestSerializeOtherScalarsUnchanged:
    """The bool arm must not capture the numeric or string types."""

    def test_int_is_still_serialized_as_number(self):
        assert serialize_to_dynamo_item({"count": 3}) == {"count": {"N": "3"}}

    def test_zero_is_still_serialized_as_number(self):
        assert serialize_to_dynamo_item({"count": 0}) == {"count": {"N": "0"}}

    def test_one_is_still_serialized_as_number(self):
        # 1 == True, so an identity-based guard would get this wrong.
        item = serialize_to_dynamo_item({"count": 1})
        assert item == {"count": {"N": "1"}}

    def test_float_is_still_serialized_as_number(self):
        assert serialize_to_dynamo_item({"score": 1.5}) == {"score": {"N": "1.5"}}

    def test_str_is_still_serialized_as_string(self):
        assert serialize_to_dynamo_item({"name": "agno"}) == {"name": {"S": "agno"}}

    def test_none_is_still_dropped(self):
        assert serialize_to_dynamo_item({"missing": None, "kept": "x"}) == {"kept": {"S": "x"}}

    def test_mixed_payload(self):
        data = {"enabled": True, "count": 1, "score": 1.5, "name": "agno"}
        assert serialize_to_dynamo_item(data) == {
            "enabled": {"BOOL": True},
            "count": {"N": "1"},
            "score": {"N": "1.5"},
            "name": {"S": "agno"},
        }
