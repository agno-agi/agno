"""A deny scope, carried as "!<scope>" next to the allows, overrides every allow, an admin scope included."""

from agno.os.scopes import get_accessible_resource_ids, has_required_scopes, with_denies


def test_with_denies_prefixes_the_denies_and_drops_an_allow_denied_word_for_word():
    assert with_denies(["agents:read", "agent_os:admin"], ["agent_os:admin", "agents:x:run"]) == [
        "agents:read",
        "!agent_os:admin",
        "!agents:x:run",
    ]
    assert with_denies(["agents:read"], None) == ["agents:read"]
    assert with_denies(["agents:read"], "agents:read") == ["agents:read"]


def test_a_deny_on_one_resource_overrides_a_broad_allow():
    scopes = with_denies(["agents:run"], ["agents:secret:run"])
    assert not has_required_scopes(scopes, ["agents:run"], resource_type="agents", resource_id="secret")
    assert has_required_scopes(scopes, ["agents:run"], resource_type="agents", resource_id="other")


def test_a_global_deny_overrides_every_resource():
    scopes = with_denies(["agents:*:run"], ["agents:run"])
    assert not has_required_scopes(scopes, ["agents:run"], resource_type="agents", resource_id="any")


def test_a_deny_overrides_admin():
    scopes = with_denies(["agent_os:admin"], ["sessions:read"])
    assert not has_required_scopes(scopes, ["sessions:read"])
    assert has_required_scopes(scopes, ["agents:read"])


def test_denying_the_admin_scope_takes_admin_away_rather_than_everything():
    scopes = with_denies(["agent_os:admin", "agents:read"], ["agent_os:admin"])
    assert has_required_scopes(scopes, ["agents:read"])
    assert not has_required_scopes(scopes, ["sessions:read"])


def test_listing_drops_denied_resources_where_it_can():
    assert get_accessible_resource_ids(with_denies(["agents:read"], ["agents:read"]), "agents", action="read") == set()
    explicit = with_denies(["agents:a:read", "agents:b:read"], ["agents:b:read"])
    assert get_accessible_resource_ids(explicit, "agents", action="read") == {"a"}
    # Under a wildcard allow the list cannot name an exception; the route check refuses the resource instead
    assert get_accessible_resource_ids(with_denies(["agents:read"], ["agents:b:read"]), "agents", action="read") == {
        "*"
    }


def test_a_deny_for_an_unknown_reader_grants_nothing():
    # Code that does not know the prefix parses "!x" as an unknown scope, which matches nothing
    assert not has_required_scopes(["!agents:read"], ["agents:read"])
