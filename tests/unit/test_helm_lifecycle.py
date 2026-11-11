"""Reviewed Helm identities, secret-safe live differences and pinned command contracts."""

import json
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest

from kuberich.domain.helm import (
    HelmOutcome,
    HelmReleaseKey,
    HelmSettings,
    HelmVersion,
)
from kuberich.domain.helm_lifecycle import (
    HelmLifecycleIntent,
    HelmLifecycleKind,
    HelmLifecycleOptions,
    HelmOperationObservation,
    HelmValuesLease,
    digest_text,
    fingerprint,
    helm_owned_manifest,
    helm_release_owns,
    live_diff,
    manifest_objects,
    normalized_manifest,
    rendered_release,
    resource_observation,
    values_bytes,
)
from kuberich.domain.helm_lifecycle_cli import lifecycle_argv
from kuberich.errors import AppError
from tests.support.helm import release, request

ADDRESS = HelmReleaseKey("team", "demo")
REQUEST = request()
OPTIONS = HelmLifecycleOptions()
IDENTITY = uuid4()
DIGEST = "a" * 64
MANIFEST = {
    "apiVersion": "v1",
    "kind": "ConfigMap",
    "metadata": {"name": "demo"},
    "data": {"password": "synthetic-private", "color": "blue"},
}


def intent(**changes):
    fields = dict(
        identity=IDENTITY,
        request=REQUEST,
        address=ADDRESS,
        operation=HelmLifecycleKind.INSTALL,
        options=OPTIONS,
        effects=("Create release.",),
        preview_text="safe\npreview\n",
        dry_run="passed",
    )
    fields.update(changes)
    return HelmLifecycleIntent(**fields)


def payload(**changes):
    fields = dict(
        name="demo",
        namespace="team",
        version=1,
        manifest=json.dumps(MANIFEST),
        config={"color": "blue"},
        hooks=[],
    )
    fields.update(changes)
    return json.dumps(fields).encode()


def test_options_make_hooks_history_crd_timeout_and_deletion_policy_explicit():
    assert HelmLifecycleOptions(False, True, 300, True, "background", True) == OPTIONS
    assert HelmLifecycleOptions(True, False, 1, False, "foreground").run_hooks
    assert HelmLifecycleOptions(timeout_seconds=600, cascade="orphan").cascade == "orphan"


@pytest.mark.parametrize(
    "changes",
    [
        {"run_hooks": 1},
        {"wait": None},
        {"keep_history": "yes"},
        {"skip_crds": 1},
        {"timeout_seconds": True},
        {"timeout_seconds": 0},
        {"timeout_seconds": 601},
        {"cascade": "other"},
        {"cascade": []},
        {"skip_crds": False},
    ],
)
def test_unsupported_or_malformed_operation_options_fail_before_any_effect(changes):
    with pytest.raises(AppError):
        HelmLifecycleOptions(**changes)


def test_values_lease_is_opaque_exact_metadata_and_complete_yaml_mapping():
    lease = HelmValuesLease(IDENTITY, DIGEST, "defaults")
    assert "a" * 64 not in repr(lease)
    assert HelmValuesLease(IDENTITY, DIGEST, "edited").source == "edited"
    assert values_bytes(b"password: synthetic-private\n") == b"password: synthetic-private\n"
    assert values_bytes(b"{}") == b"{}"
    assert fingerprint(b"abc") == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    assert digest_text(DIGEST) == DIGEST


@pytest.mark.parametrize(
    "identity,sha,source",
    [
        (None, DIGEST, "defaults"),
        (IDENTITY, DIGEST, "other"),
        (IDENTITY, DIGEST, []),
        (IDENTITY, "A" * 64, "supplied"),
        (IDENTITY, 4, "defaults"),
        (IDENTITY, "a", "defaults"),
    ],
)
def test_forged_values_metadata_is_rejected(identity, sha, source):
    with pytest.raises(AppError):
        HelmValuesLease(identity, sha, source)


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"[]",
        b"a: 1\na: 2",
        b"a: &x [*x]",
        b"\xff",
        b"a: !!python/object:object {}",
        b"x" * (1024 * 1024 + 1),
    ],
)
def test_values_parser_refuses_ambiguous_recursive_nonmapping_or_oversized_input(data):
    with pytest.raises(AppError):
        values_bytes(data)


def test_review_and_observation_retain_only_validated_safe_metadata():
    assert intent().preview_text == "safe\npreview\n"
    assert (
        intent(
            request=replace(REQUEST, scope=replace(REQUEST.scope, namespace=None))
        ).address.namespace
        == "team"
    )
    observed = HelmOperationObservation(
        HelmOutcome.SUCCEEDED, "Release storage verified.", release(), True, ("configmap: present",)
    )
    assert observed.observed.revision == 3
    assert HelmOperationObservation(HelmOutcome.BLOCKED, "No write.").observed is None


@pytest.mark.parametrize(
    "changes",
    [
        {"identity": None},
        {"request": None},
        {"address": None},
        {"operation": "install"},
        {"options": None},
        {"address": HelmReleaseKey("other", "demo")},
        {"effects": []},
        {"effects": ("x",) * 513},
        {"effects": ("\x1b[31m",)},
        {"dry_run": "unsafe\n"},
        {"preview_text": None},
        {"preview_text": "\x1b[31m"},
        {"preview_text": "x" * (256 * 1024 + 1)},
    ],
)
def test_review_cannot_embed_foreign_scope_or_unbounded_unescaped_output(changes):
    with pytest.raises(AppError):
        intent(**changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"outcome": "succeeded"},
        {"may_have_started": 1},
        {"message": "\x1b"},
        {"observed": "release"},
        {"resources": []},
        {"resources": ("x",) * 257},
        {"resources": ("\x00",)},
    ],
)
def test_observation_refuses_invalid_or_unsafe_facts(changes):
    fields = dict(outcome=HelmOutcome.UNKNOWN, message="Observe before another review.")
    fields.update(changes)
    with pytest.raises(AppError):
        HelmOperationObservation(**fields)


def test_native_release_private_parse_preserves_all_bytes_and_supported_apply_methods():
    parsed = rendered_release(
        payload(hooks=[{"manifest": json.dumps(MANIFEST)}], apply_method="csa"), ADDRESS, 1
    )
    assert parsed.manifest == json.dumps(MANIFEST).encode()
    assert parsed.hooks == (json.dumps(MANIFEST).encode(),)
    assert parsed.values == b'{"color": "blue"}'
    assert parsed.apply_method == "csa" and "synthetic-private" not in repr(parsed)
    assert rendered_release(payload(config=None, apply_method="ssa"), ADDRESS).values == b"{}"
    assert rendered_release(payload(), ADDRESS).apply_method == ""


@pytest.mark.parametrize(
    "changes,revision",
    [
        ({"name": "other"}, None),
        ({"namespace": "other"}, None),
        ({"version": True}, None),
        ({"version": 2}, 1),
        ({"manifest": []}, None),
        ({"hooks": {}}, None),
        ({"hooks": [{}]}, None),
        ({"hooks": ["bad"]}, None),
        ({"hooks": [] * 0 + [{}] * 257}, None),
        ({"apply_method": {}}, None),
        ({"apply_method": "unknown"}, None),
        ({"config": []}, None),
    ],
)
def test_native_release_parse_rejects_wrong_identity_and_incomplete_envelopes(changes, revision):
    with pytest.raises(AppError):
        rendered_release(payload(**changes), ADDRESS, revision)


def test_native_release_array_cannot_substitute_for_one_exact_release():
    with pytest.raises(AppError):
        rendered_release(b"[]", ADDRESS)


def test_native_hook_effects_preserve_events_policies_and_signed_order_without_values():
    parsed = rendered_release(
        payload(
            hooks=[
                {
                    "manifest": json.dumps(MANIFEST),
                    "events": ["pre-install", "post-upgrade"],
                    "delete_policies": ["hook-succeeded", "hook-failed"],
                    "output_log_policies": ["hook-failed"],
                    "weight": -10,
                }
            ]
        ),
        ADDRESS,
    )
    effect = parsed.hook_effects[0]
    assert "pre-install, post-upgrade" in effect and "weight -10" in effect
    assert "hook-succeeded, hook-failed" in effect and "output log policies hook-failed" in effect
    assert "synthetic-private" not in effect and "outlive" in effect
    default = rendered_release(payload(hooks=[{"manifest": "{}"}]), ADDRESS).hook_effects[0]
    assert "unspecified" in default and "before-hook-creation" in default


@pytest.mark.parametrize(
    "fields",
    [
        {"events": None},
        {"events": ["pre-install"] * 33},
        {"events": [False]},
        {"events": ["unrecognized"]},
        {"delete_policies": "hook-failed"},
        {"delete_policies": ["unrecognized"]},
        {"output_log_policies": ["unrecognized"]},
        {"weight": True},
        {"weight": 2**63},
        {"weight": -(2**63) - 1},
    ],
)
def test_unsupported_hook_effect_metadata_cannot_be_omitted_from_review(fields):
    with pytest.raises(AppError, match="hook"):
        rendered_release(payload(hooks=[{"manifest": "{}", **fields}]), ADDRESS)


@pytest.mark.parametrize(
    "metadata",
    [
        None,
        {},
        {"labels": None},
        {"labels": {"app.kubernetes.io/managed-by": "Helm"}, "annotations": None},
        {"labels": {"app.kubernetes.io/managed-by": "other"}, "annotations": {}},
        {
            "labels": {"app.kubernetes.io/managed-by": "Helm"},
            "annotations": {"meta.helm.sh/release-name": "other"},
        },
        {
            "labels": {"app.kubernetes.io/managed-by": "Helm"},
            "annotations": {
                "meta.helm.sh/release-name": "demo",
                "meta.helm.sh/release-namespace": "other",
            },
        },
    ],
)
def test_retained_resource_with_foreign_or_incomplete_metadata_never_claims_ownership(metadata):
    body = {"metadata": metadata}
    assert not helm_release_owns(body, ADDRESS)
    assert resource_observation("owned", body, ADDRESS, removed=True).endswith(
        "ownership is unverified"
    )


def test_resource_facts_distinguish_absence_pending_keep_and_unverified_deletion():
    body = helm_owned_manifest(MANIFEST, ADDRESS, "team")
    assert helm_release_owns(body, ADDRESS)
    assert resource_observation("owned", None, ADDRESS, removed=True) == "owned: absent"
    assert resource_observation("owned", body, ADDRESS, removed=False).endswith(
        "ownership verified"
    )
    assert resource_observation("owned", body, ADDRESS, removed=True).endswith(
        "retention is not verified"
    )
    body["metadata"]["annotations"]["helm.sh/resource-policy"] = "keep"
    assert resource_observation("owned", body, ADDRESS, removed=True).endswith(
        "resource-policy keep"
    )
    body["metadata"]["deletionTimestamp"] = "2026-11-11T00:00:00Z"
    assert "deletion pending" in resource_observation("owned", body, ADDRESS, removed=True)


def test_manifest_stream_and_live_diff_are_structurally_redacted_and_normalized_separately():
    assert manifest_objects(b" \n") == ()
    assert manifest_objects(json.dumps(MANIFEST).encode()) == (MANIFEST,)
    old = dict(MANIFEST, data={"password": "synthetic-private-old", "color": "blue"})
    new = dict(MANIFEST, data={"password": "synthetic-private-new", "color": "red"})
    visible = live_diff(old, new, "team/demo")
    assert "synthetic-private" not in visible and "hidden" in visible
    changed = live_diff(None, MANIFEST, "team/demo")
    assert "+++ rendered/team/demo" in changed and "synthetic-private" not in changed
    assert "--- live/team/demo" in live_diff(MANIFEST, None, "team/demo")
    assert "unchanged" in live_diff(MANIFEST, MANIFEST, "team/demo")
    assert normalized_manifest(
        {
            "kind": "Pod",
            "metadata": {"uid": "old", "resourceVersion": "1", "labels": {"a": "b"}},
            "status": {},
        }
    ) == {"kind": "Pod", "metadata": {"labels": {"a": "b"}}}
    with pytest.raises(AppError):
        normalized_manifest({"metadata": None})


@pytest.mark.parametrize("major,text", [(3, "v3.22.1"), (4, "v4.3.1")])
@pytest.mark.parametrize("operation", list(HelmLifecycleKind))
@pytest.mark.parametrize("preview", [False, True])
def test_pinned_argv_freezes_scope_options_values_and_distinct_apply_modes(
    major, text, operation, preview
):
    settings, version = HelmSettings(), HelmVersion(text, major)
    argv = lifecycle_argv(
        settings,
        version,
        REQUEST.scope,
        Path("/owned/kubeconfig"),
        ADDRESS,
        operation,
        OPTIONS,
        Path("/private/chart.tgz"),
        Path("/private/values.yaml"),
        preview=preview,
    )
    assert argv[:5] == (
        "helm",
        "--kubeconfig=/owned/kubeconfig",
        "--kube-context=kuberich-test-one",
        "--namespace=team",
        "--debug=false",
    )
    assert argv[5:7] == (operation.value, "demo")
    assert "--no-hooks=true" in argv and "--timeout=300s" in argv
    assert ("--wait=true" if major == 3 else "--wait=legacy") in argv
    if operation is HelmLifecycleKind.UNINSTALL:
        assert "--keep-history=true" in argv and "--cascade=background" in argv
        assert f"--dry-run={str(preview).lower()}" in argv
        assert not any(flag.startswith("--values=") for flag in argv)
    else:
        assert argv[7] == "/private/chart.tgz" and "--values=/private/values.yaml" in argv
        assert "--skip-crds=true" in argv and "--dependency-update=false" in argv
        assert ("--atomic=false" if major == 3 else "--rollback-on-failure=false") in argv
        assert ("--dry-run=server" in argv) is preview
        assert not any(flag.startswith(("--force-replace=", "--force-conflicts=")) for flag in argv)
        if operation is HelmLifecycleKind.UPGRADE:
            assert (
                "--reset-values=true" in argv
                and "--install=false" in argv
                and "--history-max=0" in argv
            )
            assert ("--server-side=auto" in argv) is (major == 4)
        else:
            assert "--replace=false" in argv and "--create-namespace=false" in argv
            assert ("--server-side=false" in argv) is (major == 4)


def test_no_wait_has_pinned_strategy_and_paths_are_local_not_remote():
    for major, text in [(3, "v3.22.1"), (4, "v4.3.1")]:
        argv = lifecycle_argv(
            HelmSettings(),
            HelmVersion(text, major),
            REQUEST.scope,
            Path("/owned/kubeconfig"),
            ADDRESS,
            HelmLifecycleKind.INSTALL,
            replace(OPTIONS, wait=False),
            Path("/owned/chart"),
            Path("/owned/values"),
            preview=True,
        )
        assert ("--wait=false" if major == 3 else "--wait=hookOnly") in argv
    for chart, values in [
        (None, Path("/owned/values")),
        (Path("/owned/chart"), None),
        (Path("relative"), Path("/owned/values")),
        (Path("/owned/chart"), Path("relative")),
    ]:
        with pytest.raises(AppError):
            lifecycle_argv(
                HelmSettings(),
                HelmVersion("v3.22.1", 3),
                REQUEST.scope,
                Path("/owned/kubeconfig"),
                ADDRESS,
                HelmLifecycleKind.INSTALL,
                OPTIONS,
                chart,
                values,
                preview=True,
            )
    with pytest.raises(AppError):
        lifecycle_argv(
            HelmSettings(),
            HelmVersion("v3.22.1", 3),
            REQUEST.scope,
            Path("/owned/kubeconfig"),
            ADDRESS,
            "other",
            OPTIONS,
            None,
            None,
            preview=True,
        )


def test_effective_helm_metadata_matches_pinned_visitor_without_mutating_rendered_bytes():
    from kuberich.domain.helm_lifecycle import helm_owned_manifest

    source = {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {"name": "demo", "labels": {"team": "owned"}, "annotations": {"note": "safe"}},
    }
    expected = helm_owned_manifest(source, ADDRESS, "team")
    assert expected["metadata"]["namespace"] == "team"
    assert expected["metadata"]["labels"] == {
        "team": "owned",
        "app.kubernetes.io/managed-by": "Helm",
    }
    assert expected["metadata"]["annotations"] == {
        "note": "safe",
        "meta.helm.sh/release-name": "demo",
        "meta.helm.sh/release-namespace": "team",
    }
    assert source["metadata"] == {
        "name": "demo",
        "labels": {"team": "owned"},
        "annotations": {"note": "safe"},
    }
    assert (
        "namespace"
        not in helm_owned_manifest(
            {"metadata": {"name": "cluster", "labels": None, "annotations": None}}, ADDRESS, None
        )["metadata"]
    )


@pytest.mark.parametrize(
    "source",
    [
        {},
        {"metadata": None},
        {"metadata": {"labels": False}},
        {"metadata": {"annotations": []}},
        {"metadata": {"labels": {3: "bad"}}},
        {"metadata": {"annotations": {"token": 3}}},
    ],
)
def test_effective_metadata_refuses_malformed_labels_and_annotations(source):
    from kuberich.domain.helm_lifecycle import helm_owned_manifest

    with pytest.raises(AppError):
        helm_owned_manifest(source, ADDRESS, "team")
