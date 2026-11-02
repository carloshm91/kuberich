"""Generated alias graphs keep literal arguments and reject recursion."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from kuberich.domain.aliases import expand_alias, parse_aliases
from kuberich.errors import AppError
from tests.support.properties import NAMES, PROPERTY


@PROPERTY
@given(depth=st.integers(1, 8), words=st.lists(NAMES, min_size=1, max_size=4))
def test_acyclic_expansion_preserves_literal_case_sensitive_arguments(depth, words):
    values = {
        f"a{index}": f"a{index + 1}" if index + 1 < depth else "ctx" for index in range(depth)
    }
    aliases = parse_aliases(values)
    argument = " ".join(words).upper()
    assert expand_alias("a0 " + argument, aliases) == "ctx " + argument
    assert expand_alias("ctx " + argument, aliases) == "ctx " + argument
    assert parse_aliases(dict(aliases)) == aliases


@PROPERTY
@given(depth=st.integers(1, 8))
def test_every_cycle_is_refused_regardless_of_which_alias_is_entered(depth):
    values = {f"a{index}": f"a{(index + 1) % depth}" for index in range(depth)}
    with pytest.raises(AppError, match="Recursive"):
        parse_aliases(values)
    for name in values:
        with pytest.raises(AppError, match="Recursive"):
            expand_alias(name, tuple(values.items()))


@PROPERTY
@given(argument=NAMES)
def test_preset_arguments_and_resource_name_conflicts_cannot_be_overridden(argument):
    aliases = parse_aliases({"work": "ctx Exact Context"})
    assert expand_alias("work", aliases) == "ctx Exact Context"
    with pytest.raises(AppError, match="already supplies"):
        expand_alias("work " + argument, aliases)
    with pytest.raises(AppError, match="conflicts"):
        expand_alias("work", aliases, {"work"})
