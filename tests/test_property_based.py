"""
Property-Based Tests for Functional Pipeline Components

Uses Hypothesis to verify algebraic laws and invariants
that pure functions must satisfy — the FP way to test.
"""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from src.functional import (
    Success, Failure, Some, Nothing,
    pipe, compose, when, unless,
    try_op, lazy, is_ok, is_err, is_some, is_nothing,
)
from src.pipeline.receive_pure import (
    FileInfo, FileInventory, DiscoveredFiles, validate_discovery,
)
from src.pipeline.schema_validate_pure import (
    FileType, classify_file,
    BENEFICIARY_EXPECTED_COLS, CARRIER_EXPECTED_COLS,
)


# ---------------------------------------------------------------------------
# Strategies: custom generators for our domain types
# ---------------------------------------------------------------------------

file_names = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P")),
    min_size=1, max_size=30,
).map(lambda s: s + ".csv")

sha256_hashes = st.text(
    alphabet="0123456789abcdef", min_size=64, max_size=64,
)

file_infos = st.builds(
    FileInfo,
    name=file_names,
    path=st.text(min_size=1, max_size=100),
    size_bytes=st.integers(min_value=0, max_value=10**9),
    sha256=sha256_hashes,
)

file_inventories = st.lists(file_infos, max_size=20).map(
    lambda fs: FileInventory(files=tuple(fs))
)

discovered_files = st.builds(
    DiscoveredFiles,
    beneficiary=st.lists(file_names, max_size=10).map(tuple),
    carrier_claims=st.lists(file_names, max_size=10).map(tuple),
)

csv_headers = st.lists(
    st.text(alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ_0123456789", min_size=1, max_size=30),
    min_size=0, max_size=150,
).map(tuple)

small_ints = st.integers(min_value=-100, max_value=100)
positive_ints = st.integers(min_value=1, max_value=1000)


# ===========================================================================
# MONAD LAWS — The heart of functional programming
# ===========================================================================

class TestResultMonadLaws:
    """
    Result must satisfy the three monad laws:
      1. Left identity:  Success(a).bind(f) == f(a)
      2. Right identity: m.bind(Success) == m
      3. Associativity:  m.bind(f).bind(g) == m.bind(λx: f(x).bind(g))
    """

    @given(x=small_ints)
    def test_left_identity(self, x: int):
        """Success(a).bind(f) == f(a)"""
        f = lambda a: Success(a * 2)
        assert Success(x).bind(f).unwrap() == f(x).unwrap()

    @given(x=small_ints)
    def test_right_identity(self, x: int):
        """m.bind(Success) == m"""
        m = Success(x)
        assert m.bind(Success).unwrap() == m.unwrap()

    @given(x=small_ints)
    def test_associativity(self, x: int):
        """m.bind(f).bind(g) == m.bind(λx: f(x).bind(g))"""
        f = lambda a: Success(a + 1)
        g = lambda a: Success(a * 3)
        m = Success(x)

        lhs = m.bind(f).bind(g)
        rhs = m.bind(lambda a: f(a).bind(g))
        assert lhs.unwrap() == rhs.unwrap()

    @given(x=small_ints)
    def test_failure_left_identity_short_circuits(self, x: int):
        """Failure.bind(f) == Failure (short-circuit)"""
        f = lambda a: Success(a * 2)
        err = Failure("boom")
        result = err.bind(f)
        assert is_err(result)
        assert result.failure() == "boom"


class TestResultFunctorLaws:
    """
    Result as a functor must satisfy:
      1. Identity:    map(id) == id
      2. Composition: map(f . g) == map(f) . map(g)
    """

    @given(x=small_ints)
    def test_identity(self, x: int):
        """map(id) == id"""
        assert Success(x).map(lambda a: a).unwrap() == x

    @given(x=small_ints)
    def test_composition(self, x: int):
        """map(f . g) == map(f) . map(g)"""
        f = lambda a: a + 1
        g = lambda a: a * 2
        lhs = Success(x).map(lambda a: f(g(a)))
        rhs = Success(x).map(g).map(f)
        assert lhs.unwrap() == rhs.unwrap()

    @given(x=small_ints)
    def test_failure_identity(self, x: int):
        """Failure.map(id) == Failure"""
        err = Failure("boom")
        assert is_err(err.map(lambda a: a))


# ===========================================================================
# MAYBE MONAD LAWS
# ===========================================================================

class TestMaybeMonadLaws:
    """Maybe must also satisfy monad laws."""

    @given(x=small_ints)
    def test_left_identity(self, x: int):
        f = lambda a: Some(a * 2)
        assert Some(x).bind(f).unwrap() == f(x).unwrap()

    @given(x=small_ints)
    def test_right_identity(self, x: int):
        m = Some(x)
        assert m.bind(Some).unwrap() == m.unwrap()

    @given(x=small_ints)
    def test_associativity(self, x: int):
        f = lambda a: Some(a + 1)
        g = lambda a: Some(a * 3)
        m = Some(x)
        lhs = m.bind(f).bind(g)
        rhs = m.bind(lambda a: f(a).bind(g))
        assert lhs.unwrap() == rhs.unwrap()

    def test_nothing_short_circuits(self):
        f = lambda a: Some(a * 2)
        assert Nothing.bind(f) is Nothing


# ===========================================================================
# COMPOSITION LAWS
# ===========================================================================

class TestCompositionLaws:
    """pipe and compose must satisfy algebraic properties."""

    @given(x=small_ints)
    def test_pipe_identity(self, x: int):
        """pipe(x) == x  (no-op with zero functions)"""
        assert pipe(x) == x

    @given(x=small_ints)
    def test_compose_identity(self, x: int):
        """compose(id)(x) == x"""
        identity = lambda a: a
        assert compose(identity)(x) == x

    @given(x=small_ints)
    def test_pipe_compose_equivalence(self, x: int):
        """pipe(x, f, g) == compose(g, f)(x)"""
        f = lambda a: a + 1
        g = lambda a: a * 2
        assert pipe(x, f, g) == compose(g, f)(x)

    @given(x=small_ints)
    def test_compose_associativity(self, x: int):
        """compose(f, compose(g, h)) == compose(compose(f, g), h)"""
        f = lambda a: a + 1
        g = lambda a: a * 2
        h = lambda a: a - 3
        lhs = compose(f, compose(g, h))(x)
        rhs = compose(compose(f, g), h)(x)
        assert lhs == rhs


# ===========================================================================
# CONDITIONAL COMBINATORS
# ===========================================================================

class TestConditionalCombinators:
    """when/unless must be inverses and preserve identity."""

    @given(x=small_ints)
    def test_when_unless_inverse(self, x: int):
        """when(p, f) and unless(p, f) cover all cases exactly once."""
        pred = lambda a: a > 0
        f = lambda a: a * 10

        when_result = when(pred, f)(x)
        unless_result = unless(pred, f)(x)

        # Exactly one of them transforms, the other returns identity
        if x > 0:
            assert when_result == x * 10
            assert unless_result == x
        else:
            assert when_result == x
            assert unless_result == x * 10

    @given(x=small_ints)
    def test_when_false_is_identity(self, x: int):
        """when(False, f)(x) == x"""
        assert when(lambda _: False, lambda a: a * 999)(x) == x

    @given(x=small_ints)
    def test_unless_true_is_identity(self, x: int):
        """unless(True, f)(x) == x"""
        assert unless(lambda _: True, lambda a: a * 999)(x) == x


# ===========================================================================
# DOMAIN INVARIANTS — property tests on business logic
# ===========================================================================

class TestFileInventoryProperties:
    """Properties that FileInventory must always satisfy."""

    @given(inv=file_inventories)
    def test_get_returns_some_for_existing(self, inv: FileInventory):
        """Every file in inventory is findable by name."""
        for f in inv.files:
            result = inv.get(f.name)
            assert is_some(result)

    @given(inv=file_inventories)
    def test_get_returns_nothing_for_missing(self, inv: FileInventory):
        """A name not in files returns Nothing."""
        sentinel = "THIS_FILE_DEFINITELY_DOES_NOT_EXIST_abc123.csv"
        assert is_nothing(inv.get(sentinel))

    @given(inv=file_inventories)
    def test_to_dict_preserves_count(self, inv: FileInventory):
        """to_dict has same number of entries as unique file names."""
        d = inv.to_dict()
        unique_names = {f.name for f in inv.files}
        # dict deduplicates by name, so len(d) == len(unique_names)
        assert len(d) == len(unique_names)


class TestDiscoverFilesProperties:
    """Properties for DiscoveredFiles + validate_discovery."""

    @given(d=discovered_files)
    def test_all_files_is_union(self, d: DiscoveredFiles):
        """all_files == beneficiary + carrier_claims."""
        assert d.all_files == d.beneficiary + d.carrier_claims

    @given(
        n_bene=st.integers(min_value=0, max_value=10),
        n_carrier=st.integers(min_value=0, max_value=10),
        thresh_bene=st.integers(min_value=0, max_value=10),
        thresh_carrier=st.integers(min_value=0, max_value=10),
    )
    def test_validate_discovery_completeness(
        self, n_bene: int, n_carrier: int, thresh_bene: int, thresh_carrier: int,
    ):
        """is_valid iff both counts meet thresholds."""
        d = DiscoveredFiles(
            beneficiary=tuple(f"bene_{i}.csv" for i in range(n_bene)),
            carrier_claims=tuple(f"carrier_{i}.csv" for i in range(n_carrier)),
        )
        is_valid, missing = validate_discovery(
            d, expected_beneficiary=thresh_bene, expected_carrier=thresh_carrier,
        )
        expected_valid = n_bene >= thresh_bene and n_carrier >= thresh_carrier
        assert is_valid == expected_valid

    @given(d=discovered_files)
    def test_to_dict_roundtrip_keys(self, d: DiscoveredFiles):
        """to_dict always has both category keys."""
        result = d.to_dict()
        assert "beneficiary" in result
        assert "carrier_claims" in result


class TestClassifyFileProperties:
    """Properties for schema classification."""

    def test_all_beneficiary_cols_classifies_as_beneficiary(self):
        """Full beneficiary schema → beneficiary type."""
        headers = tuple(sorted(BENEFICIARY_EXPECTED_COLS))
        assert classify_file(headers).kind == "beneficiary"

    def test_all_carrier_cols_classifies_as_carrier(self):
        """Full carrier schema → carrier_claims type."""
        headers = tuple(sorted(CARRIER_EXPECTED_COLS))
        assert classify_file(headers).kind == "carrier_claims"

    @given(headers=st.lists(
        st.text(alphabet="xyz", min_size=1, max_size=5), max_size=5,
    ).map(tuple))
    def test_random_headers_classified_as_unknown(self, headers: tuple[str, ...]):
        """Random short headers should not match known schemas."""
        result = classify_file(headers)
        assert result.kind == "unknown"


class TestColumnDiffProperties:
    """Properties for column diff computation."""

    @given(
        extra_cols=st.lists(
            st.text(alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ_", min_size=1, max_size=15),
            max_size=5,
        ),
    )
    def test_beneficiary_superset_has_no_missing(self, extra_cols: list[str]):
        """If headers ⊇ expected, missing should be empty."""
        from src.pipeline.schema_validate_pure import compute_column_diff
        headers = tuple(sorted(BENEFICIARY_EXPECTED_COLS)) + tuple(extra_cols)
        diff = compute_column_diff(headers, FileType(kind="beneficiary"))
        assert diff.missing == ()


# ===========================================================================
# TRY_OP / LAZY — effect boundary properties
# ===========================================================================

class TestTryOpProperties:
    @given(x=small_ints)
    def test_pure_function_always_succeeds(self, x: int):
        """try_op on a total function always returns Success."""
        result = try_op(lambda: x * 2)
        assert is_ok(result)
        assert result.unwrap() == x * 2

    def test_raising_function_always_fails(self):
        """try_op on a throwing function always returns Failure."""
        result = try_op(lambda: 1 / 0)
        assert is_err(result)

    @given(x=small_ints)
    def test_lazy_memoisation(self, x: int):
        """lazy(f) calls f at most once regardless of access count."""
        call_count = 0
        def f():
            nonlocal call_count
            call_count += 1
            return x
        memo = lazy(f)
        _ = memo()
        _ = memo()
        _ = memo()
        assert call_count == 1
        assert memo() == x
