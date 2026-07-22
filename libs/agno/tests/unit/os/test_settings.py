from agno.os.settings import AgnoAPISettings


def test_default_cors_origins_allow_local_agno_os_frontend() -> None:
    origins = AgnoAPISettings().cors_origin_list or []

    assert "http://localhost:8000" in origins
    assert "http://127.0.0.1:8000" in origins
