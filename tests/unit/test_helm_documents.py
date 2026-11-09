"""Helm chart content is withheld by structure until a fresh reviewed disclosure."""

import json
from pathlib import Path

import pytest
import yaml

from kuberich.domain.helm import (
    MAX_HELM_OUTPUT_BYTES,
    MAX_HELM_RENDER_BYTES,
    HelmDocumentKind,
    HelmProblem,
)
from kuberich.domain.helm_documents import helm_document_text

VALUES = {
    "innocent": "SYNTHETIC_SECRET",
    "count": 42,
    "enabled": True,
    "empty": None,
    "nested": [{"label": "SYNTHETIC_NESTED_SECRET"}, False],
    "emptyMap": {},
    "emptyList": [],
}
MANIFEST = """apiVersion: v1
kind: List
items:
  - apiVersion: v1
    kind: Secret
    metadata:
      name: demo-secret
      annotations:
        arbitrary: SYNTHETIC_ANNOTATION_SECRET
    data:
      ordinary: SYNTHETIC_SECRET_DATA
    stringData:
      plain: SYNTHETIC_SECRET_STRING
    binaryData: SYNTHETIC_SECRET_BINARY
  - apiVersion: v1
    kind: ConfigMap
    metadata:
      name: demo-config
    data:
      ordinary: SYNTHETIC_CONFIG_DATA
  - apiVersion: apps/v1
    kind: Deployment
    metadata:
      name: demo
    spec:
      template:
        spec:
          containers:
            - name: worker
              image: owned:test
              command: [SYNTHETIC_COMMAND_SECRET]
              args: [SYNTHETIC_ARG_SECRET]
              env:
                - name: INNOCENT
                  value: SYNTHETIC_ENV_SECRET
              token: SYNTHETIC_TOKEN_SECRET
"""


@pytest.mark.parametrize("kind", [HelmDocumentKind.VALUES, HelmDocumentKind.ALL_VALUES])
def test_values_hide_every_scalar_without_guessing_which_keys_are_sensitive(kind):
    rendered = helm_document_text(json.dumps(VALUES).encode(), kind, disclosed=False)
    assert "SYNTHETIC_" not in rendered and "42" not in rendered
    parsed = yaml.safe_load(rendered)
    assert parsed["innocent"] == "[REDACTED]" and parsed["nested"][1] == "[REDACTED]"
    assert parsed["emptyMap"] == {} and parsed["emptyList"] == []
    disclosed = helm_document_text(json.dumps(VALUES).encode(), kind, disclosed=True)
    assert yaml.safe_load(disclosed) == VALUES


def test_upstream_values_shape_and_null_have_honest_distinct_semantics():
    root = Path(__file__).parents[1] / "fixtures/helm/upstream"
    for version in ("v3.22.1", "v4.3.1"):
        data = (root / version / "values.json").read_bytes()
        assert "[REDACTED]" in helm_document_text(data, HelmDocumentKind.VALUES, disclosed=False)
    assert (
        helm_document_text(b"null", HelmDocumentKind.VALUES, disclosed=False)
        == "No supplied values.\n"
    )
    assert (
        helm_document_text(b"null", HelmDocumentKind.ALL_VALUES, disclosed=True)
        == "Helm returned no computed values.\n"
    )
    assert helm_document_text(b"{}", HelmDocumentKind.VALUES, disclosed=False) == "{}\n"


def test_manifest_redaction_recognizes_nested_kubernetes_objects_and_execution_data():
    safe = helm_document_text(MANIFEST.encode(), HelmDocumentKind.MANIFEST, disclosed=False)
    assert "SYNTHETIC_" not in safe
    objects = yaml.safe_load(safe)["items"]
    assert objects[0]["data"]["ordinary"] == "[REDACTED]"
    assert objects[0]["stringData"]["plain"] == "[REDACTED]"
    assert objects[0]["binaryData"] == "[REDACTED]"
    assert objects[1]["data"]["ordinary"] == "[REDACTED]"
    assert objects[2]["spec"]["template"]["spec"]["containers"][0]["image"] == "owned:test"
    disclosed = helm_document_text(MANIFEST.encode(), HelmDocumentKind.MANIFEST, disclosed=True)
    assert yaml.safe_load(disclosed) == yaml.safe_load(MANIFEST)
    assert "SYNTHETIC_SECRET_DATA" in disclosed


def test_multidocument_manifest_and_timestamp_literals_are_preserved():
    source = (
        "---\n"
        + MANIFEST
        + "---\napiVersion: v1\nkind: ConfigMap\nmetadata:\n  creationTimestamp: 2026-11-09T12:00:00Z\ndata: {}\n---\n"
    )
    documents = list(
        yaml.safe_load_all(
            helm_document_text(source.encode(), HelmDocumentKind.MANIFEST, disclosed=True)
        )
    )
    assert len(documents) == 2
    assert documents[1]["metadata"]["creationTimestamp"] == "2026-11-09T12:00:00Z"
    assert helm_document_text(b"", HelmDocumentKind.MANIFEST, disclosed=False) == ""
    assert helm_document_text(b"---\n", HelmDocumentKind.MANIFEST, disclosed=True) == ""


def test_notes_are_withheld_by_default_and_optional_header_or_empty_notes_are_valid():
    source = b"NOTES:\nSYNTHETIC_NOTES_SECRET\n"
    assert "SYNTHETIC_" not in helm_document_text(source, HelmDocumentKind.NOTES, disclosed=False)
    assert (
        helm_document_text(source, HelmDocumentKind.NOTES, disclosed=True)
        == "SYNTHETIC_NOTES_SECRET\n"
    )
    for data in (b"", b"NOTES:\n"):
        assert helm_document_text(data, HelmDocumentKind.NOTES, disclosed=False) == ""


@pytest.mark.parametrize(
    "kind,data",
    [
        (HelmDocumentKind.NOTES, b"secret\x1b[31m\r\t\x00\n"),
        (HelmDocumentKind.VALUES, b'{"value":"secret\\u001b[31m\\r\\t\\u0000"}'),
        (
            HelmDocumentKind.MANIFEST,
            b'apiVersion: v1\nkind: ConfigMap\ndata:\n  text: "secret\\u001b[31m\\r\\t\\u0000"\n',
        ),
    ],
)
def test_disclosure_keeps_terminal_and_directional_controls_inert(kind, data):
    rendered = helm_document_text(data, kind, disclosed=True)
    assert (
        "\x1b" not in rendered
        and "\r" not in rendered
        and "\t" not in rendered
        and "\0" not in rendered
    )
    assert "secret" in rendered


@pytest.mark.parametrize(
    "data",
    [
        b"[]",
        b'"scalar"',
        b"12",
        b"true",
        b'{"same":"SENSITIVE","same":1}',
        b"{",
        b"\xff",
        b'{"value":NaN}',
    ],
)
def test_values_reject_nonobjects_and_ambiguous_json_without_source_echo(data):
    with pytest.raises(HelmProblem) as caught:
        helm_document_text(data, HelmDocumentKind.VALUES, disclosed=False)
    assert "SENSITIVE" not in str(caught.value)


@pytest.mark.parametrize(
    "data",
    [
        b"secret: [SENSITIVE",
        b"apiVersion: v1\nkind: Secret\nkind: ConfigMap\n",
        b"apiVersion: v1\nkind: Secret\ndata: &s {key: SENSITIVE}\ncopy: *s\n",
        b"apiVersion: v1\nkind: Secret\ndata: !custom SENSITIVE\n",
        b"apiVersion: v1\nkind: Secret\ndata: !!timestamp 2026-11-09\n",
        b"apiVersion: v1\nkind: Secret\ndata: {1: SENSITIVE}\n",
        b"apiVersion: v1\nkind: Secret\ndata: .nan\n",
        b"[]",
        b"kind: Secret\n",
        b"apiVersion: v1\nkind: ''\n",
        b"apiVersion: 1\nkind: Secret\n",
    ],
)
def test_manifest_never_falls_back_to_raw_malformed_or_unsupported_yaml(data):
    for disclosed in (False, True):
        with pytest.raises(HelmProblem) as caught:
            helm_document_text(data, HelmDocumentKind.MANIFEST, disclosed=disclosed)
        assert "SENSITIVE" not in str(caught.value)


def test_yaml_limits_apply_before_construction_even_when_content_is_withheld():
    too_many = ("---\napiVersion: v1\nkind: ConfigMap\n" * 257).encode()
    too_deep = ("apiVersion: v1\nkind: ConfigMap\ndata: " + "[" * 65 + "0" + "]" * 65).encode()
    too_many_nodes = (
        "apiVersion: v1\nkind: ConfigMap\ndata: [" + ",".join("0" for _ in range(50_001)) + "]"
    ).encode()
    for data in (too_many, too_deep, too_many_nodes):
        with pytest.raises(HelmProblem):
            helm_document_text(data, HelmDocumentKind.MANIFEST, disclosed=False)


@pytest.mark.parametrize("kind", list(HelmDocumentKind))
def test_document_raw_output_limit_is_separate_from_rendered_text_limit(kind):
    with pytest.raises(HelmProblem, match="8 MiB"):
        helm_document_text(b"x" * (MAX_HELM_OUTPUT_BYTES + 1), kind, disclosed=False)
    with pytest.raises(HelmProblem):
        helm_document_text(None, kind, disclosed=False)


def test_rendered_limit_uses_utf8_bytes_and_rejects_instead_of_truncating():
    for data in (
        b"x" * (MAX_HELM_RENDER_BYTES + 1),
        ("\u00e9" * (MAX_HELM_RENDER_BYTES // 2 + 1)).encode(),
    ):
        with pytest.raises(HelmProblem, match="256 KiB"):
            helm_document_text(data, HelmDocumentKind.NOTES, disclosed=True)
        assert "withheld" in helm_document_text(data, HelmDocumentKind.NOTES, disclosed=False)
    assert (
        len(
            helm_document_text(b"x" * MAX_HELM_RENDER_BYTES, HelmDocumentKind.NOTES, disclosed=True)
        )
        == MAX_HELM_RENDER_BYTES
    )


@pytest.mark.parametrize("kind,disclosed", [("notes", False), (HelmDocumentKind.NOTES, 1)])
def test_document_requires_explicit_kind_and_boolean_disclosure(kind, disclosed):
    with pytest.raises(HelmProblem):
        helm_document_text(b"", kind, disclosed=disclosed)


def test_manifest_scalar_limits_remain_fail_closed():
    source = ("apiVersion: v1\nkind: Pod\nordinary: " + "x" * 65537).encode()
    with pytest.raises(HelmProblem):
        helm_document_text(source, HelmDocumentKind.MANIFEST, disclosed=False)


def test_long_mapping_keys_are_rejected_before_default_redaction_can_clip_them():
    for kind, source in (
        (HelmDocumentKind.VALUES, json.dumps({"x" * 65537: "SENSITIVE"}).encode()),
        (
            HelmDocumentKind.MANIFEST,
            ("apiVersion: v1\nkind: ConfigMap\n" + "x" * 65537 + ": SENSITIVE").encode(),
        ),
    ):
        with pytest.raises(HelmProblem):
            helm_document_text(source, kind, disclosed=False)
