"""Quantity spelling cannot change independently computed byte values."""

from decimal import Decimal

from hypothesis import example, given
from hypothesis import strategies as st

from kuberich.domain.registry import quantity
from tests.support.properties import PROPERTY


@PROPERTY
@given(amount=st.integers(0, 10**12), power=st.integers(1, 6))
@example(amount=0, power=1)
def test_binary_units_have_their_mathematical_byte_value(amount, power):
    suffix = "KMGTPE"[power - 1] + "i"
    result = quantity(f"{amount}{suffix}")
    expected = Decimal(amount * 1024**power)
    assert result.sort == expected
    assert quantity(str(amount * 1024**power)).sort == expected
    assert quantity(f"{amount + 1}{suffix}").sort > result.sort


@PROPERTY
@given(amount=st.integers(0, 10**12), exponent=st.integers(-40, 40))
@example(amount=1, exponent=30)
@example(amount=1, exponent=-30)
@example(amount=1, exponent=31)
@example(amount=1, exponent=-31)
def test_decimal_exponents_preserve_exact_arithmetic_and_spelling(amount, exponent):
    text = f"{amount}e{exponent:+}"
    result = quantity(text)
    assert result.text == text
    expected = Decimal(amount).scaleb(exponent) if -30 <= exponent <= 30 else None
    assert result.sort == expected
    assert quantity(f"+{amount}E{exponent:+}").sort == result.sort


@PROPERTY
@given(value=st.text(alphabet="0123456789", min_size=64, max_size=64))
def test_exact_length_boundary_accepts_valid_digits_and_refuses_a_longer_quantity(value):
    assert quantity(value).sort == Decimal(value)
    assert quantity(value + "0").sort is None


@PROPERTY
@given(text=st.text(max_size=128))
@example(text="1e31")
@example(text="1e-31")
@example(text="NaN")
def test_arbitrary_quantities_are_bounded_and_never_produce_nonfinite_values(text):
    result = quantity(text)
    assert len(result.text) <= 64
    assert result.sort is None or result.sort.is_finite()
    if len(text) > 64:
        assert result.sort is None
