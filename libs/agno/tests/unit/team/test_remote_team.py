from agno.team.remote import RemoteTeam


def test_remote_team_exposes_knowledge_filter_attributes() -> None:
    remote_team = RemoteTeam.__new__(RemoteTeam)
    remote_team.agentos_client = None

    assert remote_team.knowledge_filters is None
    assert remote_team.enable_agentic_knowledge_filters is False
    assert (not remote_team.knowledge_filters and remote_team.knowledge) is None


def test_remote_team_targets_remote_interface() -> None:
    remote_team = RemoteTeam(base_url="http://fake-host/", team_id="test_team")

    assert remote_team.base_url == "http://fake-host"
    assert remote_team.api_prefix == "/remote"


def test_remote_team_custom_api_prefix() -> None:
    remote_team = RemoteTeam(base_url="http://fake-host", team_id="test_team", api_prefix="custom-remote/")

    assert remote_team.api_prefix == "/custom-remote"
