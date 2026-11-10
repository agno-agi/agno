"""Every surface that persists a workflow config derives the same component
links.

The SDK save walks live step objects; the REST config routes walk the
serialized config. Both feed the same archive and publish guards, so a
disagreement over link_kind, link_key or position means the same workflow pins
different children depending on how it was written.
"""

from typing import Any, Dict, List, Optional

import pytest

from agno.agent.agent import Agent
from agno.db.base import ComponentType
from agno.db.sqlite import SqliteDb
from agno.workflow.condition import Condition
from agno.workflow.step import Step
from agno.workflow.workflow import Workflow, WorkflowLinkCollisionError, derive_step_links


def link_shape(links: List[Dict[str, Any]]) -> List[tuple]:
    return sorted(
        (
            link.get("link_kind"),
            link.get("link_key"),
            link.get("child_component_id"),
            link.get("child_version"),
            link.get("position"),
        )
        for link in links
    )


def derive_from_config(config: Dict[str, Any], db: Any) -> List[Dict[str, Any]]:
    """Derive links from a serialized config the way the REST routes do."""

    def pin_child(link: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        child = db.get_component(link.get("child_component_id"))
        if child is None or child.get("current_version") is None:
            return None
        link["child_version"] = child["current_version"]
        return link

    return derive_step_links(config.get("steps"), pin_child=pin_child, workflow_id=config.get("id"))


class TestSharedStepWalker:
    def test_config_walk_matches_the_save_walk(self, tmp_path):
        """The serialized config and the live objects must produce one answer:
        the archive and publish guards read whichever rows got written."""
        db = SqliteDb(db_file=str(tmp_path / "walker.db"))
        if_agent = Agent(id="if-agent", name="If Agent")
        else_agent = Agent(id="else-agent", name="Else Agent")
        plain_agent = Agent(id="plain-agent", name="Plain Agent")
        workflow = Workflow(
            id="walk-wf",
            name="walk wf",
            steps=[
                Step(name="plain", agent=plain_agent),
                Condition(
                    name="cond",
                    evaluator=True,
                    steps=[Step(name="branch", agent=if_agent)],
                    else_steps=[Step(name="branch", agent=else_agent)],
                ),
            ],
        )

        version = workflow.save(db=db, stage="published")
        assert version is not None
        saved_links = db.get_links(component_id="walk-wf", version=version)

        derived = derive_from_config(workflow.to_dict(), db)

        assert link_shape(derived) == link_shape(saved_links)
        # The else branch must not collide with the if branch on one key.
        keys = {link["link_key"] for link in derived}
        assert len([key for key in keys if key.endswith("#else")]) == 1

    def test_two_steps_with_one_key_and_different_children_are_refused(self, tmp_path):
        db = SqliteDb(db_file=str(tmp_path / "collide.db"))
        for agent_id in ("a-one", "a-two"):
            db.create_component_with_config(
                component_id=agent_id,
                component_type=ComponentType.AGENT,
                name=agent_id,
                config={"id": agent_id},
                stage="published",
            )
        config = {
            "id": "collide-wf",
            "steps": [
                {"type": "Step", "name": "dupe", "step_id": "dupe", "agent_id": "a-one"},
                {"type": "Step", "name": "dupe", "step_id": "dupe", "agent_id": "a-two"},
            ],
        }

        with pytest.raises(WorkflowLinkCollisionError):
            derive_from_config(config, db)

    def test_router_choices_and_nested_containers_are_walked(self, tmp_path):
        db = SqliteDb(db_file=str(tmp_path / "router.db"))
        for agent_id in ("routed-agent", "looped-agent"):
            db.create_component_with_config(
                component_id=agent_id,
                component_type=ComponentType.AGENT,
                name=agent_id,
                config={"id": agent_id},
                stage="published",
            )
        config = {
            "id": "router-wf",
            "steps": [
                {
                    "type": "Router",
                    "name": "r",
                    "choices": [{"type": "Step", "name": "routed", "step_id": "routed", "agent_id": "routed-agent"}],
                },
                {
                    "type": "Loop",
                    "name": "l",
                    "steps": [{"type": "Step", "name": "looped", "step_id": "looped", "agent_id": "looped-agent"}],
                },
            ],
        }

        derived = derive_from_config(config, db)

        assert link_shape(derived) == [
            ("step_agent", "looped", "looped-agent", 1, 0),
            ("step_agent", "routed", "routed-agent", 1, 0),
        ]
