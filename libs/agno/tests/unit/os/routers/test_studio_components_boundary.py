import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os.routers.components import get_components_router
from agno.os.settings import AgnoAPISettings
from agno.registry import Registry
from agno.run import RunContext
from agno.tools.studio import StudioTools
from agno.tools.studio_schema import AgentCreate, ModelRef


@pytest.fixture
def studio_sqlite_client(tmp_path):
    """Real typed Studio control plane and generic router over one catalog."""
    db = SqliteDb(id="studio-boundary-db", db_file=str(tmp_path / "studio-boundary.db"))
    model = OpenAIResponses(id="gpt-5.4")
    registry = Registry(name="Studio boundary registry", models=[model], dbs=[db])
    studio = StudioTools(
        registry=registry,
        db=db,
        authorize=lambda _context, _access, _action: True,
        default_model=ModelRef(id="gpt-5.4", provider="OpenAI", name="OpenAIResponses"),
    )
    run_context = RunContext(run_id="studio-run", session_id="studio-session", user_id="studio-admin")
    app = FastAPI()
    app.include_router(
        get_components_router(
            os_db=db,
            settings=AgnoAPISettings(),
            registry=registry,
        )
    )
    return TestClient(app), db, studio, run_context


def _guard(latest_version=1, current_version=1):
    return {"guard": {"latest_version": latest_version, "current_version": current_version}}


class TestStudioWriteIsolation:
    """The generic Components API is read-only for Studio-owned records."""

    def test_all_generic_mutations_reject_studio_owned_component_without_corrupting_discovery(
        self, studio_sqlite_client
    ):
        client, db, studio, run_context = studio_sqlite_client
        created = studio.create_agent(
            AgentCreate(
                component_id="studio-agent",
                name="Studio agent",
                instructions="Keep the typed request intact.",
            ),
            _agno_run_context=run_context,
        )
        assert created.ok is True
        assert created.data is not None and created.data.version == 1

        responses = [
            client.patch(
                "/components/studio-agent",
                json={"name": "Generic rename", **_guard(1, None)},
            ),
            client.request(
                "DELETE",
                "/components/studio-agent",
                json=_guard(1, None),
            ),
            client.post(
                "/components/studio-agent/configs",
                json={
                    "config": {
                        "id": "studio-agent",
                        "name": "Raw overwrite",
                        "instructions": "Bypass the typed manifest.",
                    },
                    **_guard(1, None),
                },
            ),
            client.patch(
                "/components/studio-agent/configs/1",
                json={"stage": "published", **_guard(1, None)},
            ),
            client.request(
                "DELETE",
                "/components/studio-agent/configs/1",
                json=_guard(1, None),
            ),
            client.post(
                "/components/studio-agent/configs/1/set-current",
                json=_guard(1, None),
            ),
        ]

        for response in responses:
            assert response.status_code == 409
            assert response.json()["detail"] == "Studio-owned components must be mutated through StudioTools."

        configs = db.list_configs("studio-agent", include_config=True)
        assert [row["version"] for row in configs] == [1]
        assert "_agno_studio" in configs[0]["config"]
        component = db.get_component("studio-agent")
        assert component is not None and component["current_version"] is None

        listed = studio.list_agents(_agno_run_context=run_context)
        assert listed.ok is True
        assert listed.data is not None
        assert [(item.component_id, item.latest_version) for item in listed.data] == [("studio-agent", 1)]

        read_response = client.get("/components/studio-agent/configs/1")
        assert read_response.status_code == 200
        assert "_agno_studio" in read_response.json()["config"]
