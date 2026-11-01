"""Seeded credentials disappear and terminal controls remain inert."""

from hypothesis import example, given
from hypothesis import strategies as st

from kuberich.diagnostics.redaction import sanitize_text
from tests.support.properties import PROPERTY, SECRETS


@PROPERTY
@given(secret=SECRETS, key=st.sampled_from(["token", "Password", "api_key", "client-secret"]))
def test_assignments_remove_the_entire_seeded_credential(secret, key):
    marker = "owned-secret-" + secret
    for text in (f"{key}={marker}", f'{key}: "{marker}"', f"{key}: '{marker}'"):
        safe = sanitize_text(text)
        assert marker not in safe and "[REDACTED]" in safe
        assert sanitize_text(safe) == safe


@PROPERTY
@given(secret=SECRETS, scheme=st.sampled_from(["Bearer", "Basic"]))
def test_authorization_schemes_and_url_userinfo_do_not_leak(secret, scheme):
    marker = "owned-secret-" + secret
    assert marker not in sanitize_text(f"{scheme} {marker}")
    assert marker not in sanitize_text(f"https://user:{marker}@example.test/path")


@PROPERTY
@given(text=st.text(max_size=512), allow_newlines=st.booleans())
@example(text="Bearer x\ty", allow_newlines=False)
@example(text="token=x\ny", allow_newlines=False)
def test_arbitrary_unicode_controls_stay_inert_when_sanitized_again(text, allow_newlines):
    safe = sanitize_text(text, allow_newlines=allow_newlines)
    forbidden = {chr(value) for value in [*range(32), *range(127, 160), *range(0xD800, 0xE000)]}
    if allow_newlines:
        forbidden.remove("\n")
    assert not set(safe) & forbidden
    assert len(safe) <= max(1, len(text)) * 6
    again = sanitize_text(safe, allow_newlines=allow_newlines)
    assert not set(again) & forbidden


@PROPERTY
@given(
    secret=SECRETS,
    separator=st.sampled_from(["\t", "\n", "\r", "\x85"]),
    prefix=st.sampled_from(["token=", "Bearer ", "Basic "]),
)
def test_credentials_next_to_whitespace_controls_never_reappear_on_a_later_pass(
    secret, separator, prefix
):
    marker = "owned-secret-" + secret
    safe = sanitize_text(prefix + marker + separator + "public-tail")
    again = sanitize_text(safe)
    assert marker not in safe and marker not in again
    assert "[REDACTED]" in safe and "[REDACTED]" in again
    assert separator not in safe and separator not in again
