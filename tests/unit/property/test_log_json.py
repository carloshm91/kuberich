"""Structured-log parsing must redact decoded keys while keeping public fields."""

import json

from hypothesis import given
from hypothesis import strategies as st

from kuberich.domain.log_json import UNAVAILABLE, sanitize_log_line, structured_payload
from tests.support.properties import NAMES, PROPERTY, SECRETS


@PROPERTY
@given(
    secret=SECRETS,
    visible=st.lists(NAMES, max_size=12),
    key=st.sampled_from(["token", "Password", "api_key", "authorization"]),
)
def test_nested_json_removes_secrets_without_losing_public_fields(secret, visible, key):
    marker = "owned-secret-" + secret
    payload = json.dumps({"public": visible, "nested": [{key: marker}]})
    text, structured = structured_payload(payload)
    assert marker not in text and structured == text
    result = json.loads(text)
    assert result == {"public": visible, "nested": [{key: "[REDACTED]"}]}
    assert structured_payload(text)[0] == text
    prefix = "2026-11-01T00:00:00.123Z "
    assert sanitize_log_line(prefix + payload) == prefix + text


@PROPERTY
@given(secret=SECRETS)
def test_encoded_secret_keys_and_truncated_json_never_fall_back_to_raw_credentials(secret):
    marker = "owned-secret-" + secret
    payload = '{"to\\u006ben":' + json.dumps(marker)
    assert structured_payload(payload) == (UNAVAILABLE, None)
    complete = payload + "}"
    text, structured = structured_payload(complete)
    assert marker not in text and json.loads(structured) == {"token": "[REDACTED]"}


@PROPERTY
@given(depth=st.integers(17, 30), count=st.integers(510, 514))
def test_depth_and_expansion_boundaries_return_an_explicit_unavailable_state(depth, count):
    nested = '{"public":' * depth + '"value"' + "}" * depth
    assert structured_payload(nested) == (UNAVAILABLE, None)
    text, structured = structured_payload(json.dumps([0] * count))
    if count <= 511:
        assert json.loads(structured) == [0] * count and structured == text
    else:
        assert (text, structured) == (UNAVAILABLE, None)
