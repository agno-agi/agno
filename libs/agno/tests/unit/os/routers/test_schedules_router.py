async def test_get_db_selects_matching_db_id(tmp_path):
    from agno.db.sqlite import SqliteDb
    from agno.os.routers.schedules.router import get_db

    agent_db = SqliteDb(db_file=str(tmp_path / "agent.db"), id="agent-db")
    os_db = SqliteDb(db_file=str(tmp_path / "os.db"), id="os-db")

    dbs = {
        agent_db.id: [agent_db],
        os_db.id: [os_db],
    }

    # Without specifying db_id, get_db returns the first sync DB it sees.
    selected_default = await get_db(dbs)
    assert selected_default is agent_db

    # With db_id, get_db consistently returns the matching DB.
    selected = await get_db(dbs, db_id=os_db.id)
    assert selected is os_db
