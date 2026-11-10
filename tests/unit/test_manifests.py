"""Local-source parsing, discovered destinations and exact safe request decisions."""

import json
from dataclasses import replace
from uuid import uuid4

import pytest

from kuberich.domain.editing import parse_manifest, parse_manifest_documents
from kuberich.domain.exports import DirectoryRef, FileIdentity
from kuberich.domain.manifests import (
    LAST_APPLIED,
    FrozenManifestSource,
    ManifestDisclosureIntent,
    ManifestFileSnapshot,
    ManifestPlan,
    ManifestPlanItem,
    ManifestSaveIntent,
    ManifestScope,
    canonical_manifest,
    create_manifest_intent,
    manifest_config_preview,
    manifest_documents,
    manifest_pages,
    manifest_preview,
    manifest_source_digest,
    manifest_status,
    manifest_update_intent,
    resolve_manifest,
)
from kuberich.domain.mutations import MutationResult, MutationState, decode_patch
from kuberich.domain.resources import ApiResource, Discovery, resource_record
from kuberich.domain.targets import ResourceAddress, ResourceTarget, SessionIdentity
from kuberich.errors import AppError


def resource(namespaced=True):
    return ApiResource(
        "",
        "v1",
        "configmaps",
        "ConfigMap",
        namespaced,
        frozenset({"get", "create", "patch", "delete"}),
    )


def document(value=None):
    value = value or {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {"name": "owned"},
        "data": {"ordinary": "payload-sentinel"},
    }
    return manifest_documents(canonical_manifest(value), source_path="source.yaml")[0]


def scope(namespace="team"):
    return ManifestScope(session=SessionIdentity("owned-context", 1), namespace=namespace)


def test_multidoc_json_empty_and_list_expansion_preserve_exact_bytes():
    raw = b'# comment\n---\n{"apiVersion":"v1","kind":"List","items":[{"apiVersion":"v1","kind":"ConfigMap","metadata":{"name":"one","namespace":""}}]}\n---\n\n---\napiVersion: v1\nkind: Secret\nmetadata: {name: two}\nstringData: {key: opaque}\n'
    docs = manifest_documents(raw, source_path="selected.yaml")
    assert [(item.ordinal, item.kind, item.name, item.namespace) for item in docs] == [
        (1, "ConfigMap", "one", None),
        (2, "Secret", "two", None),
    ]
    assert "namespace" not in json.loads(docs[0].body)["metadata"]
    assert json.loads(docs[1].body)["stringData"] == {"key": "opaque"}
    assert parse_manifest_documents(b"# empty", max_bytes=100, max_documents=1) == ()
    with pytest.raises(AppError):
        parse_manifest(b"a: 1\n---\nb: 2")


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"\xff",
        b"x: [invalid",
        b"x: .nan",
        b"x: .inf",
        b"x: !!timestamp 2026-01-01",
        b"x: !!set {a: null}",
        b"x: 1\nx: 2",
        b"1: value",
        b"x: &a []\ny: *a",
        b"[]",
        b'x: "\\uD800"',
        b"x: [" + b"[" * 64 + b"0" + b"]" * 65,
        b"x: [" + b"0," * 100000 + b"0]",
    ],
)
def test_stream_parser_rejects_unbounded_or_non_json_input_without_source(data):
    with pytest.raises(AppError) as error:
        parse_manifest_documents(data, max_bytes=1024 * 1024, max_documents=100)
    assert "x:" not in str(error.value)


@pytest.mark.parametrize(
    "limits", [(0, 1), (True, 1), (9 * 1024 * 1024, 1), (10, 0), (10, True), (10, 257), (1, 1)]
)
def test_invalid_stream_budgets_fail(limits):
    with pytest.raises(AppError):
        parse_manifest_documents(b"x: 1", max_bytes=limits[0], max_documents=limits[1])


def test_document_count_is_checked_before_construction():
    with pytest.raises(AppError, match="document limit"):
        parse_manifest_documents(b"x: 1\n---\ny: 2", max_bytes=100, max_documents=1)


@pytest.mark.parametrize(
    "value",
    [
        {},
        {"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"generateName": "x"}},
        {"apiVersion": "v1", "kind": "OtherList", "metadata": {"name": "x"}},
        {"apiVersion": "v1", "kind": "List", "items": [1]},
        {"apiVersion": "v1", "kind": "List", "items": {}},
        {"apiVersion": "v1", "kind": "List", "items": [], "other": True},
        {
            "apiVersion": "v1",
            "kind": "List",
            "items": [{"apiVersion": "v1", "kind": "List", "items": []}],
        },
        {"apiVersion": "v1", "kind": 12, "metadata": {"name": "x"}},
        {"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": "x", "uid": "old"}},
        {"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": "x"}, "status": {}},
    ],
)
def test_manifest_resource_shape_and_server_identity_are_refused(value):
    with pytest.raises(AppError):
        manifest_documents(canonical_manifest(value), source_path="source.yaml")


def test_resource_document_and_expanded_limits():
    with pytest.raises(AppError, match="no resources"):
        manifest_documents(b"# only comments", source_path="empty")
    with pytest.raises(AppError, match="100 resources"):
        manifest_documents(
            canonical_manifest(
                {"apiVersion": "v1", "kind": "List", "items": [json.loads(document().body)] * 101}
            ),
            source_path="many",
        )
    with pytest.raises(AppError, match="1 MiB"):
        manifest_documents(
            canonical_manifest({**json.loads(document().body), "data": {"key": "x" * 1048576}}),
            source_path="large",
        )


def test_exact_discovered_gvk_and_namespace_resolution():
    served = resource()
    descriptor, target, body = resolve_manifest(document(), Discovery((served,)), scope())
    assert descriptor is served and target.uid is None and target.namespace == "team"
    assert json.loads(body)["metadata"]["namespace"] == "team"
    explicit = document(
        {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {"name": "owned", "namespace": "other"},
        }
    )
    assert resolve_manifest(explicit, Discovery((served,)), scope(None))[1].namespace == "other"
    cluster = resource(False)
    assert resolve_manifest(document(), Discovery((cluster,)), scope())[1].namespace is None
    for discovery, selected, selected_scope in [
        (Discovery(()), document(), scope()),
        (Discovery((served, served)), document(), scope()),
        (Discovery((replace(served, verbs=frozenset({"get"})),)), document(), scope()),
        (Discovery((replace(served, name="configmaps/status"),)), document(), scope()),
        (Discovery((cluster,)), explicit, scope()),
        (Discovery((served,)), document(), scope(None)),
    ]:
        with pytest.raises(AppError):
            resolve_manifest(selected, discovery, selected_scope)


def test_create_preserves_array_positions_and_records_nulls_before_pruning():
    served = resource()
    address = ResourceAddress(
        session=scope().session, group="", resource="configmaps", namespace="team", name="owned"
    )
    raw = {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {"name": "owned", "namespace": "team"},
        "nullable": None,
        "array": [None, {"nil": None, "keep": "yes"}, False],
        "nested": {"nil": None},
    }
    intent = create_manifest_intent(served, address, canonical_manifest(raw))
    body = json.loads(intent.body)
    assert (
        "nullable" not in body
        and body["array"] == [None, {"keep": "yes"}, False]
        and body["nested"] == {}
    )
    recorded = json.loads(body["metadata"]["annotations"][LAST_APPLIED])
    assert recorded["nullable"] is None and recorded["array"][1]["nil"] is None
    assert LAST_APPLIED not in recorded["metadata"]["annotations"]
    assert intent.path == "/api/v1/namespaces/team/configmaps" and intent.effects == (
        "create configmaps/owned",
    )
    assert "yes" not in repr(intent)


@pytest.mark.parametrize(
    "change",
    [
        {"apiVersion": "v2"},
        {"kind": "Secret"},
        {"status": {}},
        {"metadata": {"name": "other", "namespace": "team"}},
        {"metadata": {"name": "owned", "namespace": "team", "uid": "old"}},
        {"metadata": {"name": "owned", "namespace": "team", "annotations": {"a": 1}}},
    ],
)
def test_create_refuses_identity_and_annotation_changes(change):
    raw = {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {"name": "owned", "namespace": "team"},
        **change,
    }
    address = ResourceAddress(
        session=scope().session, group="", resource="configmaps", namespace="team", name="owned"
    )
    with pytest.raises(AppError):
        create_manifest_intent(resource(), address, canonical_manifest(raw))


def test_create_bounds_final_annotations_and_request_body():
    address = ResourceAddress(
        session=scope().session, group="", resource="configmaps", namespace="team", name="owned"
    )
    raw = {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {"name": "owned", "namespace": "team"},
        "spec": {"data": "x" * 270000},
    }
    with pytest.raises(AppError, match="annotations"):
        create_manifest_intent(resource(), address, canonical_manifest(raw))
    with pytest.raises(AppError):
        create_manifest_intent(
            replace(resource(), verbs=frozenset({"get"})), address, document().body
        )


def test_update_normalizes_generation_status_and_managed_fields_after_identity_check():
    served = resource()
    raw = {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {
            "name": "owned",
            "namespace": "team",
            "uid": "uid-one",
            "resourceVersion": "rv-one",
            "generation": 1,
            "managedFields": [],
            "labels": {"unrelated": "preserved"},
        },
        "data": {"managed": "old"},
        "status": {"phase": "old"},
    }
    baseline = resource_record(served, raw, "team")
    target = ResourceTarget(scope().session, "", "configmaps", "team", "owned", "uid-one")
    preview = json.loads(canonical_manifest(raw))
    preview["metadata"]["generation"] = 2
    preview["metadata"]["managedFields"] = [{"manager": "server"}]
    preview["status"] = {"phase": "new"}
    preview["data"] = {"managed": "new"}
    intent = manifest_update_intent(served, target, baseline, canonical_manifest(preview))
    assert intent is not None
    patch = decode_patch(intent.body)
    assert patch[:2] == [
        {"op": "test", "path": "/metadata/uid", "value": "uid-one"},
        {"op": "test", "path": "/metadata/resourceVersion", "value": "rv-one"},
    ]
    assert patch[2:] == [{"op": "replace", "path": "/data/managed", "value": "new"}]
    assert manifest_update_intent(served, target, baseline, canonical_manifest(raw)) is None
    for field in ("name", "namespace", "uid", "resourceVersion"):
        wrong = json.loads(canonical_manifest(preview))
        wrong["metadata"][field] = "wrong"
        with pytest.raises(AppError, match="identity/version"):
            manifest_update_intent(served, target, baseline, canonical_manifest(wrong))


def test_redacted_previews_list_children_paging_and_config_structure():
    raw = {
        "apiVersion": "v1",
        "kind": "List",
        "items": [
            json.loads(document().body),
            {
                "apiVersion": "v1",
                "kind": "Secret",
                "metadata": {"name": "two"},
                "stringData": {"key": "secret-sentinel"},
            },
        ],
    }
    pages = manifest_preview(None, canonical_manifest(raw))
    assert "payload-sentinel" not in str(pages) and "secret-sentinel" not in str(pages)
    assert "[REDACTED]" in str(pages)
    assert "Unchanged" in manifest_preview(document().body, document().body)[0]
    assert (
        "hidden"
        in manifest_preview(
            document().body, document().body.replace(b"payload-sentinel", b"changed-payload")
        )[0]
    )
    assert (
        "reviewed"
        in manifest_preview(
            document().body,
            document(
                {"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": "renamed"}}
            ).body,
        )[0]
    )
    config = manifest_config_preview(
        b"kind: Kustomization\nconfigMapGenerator:\n- name: sample\n  literals: [key=raw-sentinel]\npatches:\n- patch: raw-patch-sentinel\n"
    )
    assert "raw-sentinel" not in str(config) and "raw-patch-sentinel" not in str(config)
    assert "configMapGenerator" in str(config)
    assert len(manifest_pages("é" * 140000)) == 2
    assert max(len(page.encode()) for page in manifest_pages("é" * 140000)) <= 262144
    with pytest.raises(AppError):
        manifest_config_preview(b"# empty")


def test_status_only_publishes_allowlisted_machine_codes():
    body = canonical_manifest(
        {
            "kind": "Status",
            "reason": "Invalid",
            "message": "message-secret-sentinel",
            "details": {
                "causes": [
                    {
                        "reason": "FieldValueInvalid",
                        "field": "field-secret-sentinel",
                        "message": "cause-secret-sentinel",
                    },
                    {"reason": "unknown-secret-sentinel"},
                    1,
                ]
            },
        }
    )
    result = manifest_status(422, body)
    assert (
        result.state is MutationState.REJECTED
        and "Invalid" in result.message
        and "FieldValueInvalid" in result.message
    )
    assert "secret-sentinel" not in result.message and "withheld" in result.message
    for raw in (
        b"",
        b"invalid",
        b"x" * 65537,
        b"kind: Other",
        b"kind: Status\nreason: unknown",
        b"kind: Status\ndetails: null",
    ):
        assert "secret" not in manifest_status(403, raw).message


def test_frozen_source_and_plan_repr_do_not_retain_raw_body_display(tmp_path):
    identity = FileIdentity(
        device=1, inode=2, size=3, mtime_ns=4, ctime_ns=5, mode=0o100600, uid=1, nlink=1
    )
    root = DirectoryRef(path=tmp_path, device=1, inode=2)
    snapshot = ManifestFileSnapshot(
        relative_path="input.yaml",
        identity=identity,
        sha256="a" * 64,
        data=b"raw-sensitive-sentinel",
    )
    selected = document()
    source = FrozenManifestSource(
        identity=uuid4(),
        root=root,
        kind="file",
        relative_path="input.yaml",
        files=(snapshot,),
        documents=(selected,),
        source_sha256=manifest_source_digest((snapshot,)),
        rendered_sha256="b" * 64,
    )
    disclosure = ManifestDisclosureIntent(identity=uuid4(), source=snapshot, root=root)
    save = ManifestSaveIntent(
        identity=uuid4(),
        original=snapshot,
        root=root,
        body=b"raw-sensitive-sentinel",
        preview_pages=("safe",),
    )
    target = ResourceAddress(
        session=scope().session, group="", resource="configmaps", namespace="team", name="owned"
    )
    item = ManifestPlanItem(
        document=selected,
        resource=resource(),
        target=target,
        change="unchanged",
        request=None,
        validation=MutationResult(MutationState.SUCCEEDED, "safe"),
        preview_pages=("safe",),
    )
    plan = ManifestPlan(
        identity=uuid4(),
        source_identity=source.identity,
        source_sha256=source.source_sha256,
        scope=scope(),
        action="apply",
        items=(item,),
    )
    assert plan.ready and plan.effects == (
        "unchanged v1/configmaps/owned namespace=team UID=(not captured) resourceVersion=(not captured)",
    )
    assert plan.targets == (target,)
    existing = ResourceTarget(scope().session, "", "configmaps", None, "owned", "actual-uid")
    scoped = replace(plan, items=(replace(item, target=existing, resource_version="opaque-rv"),))
    assert scoped.targets == (existing,)
    assert "namespace=(cluster) UID=actual-uid resourceVersion=opaque-rv" in scoped.effects[0]
    assert replace(plan, items=()).targets == ()
    assert not replace(plan, items=()).ready
    assert not replace(
        plan, items=(replace(item, validation=MutationResult(MutationState.BLOCKED, "safe")),)
    ).ready
    assert "raw-sensitive-sentinel" not in repr((source, disclosure, save, plan))
    with pytest.raises(AppError):
        canonical_manifest({"x": float("nan")})


def test_expanded_json_byte_budget_accounts_for_yaml_to_json_growth():
    import yaml

    # Quoted YAML scalars grow when canonical JSON escapes their quote characters.
    values = [
        {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {"name": f"owned-{index}"},
            "spec": {"opaque": '"' * 400000},
        }
        for index in range(11)
    ]
    raw = yaml.safe_dump_all(values).encode()
    assert len(raw) < 8 * 1024 * 1024
    with pytest.raises(AppError, match="Expanded manifest source"):
        manifest_documents(raw, source_path="expanded.yaml")


def test_create_rechecks_final_request_budget_after_apply_annotation_expansion(monkeypatch):
    from kuberich.domain import manifests

    address = ResourceAddress(
        session=scope().session, group="", resource="configmaps", namespace="team", name="owned"
    )
    raw = canonical_manifest(
        {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {"name": "owned", "namespace": "team"},
        }
    )
    monkeypatch.setattr(manifests, "MAX_MANIFEST_BYTES", len(raw) + 20)
    with pytest.raises(AppError, match="including apply annotation"):
        create_manifest_intent(resource(), address, raw)


@pytest.mark.parametrize(
    "path,shown",
    [
        ("spec.replicas", True),
        ("spec.template.spec.containers[0].image", True),
        ("metadata.name", True),
        ("spec.privateSentinel", False),
        ('data["key-private-sentinel"]', False),
        ("spec.\x1b[31mreplicas", False),
        ("spec.containers[1000].image", False),
        ("spec." * 17 + "replicas", False),
        ("x" * 257, False),
        (None, False),
    ],
)
def test_status_fields_publish_only_bounded_known_schema_tokens(path, shown):
    body = canonical_manifest(
        {
            "kind": "Status",
            "reason": "Invalid",
            "details": {"causes": [{"reason": "FieldValueInvalid", "field": path}]},
        }
    )
    message = manifest_status(422, body).message
    if shown:
        assert path in message
    else:
        assert "private" not in message and (path is None or path not in message)


@pytest.mark.parametrize("scalar", [b"null", b"~", b"Null", b"!!null", b'!!null ""'])
def test_explicit_null_scalar_document_is_never_skipped_inside_manifest_stream(scalar):
    raw = document().body + b"\n---\n" + scalar + b"\n"
    with pytest.raises(AppError):
        manifest_documents(raw, source_path="mixed.yaml")
    with pytest.raises(AppError):
        parse_manifest_documents(scalar, max_bytes=100, max_documents=1)
