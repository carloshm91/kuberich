"""Actual upstream output shapes, strict identity checks and explicit Helm argv."""

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from uuid import UUID

import pytest

from kuberich.domain.helm import (
    MAX_HELM_LIST_BYTES,
    HelmDocumentKind,
    HelmDriver,
    HelmProblem,
    HelmReleaseKey,
    HelmRequest,
    HelmRollbackIntent,
    HelmRollbackOptions,
    HelmScope,
    HelmSettings,
    HelmTarget,
    HelmVersion,
)
from kuberich.domain.helm_cli import (
    helm_document_argv,
    helm_environment,
    helm_history_argv,
    helm_json,
    helm_list_argv,
    helm_rollback_argv,
    helm_settings,
    helm_status_argv,
    helm_structure,
    helm_version_argv,
    parse_helm_history,
    parse_helm_list,
    parse_helm_status,
    parse_helm_version,
    parse_storage_identity,
)
from kuberich.domain.targets import SessionIdentity
from kuberich.errors import AppError

FIXTURES = Path(__file__).parents[1] / "fixtures" / "helm"
KEY = HelmReleaseKey("team", "demo")
SCOPE = HelmScope(SessionIdentity("owned-context", 1), "team", HelmDriver.SECRET)
ALL = replace(SCOPE, namespace=None)
SETTINGS = HelmSettings()
V3 = HelmVersion("v3.22.1", 3)
V4 = HelmVersion("v4.3.1", 4)
KUBECONFIG = Path("/private/scope/config")


def encode(value):
    return json.dumps(value).encode()


def row(**kwargs):
    return {
        "name": "demo",
        "namespace": "team",
        "revision": "3",
        "status": "deployed",
        "chart": "tiny-1.0",
        "app_version": "1",
        "updated": "2026-11-09 12:00:00 +0000 UTC",
        **kwargs,
    }


def revision(**kwargs):
    return {
        "revision": 1,
        "status": "superseded",
        "chart": "tiny-1.0",
        "app_version": "1",
        "updated": "2026-11-09T12:00:00Z",
        "description": "SYNTHETIC_DESCRIPTION_SECRET",
        **kwargs,
    }


def storage(**kwargs):
    return {
        "apiVersion": "meta.k8s.io/v1",
        "kind": "PartialObjectMetadata",
        "metadata": {
            "name": "sh.helm.release.v1.demo.v3",
            "namespace": "team",
            "uid": "uid-3",
            "resourceVersion": "opaque/3",
            "labels": {"owner": "helm", "name": "demo", "version": "3", "status": "deployed"},
        },
        **kwargs,
    }


def test_upstream_fixture_hashes_and_real_version_specific_shapes():
    checksums = json.loads((FIXTURES / "checksums.json").read_text())
    for name, expected in checksums.items():
        assert hashlib.sha256((FIXTURES / name).read_bytes()).hexdigest() == expected
    listing = parse_helm_list((FIXTURES / "upstream/v4.3.1/list-json.txt").read_bytes(), ALL)
    assert listing.complete and listing.releases[0].revision == 1
    assert listing.releases[0].key == HelmReleaseKey("default", "test-release")
    for version in ("v3.22.1", "v4.3.1"):
        history = parse_helm_history((FIXTURES / f"upstream/{version}/history.json").read_bytes())
        assert [item.revision for item in history.revisions] == [4, 3]
        assert history.revisions[0].description_present
        # Upstream minimum fixtures omit identity version. Never weaken production checks.
        with pytest.raises(HelmProblem, match="invalid"):
            parse_helm_status(
                (FIXTURES / f"upstream/{version}/status.json").read_bytes(),
                HelmReleaseKey("default", "flummoxed-chickadee"),
                1,
            )


def test_status_retains_only_explicit_metadata_not_embedded_chart_material():
    status = parse_helm_status((FIXTURES / "synthetic/status.json").read_bytes(), KEY, 3)
    assert status.notes_present and status.description_present
    assert status.hooks[0].events == ("pre-rollback", "post-rollback")
    assert "SYNTHETIC_" not in repr(status)
    assert not hasattr(status, "manifest") and not hasattr(status, "config")
    assert status.first_deployed == "2026-11-09T12:00:00Z"


@pytest.mark.parametrize("value", [None, "", "0001-01-01T00:00:00Z"])
def test_status_missing_and_zero_dates_and_optional_hooks(value):
    raw = {
        "name": "demo",
        "namespace": "team",
        "version": 3,
        "info": {"status": "failed", "first_deployed": value},
        "hooks": None,
    }
    parsed = parse_helm_status(encode(raw), KEY, 3)
    assert parsed.first_deployed is None and parsed.last_deployed is None
    assert not parsed.hooks and not parsed.notes_present and not parsed.description_present
    raw.pop("hooks")
    assert not parse_helm_status(encode(raw), KEY, 3).hooks


@pytest.mark.parametrize(
    "update",
    [
        {"version": "3"},
        {"version": True},
        {"version": 0},
        {"version": 2},
        {"name": "other"},
        {"namespace": "other"},
        {"info": []},
        {"info": {"status": "deployed", "notes": {"sensitive": "hidden"}}},
        {"info": {"status": "deployed", "first_deployed": "2026-11-09"}},
        {"hooks": [{}]},
        {"hooks": [{"name": "hook", "kind": "Job", "events": None}]},
    ],
)
def test_status_rejects_wrong_identity_and_malformed_metadata(update):
    raw = {
        "name": "demo",
        "namespace": "team",
        "version": 3,
        "info": {"status": "deployed"},
        **update,
    }
    with pytest.raises(AppError):
        parse_helm_status(encode(raw), KEY, 3)


def test_list_limits_duplicates_namespace_and_unknown_state():
    assert parse_helm_list(b"[]", SCOPE).complete
    assert (
        parse_helm_list(encode([row(status="future-state")]), SCOPE).releases[0].status
        == "future-state"
    )
    namespaced = parse_helm_list(encode([row(), row(namespace="other")]), ALL)
    assert len(namespaced.releases) == 2
    bounded = parse_helm_list(encode([row(name=f"demo-{number}") for number in range(501)]), ALL)
    assert not bounded.complete and len(bounded.releases) == 500
    for raw in (
        [row(), row()],
        [row(namespace="other")],
        [row(name=f"demo-{n}") for n in range(502)],
    ):
        with pytest.raises(HelmProblem):
            parse_helm_list(encode(raw), SCOPE)


@pytest.mark.parametrize(
    "update",
    [
        {"revision": 3},
        {"revision": "0"},
        {"revision": "01"},
        {"revision": "-1"},
        {"revision": "2147483648"},
        {"revision": "1" * 11},
        {"chart": "x" * 4097},
        {"app_version": None},
        {"status": ""},
    ],
)
def test_list_rejects_shape_coercion_and_unbounded_cells(update):
    with pytest.raises(AppError):
        parse_helm_list(encode([row(**update)]), SCOPE)


def test_metadata_sanitizes_remote_controls_and_credentials_before_retention():
    parsed = parse_helm_list(encode([row(chart="tiny\x1b[31m", app_version="token=hidden")]), SCOPE)
    assert parsed.releases[0].chart == "tiny\\u001b[31m"
    assert "hidden" not in parsed.releases[0].app_version


def test_dotted_release_name_preserves_upstream_dns_subdomain_contract():
    dotted = HelmReleaseKey("team", "demo.api")
    parsed = parse_helm_list(encode([row(name=dotted.name)]), SCOPE)
    assert parsed.releases[0].key == dotted
    argv = helm_status_argv(SETTINGS, V4, SCOPE, KUBECONFIG, dotted, 3)
    assert argv[-3] == "demo.api"
    for invalid in ("demo..api", ".demo", "demo.", "demo.-api"):
        with pytest.raises(HelmProblem):
            HelmReleaseKey("team", invalid)
    with pytest.raises(HelmProblem):
        HelmReleaseKey("team.prod", "demo.api")


def test_history_retains_latest_two_hundred_and_optional_v4_rollback_fields():
    history = parse_helm_history(
        encode([revision(revision=n, updated=None, rollback_revision=0) for n in range(1, 202)])
    )
    assert not history.complete and len(history.revisions) == 200
    assert history.revisions[0].revision == 201 and history.revisions[-1].revision == 2
    assert history.revisions[0].updated is None and history.revisions[0].rollback_revision is None
    assert (
        parse_helm_history(encode([revision(rollback_revision=1)])).revisions[0].rollback_revision
        == 1
    )
    assert parse_helm_history(encode([revision()])).revisions[0].rollback_revision is None
    assert not parse_helm_history(b"[]").revisions


@pytest.mark.parametrize(
    "raw",
    [
        [revision(revision="1")],
        [revision(revision=True)],
        [revision(rollback_revision=False)],
        [revision(rollback_revision=-1)],
        [revision(updated="naive")],
        [revision(), revision()],
        [None],
        [revision(revision=n) for n in range(1, 203)],
    ],
)
def test_history_rejects_duplicates_invalid_integer_and_overflow(raw):
    with pytest.raises(AppError):
        parse_helm_history(encode(raw))


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"\xff",
        b"[] []",
        b'{"same":1,"same":2}',
        b"[NaN]",
        b"[Infinity]",
        b"[-Infinity]",
        b"[1,]",
        b'["\\ud800"] invalid',
    ],
)
def test_json_rejects_nonstandard_ambiguous_and_sensitive_parser_errors(data):
    with pytest.raises(HelmProblem) as caught:
        helm_json(data)
    assert "same" not in str(caught.value) and "source" not in str(caught.value)


def test_json_and_tree_limits_cover_non_json_structures_and_parser_recursion():
    assert helm_json(b'{"nested":[true,null,1,1.25,"plain"]}') == {
        "nested": [True, None, 1, 1.25, "plain"]
    }
    for value in ({1: "invalid"}, {"x" * 4097: "value"}, {"x": object()}, [0] * 50_001):
        with pytest.raises(HelmProblem):
            helm_structure(value)
    nested = 0
    for _ in range(65):
        nested = [nested]
    with pytest.raises(HelmProblem):
        helm_structure(nested)
    for data in (b" " * (MAX_HELM_LIST_BYTES + 1), None):
        with pytest.raises(HelmProblem, match="limit"):
            helm_json(data, limit=MAX_HELM_LIST_BYTES)
    with pytest.raises(HelmProblem):
        helm_json(b"[" * 5000 + b"0" + b"]" * 5000)
    for data in (b"null", b"{}", b"[null]", b"[3]"):
        with pytest.raises(HelmProblem):
            parse_helm_list(data, SCOPE)


@pytest.mark.parametrize("driver", list(HelmDriver))
def test_storage_identity_requires_actual_metadata_uid_and_opaque_version(driver):
    result = parse_storage_identity(storage(), KEY, driver, 3)
    assert result.uid == "uid-3" and result.resource_version == "opaque/3"
    assert result.driver == driver


@pytest.mark.parametrize(
    "field,value",
    [
        ("apiVersion", "v1"),
        ("kind", "Secret"),
        ("metadata", None),
        ("data", {}),
        ("metadata.namespace", "other"),
        ("metadata.name", "sh.helm.release.v1.demo.v2"),
        ("metadata.uid", ""),
        ("metadata.uid", None),
        ("metadata.resourceVersion", ""),
        ("metadata.resourceVersion", "bad\x1b"),
        ("metadata.labels", None),
        ("metadata.labels.owner", "other"),
        ("metadata.labels.name", "other"),
        ("metadata.labels.version", "2"),
        ("metadata.labels.version", "03"),
        ("metadata.labels.status", ""),
    ],
)
def test_storage_rejects_full_body_or_wrong_identity_and_labels(field, value):
    raw = storage()
    destination = raw
    *parts, name = field.split(".")
    for part in parts:
        destination = destination[part]
    destination[name] = value
    with pytest.raises(HelmProblem):
        parse_storage_identity(raw, KEY, HelmDriver.SECRET, 3)


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, HelmDriver.SECRET),
        ("", HelmDriver.SECRET),
        ("secret", HelmDriver.SECRET),
        ("secrets", HelmDriver.SECRET),
        ("configmap", HelmDriver.CONFIGMAP),
        ("configmaps", HelmDriver.CONFIGMAP),
    ],
)
def test_storage_driver_aliases_are_canonical(value, expected):
    settings = helm_settings({} if value is None else {"HELM_DRIVER": value})
    assert settings.driver == expected


@pytest.mark.parametrize("value", ["sql", "memory", "unknown", "SECRET", " secret"])
def test_unsupported_storage_never_falls_back(value):
    with pytest.raises(HelmProblem, match="only"):
        helm_settings({"HELM_DRIVER": value})


@pytest.mark.parametrize("text,expected", [(b"v3.22.1", V3), (b"v4.3.1\n", V4)])
def test_exact_supported_cli_versions(text, expected):
    assert parse_helm_version(text) == expected
    assert helm_version_argv(SETTINGS) == ("helm", "version", "--template={{.Version}}")


@pytest.mark.parametrize(
    "data",
    [
        b"v3.22.0",
        b"v4.3.2",
        b"v4.3.1+other",
        b"v4.3.1-rc.1",
        b"v5.0.0",
        b"\xff",
        b"x" * 16385,
        None,
    ],
)
def test_version_probe_rejects_unqualified_or_invalid_output(data):
    with pytest.raises(HelmProblem):
        parse_helm_version(data)


def test_environment_is_private_and_preserves_captured_credential_helper_settings():
    original = {
        "PATH": "/owned/bin",
        "PROVIDER_AUTH": "synthetic",
        "HELM_DRIVER": "sql",
        "HELM_KUBEAPISERVER": "hostile",
        "HELM_KUBECONTEXT": "hostile",
        "HELM_KUBEUNKNOWN": "hostile",
        "HELM_NAMESPACE": "hostile",
        "HELM_DEBUG": "true",
        "HELM_MAX_HISTORY": "1",
        "HELM_DRIVER_SQL_CONNECTION_STRING": "hostile",
        "KUBECONFIG": "/caller/config",
        "HELM_NO_PLUGINS": "0",
    }
    snapshot = dict(original)
    result = dict(helm_environment(original, HelmDriver.CONFIGMAP, KUBECONFIG))
    assert original == snapshot
    assert result == {
        "PATH": "/owned/bin",
        "PROVIDER_AUTH": "synthetic",
        "HELM_DRIVER": "configmap",
        "HELM_NO_PLUGINS": "1",
        "NO_COLOR": "1",
        "KUBECONFIG": str(KUBECONFIG),
    }
    assert "KUBECONFIG" not in dict(helm_environment(original, HelmDriver.SECRET))
    with pytest.raises(HelmProblem):
        helm_environment(original, "secret")


def test_list_argv_uses_exact_version_specific_state_flags_and_explicit_scope():
    base = (
        "helm",
        "--kubeconfig=/private/scope/config",
        "--kube-context=owned-context",
        "--namespace=team",
        "--debug=false",
    )
    assert helm_list_argv(SETTINGS, V3, SCOPE, KUBECONFIG) == (
        *base,
        "list",
        "--all",
        "--max=501",
        "--offset=0",
        "--output=json",
    )
    assert helm_list_argv(SETTINGS, V4, SCOPE, KUBECONFIG) == (
        *base,
        "list",
        "--max=501",
        "--offset=0",
        "--output=json",
    )
    all_argv = helm_list_argv(SETTINGS, V4, ALL, KUBECONFIG)
    assert "--namespace=default" in all_argv and all_argv[-1] == "--all-namespaces"
    for version in (V3, V4):
        assert helm_status_argv(SETTINGS, version, ALL, KUBECONFIG, KEY, 3)[-4:] == (
            "status",
            "demo",
            "--revision=3",
            "--output=json",
        )
        assert "--namespace=team" in helm_status_argv(SETTINGS, version, ALL, KUBECONFIG, KEY, 3)
        assert helm_history_argv(SETTINGS, version, SCOPE, KUBECONFIG, KEY)[-4:] == (
            "history",
            "demo",
            "--max=201",
            "--output=json",
        )


@pytest.mark.parametrize(
    "kind,tail",
    [
        (HelmDocumentKind.NOTES, ("get", "notes", "demo", "--revision=2")),
        (HelmDocumentKind.MANIFEST, ("get", "manifest", "demo", "--revision=2")),
        (HelmDocumentKind.VALUES, ("get", "values", "demo", "--revision=2", "--output=json")),
        (
            HelmDocumentKind.ALL_VALUES,
            ("get", "values", "demo", "--revision=2", "--output=json", "--all"),
        ),
    ],
)
def test_document_argv_never_infers_all_values_or_implicit_revision(kind, tail):
    assert helm_document_argv(SETTINGS, V4, SCOPE, KUBECONFIG, KEY, 2, kind)[-len(tail) :] == tail


@pytest.mark.parametrize(
    "version,wait,run_hooks,expected_wait",
    [
        (V3, True, False, "true"),
        (V3, False, True, "false"),
        (V4, True, False, "legacy"),
        (V4, False, True, "hookOnly"),
    ],
)
def test_rollback_argv_contains_only_reviewed_effect_options(
    version, wait, run_hooks, expected_wait
):
    head = parse_storage_identity(storage(), KEY, HelmDriver.SECRET, 3)
    prior = replace(
        head,
        revision=1,
        storage_name="sh.helm.release.v1.demo.v1",
        uid="uid-1",
        resource_version="opaque/1",
        status="superseded",
    )
    intent = HelmRollbackIntent(
        UUID(int=1),
        HelmTarget(HelmRequest(ALL, 1), head),
        prior,
        HelmRollbackOptions(run_hooks, wait, 42),
        (),
    )
    argv = helm_rollback_argv(SETTINGS, version, KUBECONFIG, intent)
    expected = (
        "helm",
        "--kubeconfig=/private/scope/config",
        "--kube-context=owned-context",
        "--namespace=team",
        "--debug=false",
        "rollback",
        "demo",
        "1",
        f"--no-hooks={str(not run_hooks).lower()}",
        "--timeout=42s",
        "--history-max=0",
        f"--wait-for-jobs={str(wait).lower()}",
        f"--wait={expected_wait}",
    )
    assert argv == (*expected, "--server-side=auto") if version == V4 else argv == expected


@pytest.mark.parametrize(
    "builder",
    [
        lambda: helm_list_argv(HelmSettings(driver=HelmDriver.CONFIGMAP), V3, SCOPE, KUBECONFIG),
        lambda: helm_list_argv(SETTINGS, None, SCOPE, KUBECONFIG),
        lambda: helm_list_argv(SETTINGS, V3, SCOPE, Path("relative")),
        lambda: helm_list_argv(SETTINGS, V3, SCOPE, "/private/config"),
        lambda: helm_status_argv(
            SETTINGS, V3, SCOPE, KUBECONFIG, HelmReleaseKey("other", "demo"), 1
        ),
        lambda: helm_status_argv(SETTINGS, V3, SCOPE, KUBECONFIG, KEY, False),
        lambda: helm_document_argv(SETTINGS, V3, SCOPE, KUBECONFIG, KEY, 1, "values"),
    ],
)
def test_argv_builders_refuse_mismatched_scope_invalid_revision_and_untyped_kind(builder):
    with pytest.raises(AppError):
        builder()
