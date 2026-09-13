import pytest

from agno.knowledge.content import ContentStatus as CoreContentStatus
from agno.knowledge.knowledge import Knowledge
from agno.os.routers.knowledge.schemas import ContentResponseSchema
from agno.os.routers.knowledge.schemas import ContentStatus as ApiContentStatus


class TestEnumsStayInSync:
    def test_api_enum_covers_every_core_status(self):
        assert {s.value for s in CoreContentStatus} == {s.value for s in ApiContentStatus}

    def test_partial_is_available_on_both(self):
        assert CoreContentStatus.PARTIAL.value == "partial"
        assert ApiContentStatus.PARTIAL.value == "partial"


class TestApiResponseStatus:
    def test_partial_is_surfaced_not_downgraded_to_processing(self):
        message = "7 of 10 chunks were embedded; 3 failed and are not retrievable."

        response = ContentResponseSchema.from_dict({"id": "c1", "status": "partial", "status_message": message})

        assert response.status == ApiContentStatus.PARTIAL
        assert response.status_message == message

    @pytest.mark.parametrize(
        "stored,expected",
        [
            ("processing", ApiContentStatus.PROCESSING),
            ("completed", ApiContentStatus.COMPLETED),
            ("partial", ApiContentStatus.PARTIAL),
            ("failed", ApiContentStatus.FAILED),
        ],
    )
    def test_each_status_round_trips(self, stored, expected):
        assert ContentResponseSchema.from_dict({"id": "c1", "status": stored}).status == expected

    @pytest.mark.parametrize(
        "legacy,expected",
        [
            ("PARTIAL", ApiContentStatus.PARTIAL),
            ("partially_failed", ApiContentStatus.PARTIAL),
            ("FAILED", ApiContentStatus.FAILED),
            ("Completed", ApiContentStatus.COMPLETED),
            ("something_unknown", ApiContentStatus.PROCESSING),
        ],
    )
    def test_legacy_values_map_sensibly(self, legacy, expected):
        """A compound legacy value must not be reported as a total failure."""
        assert ContentResponseSchema.from_dict({"id": "c1", "status": legacy}).status == expected

    def test_missing_status_defaults_to_processing(self):
        assert ContentResponseSchema.from_dict({"id": "c1"}).status == ApiContentStatus.PROCESSING


class TestCoreStatusParser:
    @pytest.mark.parametrize(
        "stored,expected",
        [
            ("partial", CoreContentStatus.PARTIAL),
            ("partially_failed", CoreContentStatus.PARTIAL),
            ("completed", CoreContentStatus.COMPLETED),
            ("failed", CoreContentStatus.FAILED),
            (None, CoreContentStatus.PROCESSING),
            ("nonsense", CoreContentStatus.PROCESSING),
        ],
    )
    def test_parse_content_status(self, stored, expected):
        knowledge = Knowledge.__new__(Knowledge)
        assert knowledge._parse_content_status(stored) == expected


class TestContentRowConversion:
    """Listing content must survive rows holding legacy status values.

    ``_content_row_to_content`` runs for every row in a listing, so raising on
    one unrecognised status would fail the entire request with a 500.
    """

    def _row(self, status):
        from agno.db.schemas.knowledge import KnowledgeRow

        return KnowledgeRow(id="c1", name="n", description="d", status=status, status_message="m")

    @pytest.mark.parametrize(
        "stored,expected",
        [
            ("partial", CoreContentStatus.PARTIAL),
            ("partially_failed", CoreContentStatus.PARTIAL),
            ("PARTIAL", CoreContentStatus.PARTIAL),
            ("Completed", CoreContentStatus.COMPLETED),
            ("hard_failed", CoreContentStatus.FAILED),
            ("bogus_value", CoreContentStatus.PROCESSING),
        ],
    )
    def test_legacy_status_does_not_raise(self, stored, expected):
        knowledge = Knowledge.__new__(Knowledge)

        content = knowledge._content_row_to_content(self._row(stored))

        assert content.status == expected

    def test_missing_status_stays_none(self):
        knowledge = Knowledge.__new__(Knowledge)

        assert knowledge._content_row_to_content(self._row(None)).status is None
