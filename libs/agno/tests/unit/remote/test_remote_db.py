from agno.os.config import (
    DatabaseConfig,
    LearningConfig,
    LearningDomainConfig,
    SessionConfig,
    SessionDomainConfig,
)
from agno.os.schema import ConfigResponse
from agno.remote.base import RemoteDb


def test_remote_db_from_config_includes_learning_table_name() -> None:
    config = ConfigResponse(
        os_id="remote-os",
        databases=["remote-db"],
        session=SessionConfig(
            dbs=[
                DatabaseConfig(
                    db_id="remote-db",
                    domain_config=SessionDomainConfig(display_name="remote-db"),
                    tables=["remote_sessions"],
                )
            ]
        ),
        learning=LearningConfig(
            dbs=[
                DatabaseConfig(
                    db_id="remote-db",
                    domain_config=LearningDomainConfig(display_name="remote-db"),
                    tables=["remote_learnings"],
                )
            ]
        ),
        agents=[],
        teams=[],
        workflows=[],
        interfaces=[],
    )

    remote_db = RemoteDb.from_config(
        db_id="remote-db",
        client=object(),  # type: ignore[arg-type]
        config=config,
    )

    assert remote_db is not None
    assert remote_db.session_table_name == "remote_sessions"
    assert remote_db.learnings_table_name == "remote_learnings"
