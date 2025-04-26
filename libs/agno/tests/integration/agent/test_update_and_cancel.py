import sys,os
import asyncio

sys.path.append('libs/agno')
from agno.agent import Agent, RunResponse
from agno.memory.v2.memory import Memory
from agno.memory.v2.db.sqlite import SqliteMemoryDb
from agno.models.openai import OpenAIChat
from agno.run.response import RunEvent
from agno.storage.agent.sqlite import SqliteAgentStorage

def replace_response( run_response:RunResponse, ai_response:str, update:str ):
    if run_response is None:
        print("[RunResponse] no data")
    x:list[str] = []
    if isinstance(run_response.content,str) and run_response.content==ai_response:
        run_response.content=update
        x.append("run_response.content")
    if isinstance(run_response.messages,list):
        for idx, m in enumerate(run_response.messages):
            if m.content == ai_response:
                m.content = update
                x.append(f"run_response.messages[{idx}]")
    if len(x)>0:
        print(f"[RunResponse]")
        print( "\n".join([f"   {m}" for m in x]) )
        print(f"  Orig  :{ai_response}")
        print(f"  Update:{update}")

def make_agent(dbpath:str|None, session_id:str|None = None) ->Agent:
    db_memory = None
    db_storage = None
    if dbpath:
        db_memory = Memory(
            model=OpenAIChat(id="gpt-4.1-nano"),
            db=SqliteMemoryDb(table_name="user_memories", db_file=dbpath),
        )
        db_storage=SqliteAgentStorage(table_name="agent_sessions", db_file=dbpath)

    agent = Agent(
        session_id=session_id,
        model=OpenAIChat(id="gpt-4o-mini"),
        memory=db_memory,
        storage=db_storage,
        add_history_to_messages=True,
        num_history_runs=5,
        stream_intermediate_steps=True,
        telemetry=False,
    )
    return agent

def agent_run(agent:Agent,inputs) ->bool:
    test_result:bool = True
    for data in inputs:
        user_input, update = data
        print("-------------------")
        print(f"input:{user_input}")
        ai_response = ""
        res_itr = agent.run( user_input, stream=True)
        for run_res in res_itr:
            if run_res.event==RunEvent.run_response:
                ai_response += str(run_res.content)
            elif run_res.event==RunEvent.updating_agent_memory:
                print(f"Event:{run_res.event}")
                if update:
                    replace_response(run_res, ai_response, update)
            else:
                print(f"Event:{run_res.event}")
        if not dump_result(agent,update):
            test_result = False
    return test_result

async def async_agent_run(agent:Agent,inputs) ->bool:
    test_result:bool = True
    for data in inputs:
        user_input, update = data
        print("-------------------")
        print(f"input:{user_input}")
        ai_response = ""
        res_itr = await agent.arun( user_input, stream=True)
        async for run_res in res_itr:
            if run_res.event==RunEvent.run_response:
                ai_response += run_res.content
            elif run_res.event==RunEvent.updating_agent_memory:
                print(f"Event:{run_res.event}")
                if update:
                    replace_response(run_res, ai_response, update)
            else:
                print(f"Event:{run_res.event}")
        if not dump_result(agent,update):
            test_result = False
    return test_result

def dump_result(agent:Agent,update) ->bool:
        print("[RESULT]")
        replaced:bool = False
        if isinstance(agent.memory,Memory) and agent.session_id is not None:
            for m in agent.memory.get_messages_from_last_n_runs(agent.session_id,1):
                print(f"{m.role}:{m.content}" )
                if update and update==m.content:
                    replaced = True
        if update and not replaced:
            print("   NG")
            return False
        else:
            print("   OK")
            return True

def reset_db():
    dbpath='tmp/db/agent_memory.db'
    if os.path.exists(dbpath):
        os.remove( dbpath )
    else:
        os.makedirs( os.path.dirname( dbpath ), exist_ok=True )
    return dbpath

async def test_async_update0(test_data_list):
    """Test with in-memory storage"""
    agent = make_agent(None)
    await async_agent_run(agent, test_data_list)

async def test_async_update1(test_data_list):
    """Test using SQLite"""
    dbpath=reset_db()
    agent = make_agent(dbpath)
    await async_agent_run(agent, test_data_list)

async def test_async_update2(test_data_list):
    """Test using SQLite"""
    dbpath=reset_db()
    session_id=None
    for inp in test_data_list:
        agent = make_agent(dbpath,session_id)
        await async_agent_run(agent, [inp])
        session_id=agent.session_id

def test_update0(test_data_list):
    """Test with in-memory storage"""
    agent = make_agent(None)
    agent_run(agent, test_data_list)

def test_update1(test_data_list):
    """Test using SQLite"""
    dbpath=reset_db()
    agent = make_agent(dbpath)
    agent_run(agent, test_data_list)

def test_update2(test_data_list):
    """Test using SQLite"""
    dbpath=reset_db()
    session_id=None
    for inp in test_data_list:
        agent = make_agent(dbpath,session_id)
        agent_run(agent, [inp])
        session_id=agent.session_id

async def test():
    # test_data_list_jp = [
    #     ('きょうの気分は?','今日の天気は晴れのち曇り，時々雨，ところによっては雪が降るでしょう。'),
    #     ('ごめん、さっき何て言ったの?','')
    # ]
    test_data_list_en = [
        ("How are you feeling today?", "The weather today is sunny with occasional clouds, sometimes rain, and possibly snow in some areas."),
        ("Sorry, what did you just say?", ""),
    ]
    await test_async_update0(test_data_list_en)
    await test_async_update1(test_data_list_en)
    await test_async_update2(test_data_list_en)
    test_update0(test_data_list_en)
    test_update1(test_data_list_en)
    test_update2(test_data_list_en)

if __name__ == "__main__":
    asyncio.run( test() )
