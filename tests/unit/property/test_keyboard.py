"""Effective generated maps retain safe keys and unique owner bindings."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from kuberich.domain.keyboard import PROFILES, effective_keymap, key_mapping, keys_for, parse_keys
from kuberich.errors import AppError
from tests.support.properties import PROPERTY

SAFE_KEYS = st.sampled_from(["K", "alt+b", "alt+z", "9"])


@PROPERTY
@given(key=SAFE_KEYS)
def test_common_override_roundtrips_and_never_changes_log_navigation(key):
    parsed = parse_keys({"table": {"down": key}})
    assert parse_keys(key_mapping(parsed)) == parsed
    effective = dict(effective_keymap(parsed))
    for profile in PROFILES:
        values = keys_for(parsed, profile)
        assert len(values.values()) == len(set(values.values()))
        assert effective[profile + ".down"] == ("j" if profile in {"logs", "text"} else key)


@PROPERTY
@given(key=SAFE_KEYS)
def test_effective_duplicate_bindings_are_refused_instead_of_shadowing_an_action(key):
    with pytest.raises(AppError, match="Duplicate"):
        parse_keys({"table": {"down": key, "up": key}})


@pytest.mark.parametrize("key", ["b", "1"])
def test_history_fixed_keys_require_an_explicit_profile_override(key):
    with pytest.raises(AppError, match="fixed action in history"):
        parse_keys({"table": {"down": key}})
    parsed = parse_keys({"table": {"down": key}, "history": {"down": "alt+j"}})
    assert keys_for(parsed, "resources")["down"] == key
    assert keys_for(parsed, "history")["down"] == "alt+j"


@PROPERTY
@given(
    profile=st.sampled_from(PROFILES),
    key=st.sampled_from(["q", "ctrl+q", "enter", "slash", "colon", "f1"]),
)
def test_reserved_exit_input_and_native_keys_cannot_be_rebound(profile, key):
    with pytest.raises(AppError):
        parse_keys({profile: {"down": key}})
