"""A db's generated id is its identity: everything that tells two databases
apart (registry dedup, stored-config resolution, the catalog fallback guard,
Studio's shared-machine disclosure) keys on it. The seed expressions used to
bind the conditional over the whole or-chain, so without an engine every
instance seeded from the literal default and physically different databases
shared one id. These tests pin the corrected seeding: distinct targets get
distinct ids, the same target keeps getting the same id.

An adapter given a client object seeds from the address the client connects
to: str(client) holds memory addresses, so its id changed on every restart.

Cases that need an optional driver skip without it; CI installs the extras
and runs them.
"""

from importlib import import_module
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from agno.db.sqlite import SqliteDb
from agno.utils.string import generate_id


class TestSqliteIdSeeding:
    def test_different_files_get_different_ids(self, tmp_path):
        a = SqliteDb(db_file=str(tmp_path / "components.db"))
        b = SqliteDb(db_file=str(tmp_path / "learning.db"))
        assert a.id != b.id

    def test_same_target_gets_the_same_id(self, tmp_path):
        path = str(tmp_path / "shared.db")
        assert SqliteDb(db_file=path).id == SqliteDb(db_file=path).id
        # The no-argument default is one shared target, so one shared id.
        assert SqliteDb().id == SqliteDb().id

    def test_url_seeds_and_differs_from_the_default(self, tmp_path):
        by_url = SqliteDb(db_url="sqlite:///" + str(tmp_path / "learning.db"))
        assert by_url.id != SqliteDb().id
        assert by_url.id != SqliteDb(db_file=str(tmp_path / "components.db")).id

    def test_explicit_id_wins(self, tmp_path):
        assert SqliteDb(id="mine", db_file=str(tmp_path / "x.db")).id == "mine"


class TestAsyncSqliteIdSeeding:
    def test_different_files_get_different_ids(self, tmp_path):
        pytest.importorskip("aiosqlite")
        from agno.db.sqlite.async_sqlite import AsyncSqliteDb

        a = AsyncSqliteDb(db_file=str(tmp_path / "components.db"))
        b = AsyncSqliteDb(db_file=str(tmp_path / "learning.db"))
        assert a.id != b.id
        assert AsyncSqliteDb(db_file=str(tmp_path / "components.db")).id == a.id


class TestMySQLAndSingleStoreIdSeeding:
    def test_async_mysql_url_seeds_the_id(self):
        pytest.importorskip("aiomysql")
        from agno.db.mysql.async_mysql import AsyncMySQLDb

        a = AsyncMySQLDb(db_url="mysql+aiomysql://u:p@h:3306/one", session_table="s")
        b = AsyncMySQLDb(db_url="mysql+aiomysql://u:p@h:3306/two", session_table="s")
        assert a.id != b.id
        assert AsyncMySQLDb(db_url="mysql+aiomysql://u:p@h:3306/one", session_table="s").id == a.id

    def test_singlestore_url_seeds_the_id(self):
        pytest.importorskip("pymysql")
        from agno.db.singlestore.singlestore import SingleStoreDb

        a = SingleStoreDb(db_url="mysql+pymysql://u:p@h:3306/one", session_table="s")
        b = SingleStoreDb(db_url="mysql+pymysql://u:p@h:3306/two", session_table="s")
        assert a.id != b.id


class TestAsyncPostgresIdSeeding:
    @pytest.mark.parametrize("schema", [None, "ai", "company"])
    def test_same_url_and_schema_match_sync_and_replica(self, schema):
        from agno.db.postgres import AsyncPostgresDb, PostgresDb

        url = "postgresql+psycopg://user:password@localhost/company"
        first = AsyncPostgresDb(db_url=url, db_schema=schema)
        assert AsyncPostgresDb(db_url=url, db_schema=schema).id == first.id
        assert PostgresDb(db_url=url, db_schema=schema).id == first.id
        assert AsyncPostgresDb(db_url=url, db_schema="other").id != first.id
        assert AsyncPostgresDb(db_url=url + "_other", db_schema=schema).id != first.id
        assert AsyncPostgresDb(db_url=url, id="explicit").id == "explicit"

    def test_engine_seed_and_default_schema(self):
        from sqlalchemy import create_engine
        from sqlalchemy.ext.asyncio import create_async_engine

        from agno.db.postgres import AsyncPostgresDb, PostgresDb

        url = "postgresql+psycopg://user:password@localhost/company"
        engine = create_async_engine(url)
        first = AsyncPostgresDb(db_engine=engine)
        assert first.id == AsyncPostgresDb(db_engine=engine, db_schema="ai").id
        assert first.id == PostgresDb(db_engine=create_engine(url)).id
        assert AsyncPostgresDb(db_engine=engine, id="explicit").id == "explicit"


@pytest.mark.parametrize("source", ["file", "url", "engine", "default"])
def test_async_sqlite_stable_id_and_explicit_override(tmp_path, source):
    from sqlalchemy.ext.asyncio import create_async_engine

    from agno.db.sqlite import AsyncSqliteDb

    path = str(tmp_path / "history.db")
    options = {
        "file": {"db_file": path},
        "url": {"db_url": "sqlite+aiosqlite:///" + path},
        "engine": {"db_engine": create_async_engine("sqlite+aiosqlite:///" + path)},
        "default": {},
    }[source]
    assert AsyncSqliteDb(**options).id == AsyncSqliteDb(**options).id
    assert AsyncSqliteDb(id="explicit", **options).id == "explicit"


def _seeds(adapter_module: str):
    """Patch generate_id in an adapter module and record every seed it receives."""
    seeds: list = []
    return seeds, patch(f"{adapter_module}.generate_id", side_effect=lambda s: seeds.append(s) or generate_id(s))


class TestRedisClientIdSeeding:
    @pytest.fixture(autouse=True)
    def _driver(self):
        pytest.importorskip("redis")

    def test_same_address_gets_the_same_id(self):
        from redis import Redis

        from agno.db.redis import RedisDb

        tcp = RedisDb(redis_client=Redis(host="h1", port=6380, db=2)).id
        assert RedisDb(redis_client=Redis(host="h1", port=6380, db=2)).id == tcp
        unix = RedisDb(redis_client=Redis(unix_socket_path="/tmp/r.sock", db=1)).id
        assert RedisDb(redis_client=Redis(unix_socket_path="/tmp/r.sock", db=1)).id == unix

    def test_different_addresses_get_different_ids(self):
        from redis import Redis

        from agno.db.redis import RedisDb

        clients = [
            Redis(host="h1", port=6380, db=2),
            Redis(host="h2", port=6380, db=2),
            Redis(host="h1", port=6381, db=2),
            Redis(host="h1", port=6380, db=3),
            Redis(unix_socket_path="/tmp/a.sock"),
            Redis(unix_socket_path="/tmp/b.sock"),
        ]
        assert len({RedisDb(redis_client=c).id for c in clients}) == len(clients)

    def test_cluster_seeds_from_its_nodes_in_any_order(self):
        from redis.cluster import ClusterNode, RedisCluster

        from agno.db.redis import RedisDb

        def cluster(*nodes):
            # RedisCluster.__init__ connects to the cluster; the id only needs the nodes it was given.
            client = RedisCluster.__new__(RedisCluster)
            client.startup_nodes = [ClusterNode(host, port) for host, port in nodes]
            return client

        first = RedisDb(redis_client=cluster(("a", 7001), ("b", 7002))).id
        assert RedisDb(redis_client=cluster(("b", 7002), ("a", 7001))).id == first
        assert RedisDb(redis_client=cluster(("a", 7001), ("c", 7003))).id != first

        # A redis-py release without startup_nodes falls back instead of failing the constructor.
        bare = RedisCluster.__new__(RedisCluster)
        with patch("agno.db.utils.log_warning") as warn:
            assert RedisDb(redis_client=bare).id == generate_id(f"{bare}#agno")
        warn.assert_called_once()

    def test_url_without_a_port_matches_the_default_port(self):
        from redis import Redis

        from agno.db.redis import RedisDb

        # from_url leaves the port out of connection_kwargs when the URL has none.
        assert RedisDb(redis_client=Redis.from_url("redis://h1")).id == RedisDb(redis_client=Redis(host="h1")).id

    def test_unchanged_ids_url_sentinel_and_explicit(self):
        from redis import Redis
        from redis.sentinel import Sentinel

        from agno.db.redis import RedisDb

        assert RedisDb(db_url="redis://localhost:6379/0").id == "96232289-9272-5841-b312-3b4dc1579d34"
        with patch("agno.db.utils.log_warning") as warn:
            sentinel = RedisDb(redis_client=Sentinel([("localhost", 26379)]).master_for("mymaster"))
        # A Sentinel client's str() has no memory address, so its id was already stable.
        assert sentinel.id == "fa9203f5-ca5a-53f5-952b-fbbd5190c171"
        warn.assert_not_called()
        assert RedisDb(redis_client=Redis(host="h1"), id="mine").id == "mine"

    def test_password_never_reaches_the_seed(self):
        from redis import Redis

        from agno.db.redis import RedisDb

        seeds, recording = _seeds("agno.db.redis.redis")
        with recording:
            RedisDb(redis_client=Redis(host="h1", username="alice", password="hunter2"))
        assert seeds and "hunter2" not in seeds[0] and "alice" not in seeds[0]

    def test_unreadable_client_keeps_todays_id_and_warns(self):
        from agno.db.redis import RedisDb

        client = object()
        with patch("agno.db.utils.log_warning") as warn:
            db = RedisDb(redis_client=client)
        assert db.id == generate_id(f"{client}#agno")
        warn.assert_called_once()


class TestValkeyClientIdSeeding:
    @pytest.fixture(autouse=True)
    def _driver(self):
        pytest.importorskip("glide_sync")

    @staticmethod
    def glide(cls, *addresses, database_id=None):
        """A GLIDE client without a connection; each address is (host, port) or a unix socket path."""
        # GLIDE clients connect on create(); the id only needs the configuration the client keeps.
        # Like GLIDE's NodeAddress, a socket address keeps the default host and port alongside its path.
        client = cls.__new__(cls)
        client._config = SimpleNamespace(
            addresses=[
                SimpleNamespace(host=a[0], port=a[1], unix_socket_path=None)
                if isinstance(a, tuple)
                else SimpleNamespace(host="localhost", port=6379, unix_socket_path=a)
                for a in addresses
            ],
            database_id=database_id,
        )
        return client

    def test_same_address_gets_the_same_id(self):
        from glide_sync import GlideClient, GlideClusterClient

        from agno.db.valkey import ValkeyDb

        single = ValkeyDb(valkey_client=self.glide(GlideClient, ("h1", 6379), database_id=2)).id
        assert ValkeyDb(valkey_client=self.glide(GlideClient, ("h1", 6379), database_id=2)).id == single
        cluster = ValkeyDb(valkey_client=self.glide(GlideClusterClient, ("a", 7001), ("b", 7002))).id
        assert ValkeyDb(valkey_client=self.glide(GlideClusterClient, ("b", 7002), ("a", 7001))).id == cluster

    def test_different_addresses_get_different_ids(self):
        from glide_sync import GlideClient, GlideClusterClient

        from agno.db.valkey import ValkeyDb

        clients = [
            self.glide(GlideClient, ("h1", 6379)),
            self.glide(GlideClient, ("h2", 6379)),
            self.glide(GlideClient, ("h1", 6380)),
            self.glide(GlideClient, ("h1", 6379), database_id=3),
            self.glide(GlideClusterClient, ("h1", 6379)),
            self.glide(GlideClusterClient, ("a", 7001), ("c", 7003)),
            self.glide(GlideClient, ("localhost", 6379)),
            self.glide(GlideClient, "/run/a.sock"),
            self.glide(GlideClient, "/run/b.sock"),
            self.glide(GlideClusterClient, ("a", 7001), database_id=1),
            self.glide(GlideClusterClient, ("a", 7001), database_id=2),
        ]
        assert len({ValkeyDb(valkey_client=c).id for c in clients}) == len(clients)

    def test_unchanged_ids_host_port_and_explicit(self):
        from glide_sync import GlideClient

        from agno.db.valkey import ValkeyDb

        with patch("agno.db.valkey.valkey.GlideClient.create"):
            assert ValkeyDb(host="localhost", port=6379).id == "7aecbdf7-f87f-5a1e-be6f-307e4aec71e8"
        assert ValkeyDb(valkey_client=self.glide(GlideClient, ("h1", 6379)), id="mine").id == "mine"

    def test_client_without_config_keeps_todays_id_and_warns(self):
        from glide_sync import GlideClient

        from agno.db.valkey import ValkeyDb

        client = GlideClient.__new__(GlideClient)
        with patch("agno.db.utils.log_warning") as warn:
            db = ValkeyDb(valkey_client=client)
        assert db.id == generate_id(f"{client}#agno")
        warn.assert_called_once()


class TestDynamoClientIdSeeding:
    @pytest.fixture(autouse=True)
    def _driver(self):
        pytest.importorskip("boto3")

    @staticmethod
    def client(region="us-east-1", endpoint_url=None, key="AKIDEXAMPLE"):
        import boto3

        return boto3.client(
            "dynamodb",
            region_name=region,
            endpoint_url=endpoint_url,
            aws_access_key_id=key,
            aws_secret_access_key="secret-example",
        )

    def test_same_region_and_endpoint_get_the_same_id(self):
        from agno.db.dynamo import DynamoDb

        assert DynamoDb(db_client=self.client()).id == DynamoDb(db_client=self.client()).id
        local = DynamoDb(db_client=self.client(endpoint_url="http://localhost:8000")).id
        assert DynamoDb(db_client=self.client(endpoint_url="http://localhost:8000")).id == local

    def test_different_region_or_endpoint_get_different_ids(self):
        from agno.db.dynamo import DynamoDb

        ids = {
            DynamoDb(db_client=self.client()).id,
            DynamoDb(db_client=self.client(region="eu-west-1")).id,
            DynamoDb(db_client=self.client(endpoint_url="http://localhost:8000")).id,
        }
        assert len(ids) == 3

    def test_access_key_never_reaches_the_seed(self):
        from agno.db.dynamo import DynamoDb

        seeds, recording = _seeds("agno.db.dynamo.dynamo")
        with recording:
            DynamoDb(db_client=self.client(key="AKIDSECRETKEY"))
        assert seeds and "AKIDSECRETKEY" not in seeds[0] and "secret-example" not in seeds[0]

    def test_endpoint_credentials_never_reach_the_seed(self):
        from agno.db.dynamo import DynamoDb

        seeds, recording = _seeds("agno.db.dynamo.dynamo")
        with recording:
            # botocore keeps user:password in meta.endpoint_url when the endpoint URL carries them.
            with_login = DynamoDb(db_client=self.client(endpoint_url="https://admin:secretpw@dynamo.example.com")).id
        assert seeds and "secretpw" not in seeds[0] and "admin" not in seeds[0]
        assert with_login == DynamoDb(db_client=self.client(endpoint_url="https://dynamo.example.com")).id

    def test_unchanged_ids_region_key_and_explicit(self):
        from agno.db.dynamo import DynamoDb

        by_key = DynamoDb(region_name="us-east-1", aws_access_key_id="AKIDEXAMPLE", aws_secret_access_key="x")
        assert by_key.id == "bf995303-a057-518f-b041-2f03cb9470fe"
        assert DynamoDb(db_client=self.client(), id="mine").id == "mine"

    @pytest.mark.parametrize("client", [object(), MagicMock()], ids=["object", "mock"])
    def test_unreadable_client_keeps_todays_id_and_warns(self, client):
        from agno.db.dynamo import DynamoDb

        # A mock's meta.region_name and meta.endpoint_url are mocks, not strings: no address to read.
        with patch("agno.db.utils.log_warning") as warn:
            db = DynamoDb(db_client=client)
        assert db.id == generate_id(str(client))
        warn.assert_called_once()


class TestFirestoreClientIdSeeding:
    @pytest.fixture(autouse=True)
    def _driver(self, monkeypatch):
        pytest.importorskip("google.cloud.firestore")
        # Lets Client(project=...) build without Google credentials; nothing connects in these tests.
        monkeypatch.setenv("FIRESTORE_EMULATOR_HOST", "127.0.0.1:1")

    @staticmethod
    def client(project="my-project", database=None):
        from google.auth.credentials import AnonymousCredentials
        from google.cloud.firestore import Client

        kwargs = {"database": database} if database else {}
        return Client(project=project, credentials=AnonymousCredentials(), **kwargs)

    def test_same_project_and_database_get_the_same_id(self):
        from agno.db.firestore import FirestoreDb

        assert FirestoreDb(db_client=self.client()).id == FirestoreDb(db_client=self.client()).id
        named = FirestoreDb(db_client=self.client(database="other")).id
        assert FirestoreDb(db_client=self.client(database="other")).id == named

    def test_default_database_matches_project_id_and_named_databases_differ(self):
        from agno.db.firestore import FirestoreDb

        by_project = FirestoreDb(project_id="my-project").id
        assert by_project == "e963980a-77a2-5699-beeb-90c6c7c9d332"
        assert FirestoreDb(db_client=self.client()).id == by_project
        assert FirestoreDb(db_client=self.client(database="other")).id != by_project
        assert FirestoreDb(db_client=self.client(project="another")).id != by_project
        assert FirestoreDb(db_client=self.client(), id="mine").id == "mine"

    def test_unreadable_client_keeps_todays_id_and_warns(self):
        from agno.db.firestore import FirestoreDb

        client = object()
        with patch("agno.db.utils.log_warning") as warn:
            db = FirestoreDb(db_client=client)
        assert db.id == generate_id(str(client))
        warn.assert_called_once()


@pytest.mark.parametrize(
    "driver, package, adapter, client_arg",
    [
        ("redis", "redis", "RedisDb", "redis_client"),
        ("glide_sync", "valkey", "ValkeyDb", "valkey_client"),
        ("boto3", "dynamo", "DynamoDb", "db_client"),
        ("google.cloud.firestore", "firestore", "FirestoreDb", "db_client"),
    ],
)
def test_a_mock_client_never_fails_construction(driver, package, adapter, client_arg):
    # Tests across the suite build adapters around MagicMock clients; reading an address from one must not raise.
    pytest.importorskip(driver)
    adapter_class = getattr(import_module(f"agno.db.{package}"), adapter)
    assert adapter_class(**{client_arg: MagicMock()}).id
