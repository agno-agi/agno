from unittest.mock import MagicMock

from agno.tools.toolkit import Toolkit


class FakeGoogleToolkit(Toolkit):
    """Simulates a Google toolkit with auth state and per-user caches."""

    def __init__(self):
        self.creds = None
        self.service = None
        self.google_auth = MagicMock()
        self._db = MagicMock()
        self._label_cache = None
        self.scopes = ["https://www.googleapis.com/auth/gmail.readonly"]
        super().__init__(name="fake_google", tools=[self.do_thing, self.get_stuff])

    def do_thing(self, query: str) -> str:
        return f"result from {id(self)}: {query}"

    def get_stuff(self, item_id: str) -> str:
        return f"stuff from {id(self)}: {item_id}"


class FakeSlidesToolkit(Toolkit):
    """Simulates Slides with dual services."""

    def __init__(self):
        self.creds = None
        self.service = None
        self.slides_service = None
        self.drive_service = None
        super().__init__(name="fake_slides", tools=[self.create_slide])

    def create_slide(self, title: str) -> str:
        return f"slide from {id(self)}: {title}"


class FakeCustomNameToolkit(Toolkit):
    """Toolkit where registered function name differs from method name."""

    def __init__(self):
        self.creds = None
        self.service = None
        super().__init__(name="custom_name", tools=[])
        self.register(self._internal_search, name="search")

    def _internal_search(self, query: str) -> str:
        return f"search from {id(self)}: {query}"


class TestCloneForRun:
    def test_clone_is_different_object(self):
        toolkit = FakeGoogleToolkit()
        clone = toolkit._clone_for_run()
        assert clone is not toolkit

    def test_clone_shares_immutable_config(self):
        toolkit = FakeGoogleToolkit()
        clone = toolkit._clone_for_run()
        assert clone.name == toolkit.name
        assert clone.google_auth is toolkit.google_auth
        assert clone._db is toolkit._db
        assert clone.scopes is toolkit.scopes

    def test_clone_resets_creds_and_service(self):
        toolkit = FakeGoogleToolkit()
        toolkit.creds = MagicMock(valid=True)
        toolkit.service = MagicMock()

        clone = toolkit._clone_for_run()
        assert clone.creds is None
        assert clone.service is None
        # Original unchanged
        assert toolkit.creds is not None
        assert toolkit.service is not None

    def test_clone_isolates_attribute_writes(self):
        toolkit = FakeGoogleToolkit()
        clone = toolkit._clone_for_run()

        clone.creds = "alice_creds"
        clone.service = "alice_service"
        clone._label_cache = {"inbox": "INBOX_ID"}

        assert toolkit.creds is None
        assert toolkit.service is None
        assert toolkit._label_cache is None

    def test_clone_preserves_functions(self):
        toolkit = FakeGoogleToolkit()
        clone = toolkit._clone_for_run()

        original_funcs = set(toolkit.get_functions().keys())
        clone_funcs = set(clone.get_functions().keys())
        assert original_funcs == clone_funcs

    def test_clone_without_auth_attrs(self):
        toolkit = Toolkit(name="plain", tools=[])
        clone = toolkit._clone_for_run()
        assert clone is not toolkit
        assert clone.name == "plain"


class TestCloneSlidesToolkit:
    def test_slides_resets_all_services(self):
        toolkit = FakeSlidesToolkit()
        toolkit.creds = MagicMock(valid=True)
        toolkit.service = MagicMock()
        toolkit.slides_service = MagicMock()
        toolkit.drive_service = MagicMock()

        clone = toolkit._clone_for_run()
        assert clone.creds is None
        assert clone.service is None
        assert clone.slides_service is None
        assert clone.drive_service is None
        # Original unchanged
        assert toolkit.slides_service is not None
        assert toolkit.drive_service is not None

    def test_slides_clone_isolates_service_writes(self):
        toolkit = FakeSlidesToolkit()
        clone = toolkit._clone_for_run()

        clone.slides_service = "alice_slides"
        clone.drive_service = "alice_drive"

        assert toolkit.slides_service is None
        assert toolkit.drive_service is None


class TestEntrypointRebinding:
    def test_rebound_method_sees_clone_self(self):
        toolkit = FakeGoogleToolkit()
        clone = toolkit._clone_for_run()

        rebound = getattr(clone, "do_thing")
        assert rebound.__self__ is clone

    def test_rebound_method_executes_on_clone(self):
        toolkit = FakeGoogleToolkit()
        clone = toolkit._clone_for_run()

        rebound = getattr(clone, "do_thing")
        result = rebound("test")
        assert str(id(clone)) in result

    def test_custom_name_method_resolves(self):
        toolkit = FakeCustomNameToolkit()
        funcs = toolkit.get_functions()
        assert "search" in funcs

        clone = toolkit._clone_for_run()
        # The method is registered as "search" but Python name is "_internal_search"
        # Rebinding uses the registered name (loop variable `name`)
        rebound = getattr(clone, "_internal_search", None)
        assert rebound is not None
        result = rebound("test")
        assert str(id(clone)) in result


class TestMultiUserIsolation:
    def test_two_clones_are_independent(self):
        toolkit = FakeGoogleToolkit()

        clone_alice = toolkit._clone_for_run()
        clone_bob = toolkit._clone_for_run()

        clone_alice.creds = "alice_creds"
        clone_alice.service = "alice_service"
        clone_alice._label_cache = {"inbox": "ALICE_INBOX"}

        clone_bob.creds = "bob_creds"
        clone_bob.service = "bob_service"
        clone_bob._label_cache = {"inbox": "BOB_INBOX"}

        assert clone_alice.creds == "alice_creds"
        assert clone_bob.creds == "bob_creds"
        assert clone_alice._label_cache["inbox"] == "ALICE_INBOX"
        assert clone_bob._label_cache["inbox"] == "BOB_INBOX"
        # Original untouched
        assert toolkit.creds is None
        assert toolkit._label_cache is None

    def test_original_stays_clean_across_runs(self):
        toolkit = FakeGoogleToolkit()

        for user in ["alice", "bob", "charlie"]:
            clone = toolkit._clone_for_run()
            clone.creds = f"{user}_creds"
            clone.service = f"{user}_service"

        assert toolkit.creds is None
        assert toolkit.service is None

    def test_slides_clones_independent(self):
        toolkit = FakeSlidesToolkit()

        clone_a = toolkit._clone_for_run()
        clone_b = toolkit._clone_for_run()

        clone_a.slides_service = "alice_slides"
        clone_b.slides_service = "bob_slides"

        assert clone_a.slides_service == "alice_slides"
        assert clone_b.slides_service == "bob_slides"
        assert toolkit.slides_service is None


class FakeContextvarToolkit(Toolkit):
    """Simulates real Google toolkits where service is a @property reading from contextvar.

    This is the ACTUAL pattern used by GoogleToolkit in v2.6+. The service attribute
    is a property, not an instance attribute, so _clone_for_run() correctly skips it
    (vars() doesn't include properties).
    """

    _service_value = None

    def __init__(self):
        self._explicit_creds = None
        self.scopes = ["https://www.googleapis.com/auth/gmail.readonly"]
        super().__init__(name="contextvar_toolkit", tools=[self.do_thing])

    @property
    def service(self):
        return self._service_value

    def do_thing(self, query: str) -> str:
        return f"result: {query}"


class FakeRuntimeMutationToolkit(Toolkit):
    """Simulates toolkits like Zep/E2B that mutate instance state during execution.

    These toolkits have real instance attributes that get set during tool method
    execution, not in __init__. _clone_for_run() provides isolation for these.
    """

    def __init__(self):
        self._initialized = False
        self.session_id = None
        self.user_id = None
        self.client = None
        super().__init__(name="runtime_mutation", tools=[self.initialize, self.do_work])

    def initialize(self) -> str:
        self._initialized = True
        self.session_id = f"session_{id(self)}"
        self.user_id = f"user_{id(self)}"
        self.client = {"connected": True}
        return f"initialized: {self.session_id}"

    def do_work(self, task: str) -> str:
        return f"work on {task} by {self.user_id}"


class TestContextvarPatternToolkit:
    """Tests for toolkits using @property + contextvar pattern (like real Google toolkits)."""

    def test_clone_does_not_crash_on_property(self):
        toolkit = FakeContextvarToolkit()
        clone = toolkit._clone_for_run()
        assert clone is not toolkit

    def test_clone_skips_property_service(self):
        toolkit = FakeContextvarToolkit()
        FakeContextvarToolkit._service_value = "shared_service"

        clone = toolkit._clone_for_run()
        assert clone.service == "shared_service"
        assert toolkit.service == "shared_service"

    def test_service_not_in_vars(self):
        toolkit = FakeContextvarToolkit()
        assert "service" not in vars(toolkit)
        clone = toolkit._clone_for_run()
        assert "service" not in vars(clone)

    def test_clone_shares_explicit_creds(self):
        toolkit = FakeContextvarToolkit()
        toolkit._explicit_creds = "preset_creds"

        clone = toolkit._clone_for_run()
        assert clone._explicit_creds == "preset_creds"


class TestRuntimeMutationToolkit:
    """Tests for toolkits with runtime state mutations (like Zep, E2B)."""

    def test_clone_isolates_runtime_mutations(self):
        toolkit = FakeRuntimeMutationToolkit()

        clone = toolkit._clone_for_run()
        clone.initialize()

        assert clone._initialized is True
        assert clone.session_id is not None
        assert clone.client is not None
        assert toolkit._initialized is False
        assert toolkit.session_id is None
        assert toolkit.client is None

    def test_two_clones_get_different_sessions(self):
        toolkit = FakeRuntimeMutationToolkit()

        clone_alice = toolkit._clone_for_run()
        clone_bob = toolkit._clone_for_run()

        clone_alice.initialize()
        clone_bob.initialize()

        assert clone_alice.session_id != clone_bob.session_id
        assert clone_alice.user_id != clone_bob.user_id
        assert toolkit.session_id is None

    def test_original_stays_clean_for_next_user(self):
        toolkit = FakeRuntimeMutationToolkit()

        for i in range(3):
            clone = toolkit._clone_for_run()
            clone.initialize()
            assert clone._initialized is True

        assert toolkit._initialized is False
        assert toolkit.session_id is None


class TestMixedToolkitScenario:
    """Tests for mixed toolkit scenarios (Google + Zep + stateless)."""

    def test_mixed_toolkits_all_clone_correctly(self):
        contextvar_toolkit = FakeContextvarToolkit()
        mutation_toolkit = FakeRuntimeMutationToolkit()
        plain_toolkit = Toolkit(name="plain", tools=[])

        cv_clone = contextvar_toolkit._clone_for_run()
        mut_clone = mutation_toolkit._clone_for_run()
        plain_clone = plain_toolkit._clone_for_run()

        assert cv_clone is not contextvar_toolkit
        assert mut_clone is not mutation_toolkit
        assert plain_clone is not plain_toolkit

    def test_mixed_isolation_patterns_coexist(self):
        contextvar_toolkit = FakeContextvarToolkit()
        mutation_toolkit = FakeRuntimeMutationToolkit()

        cv_clone = contextvar_toolkit._clone_for_run()
        mut_clone = mutation_toolkit._clone_for_run()

        mut_clone.initialize()

        assert mut_clone._initialized is True
        assert mutation_toolkit._initialized is False
        assert "service" not in vars(cv_clone)
