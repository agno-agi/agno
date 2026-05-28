"""Tests for AgentOS config schemas, focused on the Manifest field."""

import json
import tempfile
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from pydantic import ValidationError

from agno.agent.agent import Agent
from agno.os import AgentOS
from agno.os.config import AgentOSConfig, ChatConfig, Manifest
from agno.os.schema import ConfigResponse
from agno.os.utils import load_yaml_config


class TestManifest:
    def test_all_fields(self):
        m = Manifest(
            description="Plans and runs marketing campaigns.",
            labels=["beta", "marketing"],
            quick_prompts=["What can you do?", "Tell me more"],
        )
        assert m.description == "Plans and runs marketing campaigns."
        assert m.labels == ["beta", "marketing"]
        assert m.quick_prompts == ["What can you do?", "Tell me more"]

    def test_all_fields_optional(self):
        m = Manifest()
        assert m.description is None
        assert m.labels is None
        assert m.quick_prompts is None

    def test_labels_as_list(self):
        m = Manifest(labels=["beta", "internal"])
        assert m.labels == ["beta", "internal"]

    def test_labels_as_dict(self):
        m = Manifest(labels={"env": "prod", "team": "growth"})
        assert m.labels == {"env": "prod", "team": "growth"}

    def test_labels_reject_invalid_shape(self):
        with pytest.raises(ValidationError):
            Manifest(labels=123)
        with pytest.raises(ValidationError):
            Manifest(labels=[1, 2, 3])

    def test_quick_prompts_cap_enforced(self):
        with pytest.raises(ValidationError, match="Too many quick prompts"):
            Manifest(quick_prompts=["a", "b", "c", "d"])

    def test_quick_prompts_at_cap_allowed(self):
        m = Manifest(quick_prompts=["a", "b", "c"])
        assert len(m.quick_prompts) == 3

    def test_quick_prompts_empty_allowed(self):
        # An explicit empty list is fine - means "no prompts configured."
        m = Manifest(quick_prompts=[])
        assert m.quick_prompts == []


class TestAgentOSConfigManifestField:
    def test_manifest_field_default_none(self):
        cfg = AgentOSConfig()
        assert cfg.manifest is None

    def test_manifest_python_construction(self):
        cfg = AgentOSConfig(
            manifest={
                "marketing-agent": Manifest(
                    description="Plans and runs marketing campaigns.",
                    labels=["beta"],
                    quick_prompts=["What can you do?"],
                ),
                "support-team": Manifest(labels={"env": "prod"}),
            },
        )
        assert cfg.manifest["marketing-agent"].description == "Plans and runs marketing campaigns."
        assert cfg.manifest["marketing-agent"].labels == ["beta"]
        assert cfg.manifest["support-team"].labels == {"env": "prod"}

    def test_manifest_from_yaml(self):
        raw = yaml.safe_load(
            """
            manifest:
              marketing-agent:
                description: "Plans and runs marketing campaigns."
                labels: ["beta", "marketing"]
                quick_prompts:
                  - "What can you do?"
                  - "Latest post?"
              support-team:
                description: "Triages support tickets."
                labels:
                  env: "prod"
                  team: "growth"
            """
        )
        cfg = AgentOSConfig(**raw)
        m = cfg.manifest["marketing-agent"]
        assert m.description == "Plans and runs marketing campaigns."
        assert m.labels == ["beta", "marketing"]
        assert m.quick_prompts == ["What can you do?", "Latest post?"]
        assert cfg.manifest["support-team"].labels == {"env": "prod", "team": "growth"}

    def test_manifest_quick_prompts_cap_via_yaml(self):
        raw = yaml.safe_load(
            """
            manifest:
              marketing-agent:
                quick_prompts: ["1", "2", "3", "4"]
            """
        )
        with pytest.raises(ValidationError, match="Too many quick prompts"):
            AgentOSConfig(**raw)


class TestBackwardCompat:
    def test_chat_config_untouched(self):
        # ChatConfig still works exactly as before - no manifest involvement.
        chat = ChatConfig(quick_prompts={"marketing-agent": ["a", "b"]})
        assert chat.quick_prompts == {"marketing-agent": ["a", "b"]}

    def test_chat_config_cap_still_enforced(self):
        with pytest.raises(ValidationError, match="Too many quick prompts"):
            ChatConfig(quick_prompts={"marketing-agent": ["a", "b", "c", "d"]})

    def test_legacy_yaml_still_loads(self):
        raw = yaml.safe_load(
            """
            chat:
              quick_prompts:
                marketing-agent:
                  - "What can you do?"
            """
        )
        cfg = AgentOSConfig(**raw)
        assert cfg.chat.quick_prompts == {"marketing-agent": ["What can you do?"]}
        assert cfg.manifest is None

    def test_chat_and_manifest_coexist(self):
        cfg = AgentOSConfig(
            chat=ChatConfig(quick_prompts={"legacy-agent": ["one", "two"]}),
            manifest={"new-agent": Manifest(description="Hi", quick_prompts=["a"])},
        )
        assert cfg.chat.quick_prompts == {"legacy-agent": ["one", "two"]}
        assert cfg.manifest["new-agent"].description == "Hi"


class TestConfigResponseExposesManifest:
    def test_response_includes_manifest(self):
        resp = ConfigResponse(
            os_id="test-os",
            databases=[],
            manifest={
                "marketing-agent": Manifest(
                    description="Plans campaigns.",
                    labels=["beta"],
                    quick_prompts=["What can you do?"],
                ),
            },
            agents=[],
            teams=[],
            workflows=[],
            interfaces=[],
        )
        dumped = resp.model_dump(exclude_none=True)
        assert "manifest" in dumped
        assert dumped["manifest"]["marketing-agent"]["description"] == "Plans campaigns."
        assert dumped["manifest"]["marketing-agent"]["labels"] == ["beta"]

    def test_response_omits_manifest_when_none(self):
        resp = ConfigResponse(
            os_id="test-os",
            databases=[],
            agents=[],
            teams=[],
            workflows=[],
            interfaces=[],
        )
        dumped = resp.model_dump(exclude_none=True)
        assert "manifest" not in dumped

    def test_response_round_trips_labels_dict(self):
        # The dict-shape for labels must survive a JSON round-trip alongside the list shape.
        resp = ConfigResponse(
            os_id="test-os",
            databases=[],
            manifest={
                "support-team": Manifest(labels={"env": "prod", "team": "growth"}),
                "marketing-agent": Manifest(labels=["beta"]),
            },
            agents=[],
            teams=[],
            workflows=[],
            interfaces=[],
        )
        rebuilt = ConfigResponse(**json.loads(resp.model_dump_json()))
        assert rebuilt.manifest["support-team"].labels == {"env": "prod", "team": "growth"}
        assert rebuilt.manifest["marketing-agent"].labels == ["beta"]


class TestLoadYamlConfig:
    def test_load_yaml_config_parses_manifest(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(
                """
                manifest:
                  marketing-agent:
                    description: "Plans campaigns."
                    labels: ["beta", "marketing"]
                    quick_prompts:
                      - "What can you do?"
                  support-team:
                    labels:
                      env: "prod"
                      team: "growth"
                """
            )
            path = f.name
        try:
            cfg = load_yaml_config(path)
            assert cfg.manifest["marketing-agent"].description == "Plans campaigns."
            assert cfg.manifest["marketing-agent"].labels == ["beta", "marketing"]
            assert cfg.manifest["support-team"].labels == {"env": "prod", "team": "growth"}
        finally:
            Path(path).unlink()


class TestConfigEndpointSerialization:
    """End-to-end test: spin up AgentOS, hit /config, assert manifest comes back over HTTP."""

    def _build_client(self, manifest):
        agent = Agent(name="Marketing Agent", id="marketing-agent", telemetry=False)
        os_instance = AgentOS(
            agents=[agent],
            telemetry=False,
            config=AgentOSConfig(manifest=manifest),
        )
        return TestClient(os_instance.get_app())

    def test_manifest_serialized_with_list_labels(self):
        client = self._build_client(
            {
                "marketing-agent": Manifest(
                    description="Plans campaigns.",
                    labels=["beta", "marketing"],
                    quick_prompts=["What can you do?"],
                ),
            }
        )
        resp = client.get("/config")
        assert resp.status_code == 200
        body = resp.json()
        assert "manifest" in body
        assert body["manifest"]["marketing-agent"] == {
            "description": "Plans campaigns.",
            "labels": ["beta", "marketing"],
            "quick_prompts": ["What can you do?"],
        }

    def test_manifest_serialized_with_dict_labels(self):
        client = self._build_client({"marketing-agent": Manifest(labels={"env": "prod", "team": "growth"})})
        resp = client.get("/config")
        assert resp.status_code == 200
        body = resp.json()
        assert body["manifest"]["marketing-agent"]["labels"] == {"env": "prod", "team": "growth"}

    def test_manifest_absent_from_response_when_unset(self):
        agent = Agent(name="Marketing Agent", id="marketing-agent", telemetry=False)
        os_instance = AgentOS(agents=[agent], telemetry=False)
        client = TestClient(os_instance.get_app())
        resp = client.get("/config")
        assert resp.status_code == 200
        # response_model_exclude_none=True on the route - so None manifest is omitted.
        assert "manifest" not in resp.json()
