"""
Manage Company Products
=======================

Create Products, scope reads by owner, soft-delete and restore.

Prerequisites: Install Agno and sqlalchemy in the development environment.
Run: .venv/bin/python cookbook/05_agent_os/30_company/01_manage_products.py
Try: Change user_id, page, limit and include_deleted in the manager calls.
"""

from tempfile import TemporaryDirectory

from agno.company import CompanyManager
from agno.db.sqlite import SqliteDb

if __name__ == "__main__":
    with TemporaryDirectory() as directory:
        db = SqliteDb(db_file=directory + "/company.db")
        manager = CompanyManager(db)
        sdk = manager.create(name="SDK", purpose="Build the framework", user_id="alice")
        manager.create(
            name="Documentation", purpose="Teach the framework", user_id="bob"
        )

        products, total = manager.list()
        assert total == 2
        print(f"Isolation off: {total} Products")
        products, total = manager.list(user_id="alice")
        assert total == 1 and products[0]["id"] == sdk["id"]
        print(f"Isolation on for alice: {total} Product")

        assert manager.delete(sdk["id"], user_id="alice")
        assert manager.get(sdk["id"], user_id="alice") is None
        deleted = manager.get(sdk["id"], user_id="alice", include_deleted=True)
        assert deleted is not None and deleted["deleted_at"] is not None
        restored = manager.restore(sdk["id"], user_id="alice")
        assert restored is not None and restored["deleted_at"] is None
        print("Soft delete, include_deleted and restore passed")
        db.close()
