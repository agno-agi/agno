"""Test V2 User Profile methods across different databases."""

import time
from os import getenv

from agno.db.schemas.user_profile import UserProfile


def test_user_profile_crud(db, db_name: str) -> bool:
    """Test all 4 CRUD operations for user profiles."""
    print(f"\n{'=' * 50}")
    print(f"Testing: {db_name}")
    print("=" * 50)

    user_id = f"test_user_{int(time.time())}"

    try:
        # 1. Create a new profile
        print("\n1. Testing upsert_user_profile (create)...")
        profile = UserProfile(
            user_id=user_id,
            user_profile={"name": "John Doe", "role": "Engineer"},
            memory_layers={"policies": {"tone": "professional"}, "knowledge": []},
            metadata={"source": "test"},
        )
        result = db.upsert_user_profile(profile)
        assert result is not None, "upsert_user_profile returned None"
        assert result.user_id == user_id, "user_id mismatch"
        print("   PASS: Profile created successfully")

        # 2. Get the profile
        print("\n2. Testing get_user_profile...")
        fetched = db.get_user_profile(user_id)
        assert fetched is not None, "get_user_profile returned None"
        assert fetched.user_id == user_id, "user_id mismatch"
        assert fetched.user_profile["name"] == "John Doe", "user_profile data mismatch"
        print("   PASS: Profile retrieved successfully")

        # 3. Update the profile
        print("\n3. Testing upsert_user_profile (update)...")
        profile.user_profile["name"] = "Jane Doe"
        profile.memory_layers["knowledge"] = [{"fact": "Likes Python"}]
        updated = db.upsert_user_profile(profile)
        assert updated is not None, "upsert_user_profile (update) returned None"
        assert updated.user_profile["name"] == "Jane Doe", "update failed"
        print("   PASS: Profile updated successfully")

        # 4. Get all profiles
        print("\n4. Testing get_user_profiles...")
        profiles = db.get_user_profiles(limit=10)
        assert isinstance(profiles, list), "get_user_profiles should return a list"
        assert len(profiles) >= 1, "Should have at least 1 profile"
        print(f"   PASS: Retrieved {len(profiles)} profile(s)")

        # 5. Delete the profile
        print("\n5. Testing delete_user_profile...")
        db.delete_user_profile(user_id)
        print("   PASS: Profile deleted")

        # 6. Verify deletion
        print("\n6. Verifying deletion...")
        deleted = db.get_user_profile(user_id)
        assert deleted is None, "Profile should be deleted"
        print("   PASS: Profile confirmed deleted")

        print(f"\n[PASS] {db_name} - All methods working correctly")
        return True

    except Exception as e:
        print(f"\n[FAIL] {db_name} - Error: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_sqlite():
    """Test SQLite database."""
    from agno.db.sqlite import SqliteDb

    db = SqliteDb(db_file="tmp/test_user_profiles.db")
    return test_user_profile_crud(db, "SQLite")


def test_inmemory():
    """Test InMemory database."""
    from agno.db.in_memory import InMemoryDb

    db = InMemoryDb()
    return test_user_profile_crud(db, "InMemoryDb")


def test_jsondb():
    """Test JsonDb database."""
    from agno.db.json import JsonDb

    db = JsonDb(db_path="tmp/test_json_db")
    return test_user_profile_crud(db, "JsonDb")


def test_postgres():
    """Test PostgreSQL database."""
    db_url = getenv("DATABASE_URL")
    if not db_url:
        print("\n[SKIP] PostgreSQL - DATABASE_URL not set")
        return None

    from agno.db.postgres import PostgresDb

    db = PostgresDb(db_url=db_url)
    return test_user_profile_crud(db, "PostgreSQL")


def test_mysql():
    """Test MySQL database."""
    db_url = getenv("MYSQL_URL")
    if not db_url:
        print("\n[SKIP] MySQL - MYSQL_URL not set")
        return None

    from agno.db.mysql import MySQLDb

    db = MySQLDb(db_url=db_url)
    return test_user_profile_crud(db, "MySQL")


def test_mongodb():
    """Test MongoDB database."""
    db_url = getenv("MONGODB_URL")
    if not db_url:
        print("\n[SKIP] MongoDB - MONGODB_URL not set")
        return None

    from agno.db.mongo import MongoDb

    db = MongoDb(db_url=db_url, db_name="agno_test")
    return test_user_profile_crud(db, "MongoDB")


def test_redis():
    """Test Redis database."""
    db_url = getenv("REDIS_URL")
    if not db_url:
        print("\n[SKIP] Redis - REDIS_URL not set")
        return None

    from agno.db.redis import RedisDb

    db = RedisDb(db_url=db_url)
    return test_user_profile_crud(db, "Redis")


def test_firestore():
    """Test Firestore database."""
    project_id = getenv("GOOGLE_CLOUD_PROJECT")
    if not project_id:
        print("\n[SKIP] Firestore - GOOGLE_CLOUD_PROJECT not set")
        return None

    from agno.db.firestore import FirestoreDb

    db = FirestoreDb(project_id=project_id)
    return test_user_profile_crud(db, "Firestore")


def test_dynamodb():
    """Test DynamoDB database."""
    if not getenv("AWS_ACCESS_KEY_ID"):
        print("\n[SKIP] DynamoDB - AWS credentials not set")
        return None

    from agno.db.dynamo import DynamoDb

    db = DynamoDb(region_name=getenv("AWS_REGION", "us-east-1"))
    return test_user_profile_crud(db, "DynamoDB")


def test_singlestore():
    """Test SingleStore database."""
    db_url = getenv("SINGLESTORE_URL")
    if not db_url:
        print("\n[SKIP] SingleStore - SINGLESTORE_URL not set")
        return None

    from agno.db.singlestore import SingleStoreDb

    db = SingleStoreDb(db_url=db_url)
    return test_user_profile_crud(db, "SingleStore")


def test_surrealdb():
    """Test SurrealDB database."""
    db_url = getenv("SURREALDB_URL")
    if not db_url:
        print("\n[SKIP] SurrealDB - SURREALDB_URL not set")
        return None

    from agno.db.surrealdb import SurrealDb

    db = SurrealDb(client=None, db_url=db_url, namespace="test", database="test")
    return test_user_profile_crud(db, "SurrealDB")


def test_gcs_jsondb():
    """Test GCS JsonDb database."""
    bucket_name = getenv("GCS_BUCKET_NAME")
    if not bucket_name:
        print("\n[SKIP] GcsJsonDb - GCS_BUCKET_NAME not set")
        return None

    from agno.db.gcs_json import GcsJsonDb

    db = GcsJsonDb(bucket_name=bucket_name)
    return test_user_profile_crud(db, "GcsJsonDb")


if __name__ == "__main__":
    print("Testing V2 User Profile Methods")
    print("=" * 50)

    results = {
        "passed": [],
        "failed": [],
        "skipped": [],
    }

    # Test each database
    tests = [
        ("SQLite", test_sqlite),
        ("InMemoryDb", test_inmemory),
        ("JsonDb", test_jsondb),
        ("PostgreSQL", test_postgres),
        ("MySQL", test_mysql),
        ("MongoDB", test_mongodb),
        ("Redis", test_redis),
        ("Firestore", test_firestore),
        ("DynamoDB", test_dynamodb),
        ("SingleStore", test_singlestore),
        ("SurrealDB", test_surrealdb),
        ("GcsJsonDb", test_gcs_jsondb),
    ]

    for name, test_fn in tests:
        try:
            result = test_fn()
            if result is True:
                results["passed"].append(name)
            elif result is False:
                results["failed"].append(name)
            else:
                results["skipped"].append(name)
        except Exception as e:
            print(f"\n[ERROR] {name} - Unexpected error: {e}")
            results["failed"].append(name)

    # Print summary
    print("\n" + "=" * 50)
    print("SUMMARY")
    print("=" * 50)
    print(
        f"Passed:  {len(results['passed'])} - {', '.join(results['passed']) or 'None'}"
    )
    print(
        f"Failed:  {len(results['failed'])} - {', '.join(results['failed']) or 'None'}"
    )
    print(
        f"Skipped: {len(results['skipped'])} - {', '.join(results['skipped']) or 'None'}"
    )
