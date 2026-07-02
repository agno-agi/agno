from agno.learn.config import UserProfileConfig
from agno.learn.schemas import UserProfile
from agno.learn.stores.user_profile import UserProfileStore


def test_update_profile_tool_skips_unchanged_values(mocker):
    store = UserProfileStore(config=UserProfileConfig())

    existing = UserProfile(user_id="u1", name="Alice")
    save_spy = mocker.patch.object(store, "save")
    mocker.patch.object(store, "get", return_value=existing)

    update_tool = store._build_update_profile_tool(user_id="u1")
    assert update_tool is not None

    result = update_tool(name="Alice")

    assert result == "No fields provided to update"
    save_spy.assert_not_called()


def test_update_profile_tool_updates_when_value_changes(mocker):
    store = UserProfileStore(config=UserProfileConfig())

    existing = UserProfile(user_id="u1", name="Alice")
    save_spy = mocker.patch.object(store, "save")
    mocker.patch.object(store, "get", return_value=existing)

    update_tool = store._build_update_profile_tool(user_id="u1")
    assert update_tool is not None

    result = update_tool(name="Alicia")

    assert result == "Profile updated: name=Alicia"
    save_spy.assert_called_once()


async def test_async_update_profile_tool_skips_unchanged_values(mocker):
    store = UserProfileStore(config=UserProfileConfig())

    existing = UserProfile(user_id="u1", preferred_name="Ali")
    asave_spy = mocker.patch.object(store, "asave")
    mocker.patch.object(store, "aget", mocker.AsyncMock(return_value=existing))

    update_tool = await store._abuild_update_profile_tool(user_id="u1")
    assert update_tool is not None

    result = await update_tool(preferred_name="Ali")

    assert result == "No fields provided to update"
    asave_spy.assert_not_called()
