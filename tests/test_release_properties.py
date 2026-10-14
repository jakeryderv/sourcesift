"""Release authorization and ordering across final and prerelease versions."""

import pytest
from hypothesis import example, given
from hypothesis import strategies as st

from scripts.release_checks import validate_change


@st.composite
def release_versions(draw):
    """Return a normalized version and its independently ordered numeric key."""
    major, minor, patch = draw(st.tuples(*(st.integers(0, 1000) for _ in range(3))))
    phase = draw(st.integers(0, 5))
    serial = 0 if phase == 4 else draw(st.integers(0, 100))
    suffix = (
        f".dev{serial}",
        f"a{serial}",
        f"b{serial}",
        f"rc{serial}",
        "",
        f".post{serial}",
    )[phase]
    return f"{major}.{minor}.{patch}{suffix}", (major, minor, patch, phase, serial)


@given(base=release_versions(), candidate=release_versions())
@example(base=("0.1.0rc1", (0, 1, 0, 3, 1)), candidate=("0.1.0", (0, 1, 0, 4, 0)))
@example(base=("1.0.0", (1, 0, 0, 4, 0)), candidate=("1.0.0", (1, 0, 0, 4, 0)))
def test_release_pr_requires_strict_version_increase(base, candidate):
    base_version, base_order = base
    candidate_version, candidate_order = candidate
    if candidate_order > base_order:
        validate_change(candidate_version, base_version, release_pr=True)
    else:
        with pytest.raises(ValueError):
            validate_change(candidate_version, base_version, release_pr=True)


@given(base=release_versions(), candidate=release_versions())
@example(base=("0.0.2", (0, 0, 2, 4, 0)), candidate=("0.0.2", (0, 0, 2, 4, 0)))
def test_ordinary_pr_cannot_change_any_version(base, candidate):
    base_version, _ = base
    candidate_version, _ = candidate
    if candidate_version == base_version:
        validate_change(candidate_version, base_version, release_pr=False)
    else:
        with pytest.raises(ValueError, match="only in the Release Please PR"):
            validate_change(candidate_version, base_version, release_pr=False)
