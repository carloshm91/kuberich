"""Parsed selector predicates agree with independent membership decisions."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from kuberich.domain.selectors import selectors
from kuberich.errors import AppError
from tests.support.properties import NAMES, PROPERTY, VALUES


@PROPERTY
@given(
    key=NAMES, values=st.sets(VALUES, min_size=1, max_size=4), actual=st.one_of(st.none(), VALUES)
)
def test_set_selectors_and_their_complements_respect_absent_labels(key, values, actual):
    fields = {} if actual is None else {key: actual}
    joined = ",".join(sorted(values))
    positive = selectors(f"{key} in ({joined})")[0]
    negative = selectors(f"{key} notin ({joined})")[0]
    expected = actual is not None and actual in values
    assert positive.matches(fields) is expected
    assert negative.matches(fields) is (not expected)
    assert selectors(key)[0].matches(fields) is (actual is not None)
    assert selectors("!" + key)[0].matches(fields) is (actual is None)


@PROPERTY
@given(key=NAMES, expected=VALUES, actual=st.one_of(st.none(), VALUES))
def test_equality_inequality_and_whitespace_do_not_guess_missing_values(key, expected, actual):
    fields = {} if actual is None else {key: actual}
    equal = actual == expected
    assert selectors(f" {key} = {expected} ")[0].matches(fields) is equal
    assert selectors(f"{key}=={expected}")[0].matches(fields) is equal
    assert selectors(f"{key}!={expected}")[0].matches(fields) is (not equal)


@PROPERTY
@given(name=NAMES, value=VALUES)
def test_unknown_field_paths_are_refused_without_becoming_label_predicates(name, value):
    with pytest.raises(AppError, match="field"):
        selectors(f"unregistered.{name}={value}", field=True)
    expression = f"metadata.name={name}"
    assert selectors(expression, field=True)[0].matches({"metadata.name": name})
