from agno.team.remote import RemoteTeam


def test_remote_team_exposes_knowledge_filter_attributes() -> None:
    remote_team = RemoteTeam.__new__(RemoteTeam)
    remote_team.agentos_client = None

    assert remote_team.knowledge_filters is None
    assert remote_team.enable_agentic_knowledge_filters is False
    assert (not remote_team.knowledge_filters and remote_team.knowledge) is None
