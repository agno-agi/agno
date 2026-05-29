"""
Test Google toolkit explicit agent/run_context parameter pattern.

This validates the new pattern where decorated methods MUST have agent and run_context
as their first two parameters after self:

    @google_authenticate("gmail")
    def get_emails(self, agent: Agent, run_context: RunContext, count: int) -> str:

The framework injects these params automatically (function.py:898-905).
"""

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

import pytest

from agno.run.base import RunContext
from agno.tools import Toolkit
from agno.tools.function import FunctionCall
from agno.tools.google.auth import (
    get_cache_key,
    get_current_creds,
    get_current_service,
    google_authenticate,
)
from agno.tools.google.auth.decorator import _google_context


class MockDb:
    def __init__(self, name: str = "default"):
        self.name = name
        self.access_log: List[Dict[str, Any]] = []

    def get_auth_token(self, provider: str, user_id: str, service: str):
        self.access_log.append({"user_id": user_id, "db_name": self.name})
        return {"token_data": {"access_token": f"token_{user_id}_{self.name}"}}


class MockAgent:
    def __init__(self, db: MockDb):
        self.db = db


class ExplicitParamToolkit(Toolkit):
    """Toolkit using the new explicit agent/run_context pattern."""

    def __init__(self):
        super().__init__(name="explicit_param", tools=[self.do_work])
        self.call_log: List[Dict[str, Any]] = []
        self.resolve_creds_log: List[Dict[str, Any]] = []

    def _resolve_creds(self, run_context: Any = None, agent: Any = None) -> Dict[str, Any]:
        user_id = getattr(run_context, "user_id", None) if run_context else None
        db = agent.db if agent else None
        db_name = db.name if db else None
        self.resolve_creds_log.append({"user_id": user_id, "db_name": db_name})
        return {"user_id": user_id, "db_name": db_name}

    def _build_service(self, creds: Any) -> Dict[str, Any]:
        return {"creds": creds}

    @google_authenticate("explicit")
    def do_work(self, agent: Any, run_context: Any, message: str) -> str:
        """Method with explicit agent/run_context params."""
        service = get_current_service()
        cache_key = get_cache_key()
        user_id = service["creds"]["user_id"] if service else None
        db_name = service["creds"]["db_name"] if service else None
        self.call_log.append(
            {
                "message": message,
                "user_id": user_id,
                "db_name": db_name,
                "cache_key": cache_key,
            }
        )
        return f"Done: {message} for {user_id} via {db_name}"


class TestExplicitParamInjection:
    """Test that explicit params receive framework-injected values."""

    def test_run_context_injected(self):
        """run_context should be injected by framework."""
        toolkit = ExplicitParamToolkit()
        functions = toolkit.get_functions()
        func = functions["do_work"]
        func.process_entrypoint()

        run_context = RunContext(run_id="r1", session_id="s1", user_id="alice")
        func._run_context = run_context

        fc = FunctionCall(function=func, arguments={"message": "test"})
        result = fc.execute()

        assert result.status == "success"
        assert "alice" in result.result
        assert toolkit.resolve_creds_log[-1]["user_id"] == "alice"

    def test_agent_injected(self):
        """agent should be injected by framework."""
        toolkit = ExplicitParamToolkit()
        functions = toolkit.get_functions()
        func = functions["do_work"]
        func.process_entrypoint()

        mock_db = MockDb(name="test_db")
        mock_agent = MockAgent(db=mock_db)
        run_context = RunContext(run_id="r1", session_id="s1", user_id="bob")

        func._run_context = run_context
        func._agent = mock_agent

        fc = FunctionCall(function=func, arguments={"message": "test"})
        result = fc.execute()

        assert result.status == "success"
        assert "test_db" in result.result
        assert toolkit.resolve_creds_log[-1]["db_name"] == "test_db"

    def test_context_reset_after_call(self):
        """ContextVar should be reset after call completes."""
        toolkit = ExplicitParamToolkit()
        functions = toolkit.get_functions()
        func = functions["do_work"]
        func.process_entrypoint()

        run_context = RunContext(run_id="r1", session_id="s1", user_id="test")
        func._run_context = run_context

        fc = FunctionCall(function=func, arguments={"message": "test"})
        fc.execute()

        assert _google_context.get() is None


class TestMultiUserIsolation:
    """Test isolation between concurrent users."""

    def test_sequential_users_isolated(self):
        """Sequential calls should be isolated."""
        toolkit = ExplicitParamToolkit()
        functions = toolkit.get_functions()
        func = functions["do_work"]
        func.process_entrypoint()

        users = ["alice", "bob", "charlie"]
        results = {}

        for user in users:
            mock_db = MockDb(name=f"db_{user}")
            mock_agent = MockAgent(db=mock_db)
            run_context = RunContext(run_id=f"r_{user}", session_id=f"s_{user}", user_id=user)

            func._run_context = run_context
            func._agent = mock_agent

            fc = FunctionCall(function=func, arguments={"message": f"from {user}"})
            result = fc.execute()
            results[user] = result.result

        for user in users:
            assert user in results[user]
            assert f"db_{user}" in results[user]

    def test_concurrent_sync_users_isolated(self):
        """Concurrent sync calls should be isolated."""
        toolkit = ExplicitParamToolkit()
        functions = toolkit.get_functions()
        func = functions["do_work"]
        func.process_entrypoint()

        results = {}
        errors = []

        def run_for_user(user_id: str):
            try:
                mock_db = MockDb(name=f"db_{user_id}")
                mock_agent = MockAgent(db=mock_db)
                run_context = RunContext(run_id=f"r_{user_id}", session_id=f"s_{user_id}", user_id=user_id)

                func._run_context = run_context
                func._agent = mock_agent

                fc = FunctionCall(function=func, arguments={"message": f"from {user_id}"})
                result = fc.execute()
                results[user_id] = result.result
            except Exception as e:
                errors.append((user_id, str(e)))

        users = [f"user_{i}" for i in range(10)]

        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(run_for_user, user) for user in users]
            for future in futures:
                future.result()

        assert len(errors) == 0, f"Errors: {errors}"

        for user in users:
            assert user in results, f"Missing {user}"
            assert user in results[user], f"User {user} not in result"

    @pytest.mark.asyncio
    async def test_concurrent_async_users_isolated(self):
        """Concurrent async calls should be isolated."""
        toolkit = ExplicitParamToolkit()
        functions = toolkit.get_functions()
        func = functions["do_work"]
        func.process_entrypoint()

        results = {}

        async def run_for_user(user_id: str):
            mock_db = MockDb(name=f"db_{user_id}")
            mock_agent = MockAgent(db=mock_db)
            run_context = RunContext(run_id=f"r_{user_id}", session_id=f"s_{user_id}", user_id=user_id)

            func._run_context = run_context
            func._agent = mock_agent

            fc = FunctionCall(function=func, arguments={"message": f"from {user_id}"})
            result = await fc.aexecute()
            results[user_id] = result.result

        users = [f"user_{i}" for i in range(10)]
        await asyncio.gather(*[run_for_user(user) for user in users])

        for user in users:
            assert user in results[user]


class TestNoCredentialLeakage:
    """Test that credentials never leak between users."""

    def test_no_cross_db_access(self):
        """Each user's DB should only be accessed by that user."""
        toolkit = ExplicitParamToolkit()
        functions = toolkit.get_functions()
        func = functions["do_work"]
        func.process_entrypoint()

        user_dbs = {}

        def run_for_user(user_id: str):
            db = MockDb(name=f"db_{user_id}")
            user_dbs[user_id] = db
            mock_agent = MockAgent(db=db)
            run_context = RunContext(run_id=f"r_{user_id}", session_id=f"s_{user_id}", user_id=user_id)

            func._run_context = run_context
            func._agent = mock_agent

            fc = FunctionCall(function=func, arguments={"message": f"from {user_id}"})
            fc.execute()

        users = [f"user_{i}" for i in range(5)]

        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = [executor.submit(run_for_user, user) for user in users]
            for future in futures:
                future.result()

        for user_id, db in user_dbs.items():
            for access in db.access_log:
                assert access["user_id"] == user_id, (
                    f"DB {db.name} accessed by wrong user: expected {user_id}, got {access['user_id']}"
                )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
