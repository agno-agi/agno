"""Prompt facade: one reusable text block with immutable published versions.

A Prompt is a ``str`` or a list of instruction blocks stored in the component
catalog. ``save`` always appends and publishes a new version, so identical
saves still produce distinct version numbers; ``load`` reads the current
published pointer unless an exact version or label is requested. Selector and
fallback values belong to the consumer relationship and never enter the
stored component config. Persistence is synchronous only.
"""

import dataclasses
import json
import re
from unittest.mock import MagicMock

import pytest

from agno.db.base import AsyncBaseDb, BaseDb
from agno.db.base import ComponentType as DbComponentType
from agno.db.sqlite import SqliteDb
from agno.os.schema import ComponentType as ApiComponentType
from agno.prompt import Prompt

SELECTOR_ERROR = "`version` must be a positive integer, 'latest', or None"
CONTENT = ["Be concise.", "Never expose private customer data."]


@pytest.fixture
def db(tmp_path):
    return SqliteDb(id="prompt-db", db_file=str(tmp_path / "prompt.db"))


def _support_prompt(**overrides):
    fields = {
        "id": "support",
        "name": "Support instructions",
        "content": list(CONTENT),
        "description": "Shared support behavior",
    }
    fields.update(overrides)
    return Prompt(**fields)


class TestSelectorValidation:
    @pytest.mark.parametrize("version", [None, 1, 7, "latest"])
    def test_accepts_none_positive_integers_and_latest(self, version):
        assert Prompt(id="support", version=version).version == version

    @pytest.mark.parametrize(
        "version",
        [True, False, 0, -1, 1.5, 2.0, "", "1", "v1", "LATEST", "current", [], {}, object()],
    )
    def test_rejects_every_other_selector(self, version):
        with pytest.raises(ValueError, match=re.escape(SELECTOR_ERROR)):
            Prompt(id="support", version=version)


class TestContentValidation:
    def test_accepts_a_string(self):
        assert Prompt(id="support", content="Be concise.").content == "Be concise."

    def test_accepts_a_list_of_strings(self):
        assert Prompt(id="support", content=list(CONTENT)).content == CONTENT

    def test_accepts_none_for_a_reference_only_handle(self):
        assert Prompt(id="support").content is None

    @pytest.mark.parametrize("content", [42, 1.5, {"text": "x"}, ("a", "b"), ["ok", 3], [None], b"bytes"])
    def test_rejects_non_text_content(self, content):
        with pytest.raises(ValueError, match="`content` must be a string or a list of strings"):
            Prompt(id="support", content=content)

    @pytest.mark.parametrize("fallback", ["Answer safely.", ["Answer safely.", "Stay polite."], None])
    def test_fallback_accepts_the_same_shapes(self, fallback):
        assert Prompt(id="support", fallback=fallback).fallback == fallback

    @pytest.mark.parametrize("fallback", [42, ["ok", 3]])
    def test_fallback_rejects_non_text(self, fallback):
        with pytest.raises(ValueError, match="`fallback` must be a string or a list of strings"):
            Prompt(id="support", fallback=fallback)


class TestIdValidation:
    @pytest.mark.parametrize("prompt_id", ["", "   ", None, 7])
    def test_rejects_missing_or_blank_ids(self, prompt_id):
        with pytest.raises(ValueError, match="`id` must be a non-empty string"):
            Prompt(id=prompt_id)


class TestComponentSerialization:
    def test_to_dict_emits_the_component_shape(self):
        assert _support_prompt().to_dict() == {
            "type": "prompt",
            "id": "support",
            "name": "Support instructions",
            "content": CONTENT,
            "description": "Shared support behavior",
        }

    def test_to_dict_omits_unset_optional_fields(self):
        assert Prompt(id="support", content="Be concise.").to_dict() == {
            "type": "prompt",
            "id": "support",
            "content": "Be concise.",
        }

    def test_to_dict_excludes_relationship_state(self):
        config = _support_prompt(version="latest", fallback=["Answer safely."]).to_dict()
        assert "version" not in config
        assert "fallback" not in config

    def test_from_dict_restores_the_prompt(self):
        prompt = _support_prompt()
        assert Prompt.from_dict(prompt.to_dict()) == prompt

    def test_round_trip_survives_json(self):
        prompt = _support_prompt()
        assert Prompt.from_dict(json.loads(json.dumps(prompt.to_dict()))) == prompt

    def test_from_dict_refuses_another_component_type(self):
        with pytest.raises(ValueError, match="prompt"):
            Prompt.from_dict({"type": "agent", "id": "support", "content": "x"})


class TestReferenceSerialization:
    @pytest.mark.parametrize(
        "version, expected",
        [
            (None, {"prompt_id": "support"}),
            (3, {"prompt_id": "support", "version": 3}),
            ("latest", {"prompt_id": "support", "version": "latest"}),
        ],
    )
    def test_reference_carries_only_identity_and_selector(self, version, expected):
        prompt = _support_prompt(version=version, fallback=["Answer safely."])
        assert prompt._to_reference() == expected


class TestNoHiddenState:
    def test_only_the_public_fields_exist(self):
        assert [f.name for f in dataclasses.fields(Prompt)] == [
            "id",
            "content",
            "name",
            "description",
            "version",
            "fallback",
        ]

    def test_equality_and_repr_use_the_public_fields(self):
        left = _support_prompt(version=2, fallback="Answer safely.")
        right = _support_prompt(version=2, fallback="Answer safely.")
        assert left == right
        assert repr(left) == repr(right)
        assert repr(left).startswith("Prompt(id='support'")


class TestPublicApi:
    def test_root_import_and_module_agree(self):
        import agno.prompt.prompt as module

        assert Prompt is module.Prompt

    def test_both_component_enums_expose_prompt(self):
        assert DbComponentType.PROMPT.value == "prompt"
        assert ApiComponentType.PROMPT.value == "prompt"
        assert DbComponentType(ApiComponentType.PROMPT.value) is DbComponentType.PROMPT

    @pytest.mark.parametrize("name", ["asave", "aload", "adelete"])
    def test_no_async_persistence(self, name):
        assert not hasattr(Prompt, name)


class TestSave:
    def test_requires_content_before_any_write(self):
        db = MagicMock(spec=BaseDb)
        with pytest.raises(ValueError, match="`content` is required to save a Prompt"):
            Prompt(id="support").save(db=db)
        db.upsert_component.assert_not_called()
        db.upsert_config.assert_not_called()

    def test_refuses_an_async_db(self):
        db = MagicMock(spec=AsyncBaseDb)
        with pytest.raises(ValueError, match="Async databases not yet supported for save"):
            _support_prompt().save(db=db)

    # Two independent databases in one process: version numbers must come from the catalog, never process state.
    @pytest.mark.parametrize("run", [1, 2])
    def test_each_identical_save_publishes_a_new_version(self, db, run):
        prompt = _support_prompt()
        assert prompt.save(db=db) == 1
        assert prompt.save(db=db) == 2
        assert db.get_component("support")["current_version"] == 2
        for version in (1, 2):
            row = db.get_config("support", version=version)
            assert row["stage"] == "published"
            assert row["config"] == prompt.to_dict()

    def test_registers_a_prompt_component(self, db):
        _support_prompt().save(db=db)
        row = db.get_component("support")
        assert row["component_type"] == "prompt"
        assert row["name"] == "Support instructions"
        assert row["description"] == "Shared support behavior"

    def test_component_name_defaults_to_the_id(self, db):
        Prompt(id="support", content="Be concise.").save(db=db)
        assert db.get_component("support")["name"] == "support"

    def test_earlier_versions_stay_immutable(self, db):
        prompt = Prompt(id="support", content="one")
        prompt.save(db=db)
        prompt.content = "two"
        prompt.save(db=db)
        assert db.get_config("support", version=1)["config"]["content"] == "one"
        assert db.get_config("support", version=2)["config"]["content"] == "two"


class TestLoad:
    def test_uses_the_current_published_pointer(self, db):
        Prompt(id="support", content="one").save(db=db)
        Prompt(id="support", content="two").save(db=db)
        assert Prompt.load("support", db=db) == Prompt(id="support", content="two")

    def test_explicit_version(self, db):
        Prompt(id="support", content="one").save(db=db)
        Prompt(id="support", content="two").save(db=db)
        assert Prompt.load("support", db=db, version=1) == Prompt(id="support", content="one")

    def test_label(self, db):
        # Labels are attached at creation through the catalog API; the facade reads them back.
        db.upsert_component(component_id="support", component_type=DbComponentType.PROMPT, name="support")
        db.upsert_config(
            component_id="support",
            config=Prompt(id="support", content="one").to_dict(),
            stage="published",
            label="stable",
        )
        Prompt(id="support", content="two").save(db=db)
        assert Prompt.load("support", db=db, label="stable") == Prompt(id="support", content="one")
        assert Prompt.load("support", db=db) == Prompt(id="support", content="two")

    def test_returns_none_when_nothing_is_published(self, db):
        db.upsert_component(component_id="support", component_type=DbComponentType.PROMPT, name="support")
        db.upsert_config(component_id="support", config=Prompt(id="support", content="draft").to_dict())
        assert db.get_config("support") is not None
        assert Prompt.load("support", db=db) is None

    def test_returns_none_for_an_unknown_id(self, db):
        assert Prompt.load("missing", db=db) is None

    def test_returns_none_for_a_component_of_another_type(self, db):
        db.upsert_component(component_id="helper", component_type=DbComponentType.AGENT, name="helper")
        db.upsert_config(component_id="helper", config={"id": "helper", "instructions": "x"}, stage="published")
        assert Prompt.load("helper", db=db) is None

    def test_uses_the_requested_id_when_the_stored_config_has_none(self, db):
        # A config written through the generic component API need not carry the id.
        db.upsert_component(component_id="support", component_type=DbComponentType.PROMPT, name="support")
        db.upsert_config(component_id="support", config={"type": "prompt", "content": "Be concise."}, stage="published")
        assert Prompt.load("support", db=db) == Prompt(id="support", content="Be concise.")

    def test_loaded_prompt_carries_no_relationship_state(self, db):
        _support_prompt(version="latest", fallback=["Answer safely."]).save(db=db)
        assert Prompt.load("support", db=db) == _support_prompt()


class TestDelete:
    def test_requests_dependency_safe_generic_deletion(self):
        db = MagicMock(spec=BaseDb)
        db.delete_component.return_value = True
        assert _support_prompt().delete(db=db) is True
        db.delete_component.assert_called_once_with(
            component_id="support", hard_delete=False, require_no_dependents=True
        )

    def test_refuses_an_async_db(self):
        db = MagicMock(spec=AsyncBaseDb)
        with pytest.raises(ValueError, match="Async databases not yet supported for delete"):
            _support_prompt().delete(db=db)

    def test_archives_the_component(self, db):
        prompt = _support_prompt()
        prompt.save(db=db)
        assert prompt.delete(db=db) is True
        assert db.get_component("support") is None
        assert db.get_component("support", include_deleted=True) is not None
        assert Prompt.load("support", db=db) is None
