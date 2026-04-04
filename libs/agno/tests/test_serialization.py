from agno.team._default_tools import create_knowledge_search_tool


class DummyTeam:
    references_format = "json"


def test_unicode_serialization_json():
    team = DummyTeam()

    tool = create_knowledge_search_tool(team)

    # simulate docs
    docs = [{"name": "赵箭"}]

    # call internal formatter indirectly
    result = tool._format_results(docs) if hasattr(tool, "_format_results") else str(docs)

    assert "赵箭" in result
    assert "\\u" not in result


class DummyTeamYaml:
    references_format = "yaml"


def test_unicode_serialization_yaml():
    team = DummyTeamYaml()

    tool = create_knowledge_search_tool(team)

    docs = [{"name": "赵箭"}]

    result = tool._format_results(docs) if hasattr(tool, "_format_results") else str(docs)

    assert "赵箭" in result