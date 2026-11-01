"""Bounded, reproducible input generation shared by the property suite."""

from hypothesis import settings
from hypothesis import strategies as st

PROPERTY = settings(max_examples=100, derandomize=True, deadline=None)
NAMES = st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=1, max_size=12)
VALUES = st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789", min_size=1, max_size=16)
SECRETS = st.text(
    alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789",
    min_size=8,
    max_size=24,
)
