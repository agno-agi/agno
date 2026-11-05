"""Skills through the component routes: stored as components, and linked from the agents and teams that use them."""

from typing import Any, Dict, Optional

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agno.db.sqlite import SqliteDb
from agno.os.routers.components import get_components_router
from agno.os.settings import AgnoAPISettings
from agno.skills import Skill


@pytest.fixture
def db(tmp_path) -> SqliteDb:
    db = SqliteDb(id="components-skills-db", db_file=str(tmp_path / "components_skills.db"))
    Skill(
        name="pdf-extract",
        description="Extract text from PDFs",
        instructions="Read the PDF",
        script_contents={},
        reference_contents={},
    ).save(db=db)
    return db


@pytest.fixture
def client(db) -> TestClient:
    app = FastAPI()
    app.include_router(get_components_router(os_db=db, settings=AgnoAPISettings()))
    return TestClient(app)


def agent_body(component_id: str, skill_ref: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    config: Dict[str, Any] = {"name": component_id, "id": component_id}
    if skill_ref is not None:
        config["skills"] = {"refs": [skill_ref]}
    return {
        "name": component_id,
        "component_id": component_id,
        "component_type": "agent",
        "config": config,
        "stage": "published",
    }


def skill_links(db: SqliteDb, component_id: str, version: int = 1):
    return [
        (row["child_component_id"], row["child_version"])
        for row in db.get_links(component_id=component_id, version=version)
        if row["link_kind"] == "skill"
    ]


def test_list_filters_by_skill_type(client):
    response = client.get("/components", params={"component_type": "skill"})

    assert response.status_code == 200, response.text
    assert [row["component_id"] for row in response.json()["data"]] == ["pdf-extract"]


def test_create_agent_links_and_pins_its_skills(client, db):
    response = client.post("/components", json=agent_body("a1", {"skill_id": "pdf-extract"}))

    assert response.status_code == 201, response.text
    assert skill_links(db, "a1") == [("pdf-extract", 1)]
    assert db.get_config("a1")["config"]["skills"] == {"refs": [{"skill_id": "pdf-extract", "version": 1}]}


def test_create_agent_with_unknown_skill_is_a_400(client, db):
    response = client.post("/components", json=agent_body("a1", {"skill_id": "nope"}))

    assert response.status_code == 400
    assert db.get_component("a1") is None


def test_new_config_version_derives_skill_links(client, db):
    assert client.post("/components", json=agent_body("a1", None)).status_code == 201

    response = client.post(
        "/components/a1/configs",
        json={
            "config": {
                "name": "a1",
                "id": "a1",
                "skills": {"refs": [{"skill_id": "pdf-extract", "version": "latest"}]},
            },
            "stage": "published",
        },
    )

    assert response.status_code == 201, response.text
    assert skill_links(db, "a1", response.json()["version"]) == [("pdf-extract", None)]


def test_referenced_skill_cannot_be_archived(client):
    assert client.post("/components", json=agent_body("a1", {"skill_id": "pdf-extract"})).status_code == 201

    assert client.delete("/components/pdf-extract").status_code == 409
