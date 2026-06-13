from agno.culture.manager import CultureManager
from agno.models.defaults import DEFAULT_OPENAI_MODEL_ID


def test_culture_manager_uses_default_openai_model_id_when_model_is_not_provided():
    manager = CultureManager()

    model = manager.get_model()

    assert model.id == DEFAULT_OPENAI_MODEL_ID
