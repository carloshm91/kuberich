"""Curated default documents expose bounded authored facts rather than arbitrary bodies."""

import json
from dataclasses import asdict

import pytest
import yaml

from kuberich.domain.curated import CuratedDetails, DetailSection, curated_details, curated_families
from kuberich.domain.curated_navigation import CuratedLink, ReferenceDestination
from kuberich.domain.inspection import REDACTED, inspection_documents, redacted
from kuberich.domain.relationships import RelationshipRef
from kuberich.domain.resources import ApiResource, resource_record
from kuberich.domain.targets import ResourceTarget, SessionIdentity
from tests.support.curated_access import KINDS, access_manifest, access_resource
from tests.support.curated_admission import KINDS as ADMISSION_KINDS
from tests.support.curated_admission import admission_manifest, admission_resource
from tests.support.curated_policy import policy_manifest, policy_resource
from tests.support.curated_scaling import SAMPLES, api, record


def capture(resource, item):
    return ResourceTarget(
        SessionIdentity("owned", 1),
        resource.group,
        resource.name,
        item.namespace,
        item.name,
        item.uid,
    )


def fixture(family):
    if family.kind in SAMPLES:
        resource = api(family.kind)
        return resource, record(resource)
    if family.kind in KINDS:
        resource = access_resource(family.kind)
        raw = access_manifest(family.kind)
    elif family.resource in ADMISSION_KINDS:
        resource = admission_resource(family.resource)
        raw = admission_manifest(family.resource)
    else:
        resource = policy_resource(family.resource)
        raw = policy_manifest(family.resource)
    return resource, resource_record(resource, raw)


@pytest.mark.parametrize("family", curated_families(), ids=lambda item: item.kind)
def test_all_curated_families_have_allowlisted_details_and_full_bounded_action_contract(family):
    resource, original = fixture(family)
    raw = original.manifest
    raw["unlisted"] = {"note": "synthetic-unlisted-body-canary"}
    raw.setdefault("status", {})["privateFreeText"] = "synthetic-unlisted-status-canary"
    raw["metadata"]["labels"] = {"arbitrary": "synthetic-unlisted-label-canary"}
    item = resource_record(resource, raw)
    curated = curated_details(resource, item)
    result = inspection_documents(raw, (), capture(resource, item), curated)
    assert "synthetic-unlisted" not in result.details
    assert "spec:" not in result.details and "status:" not in result.details
    assert "sections:" in result.details
    assert (
        len(json.dumps(asdict(curated), ensure_ascii=False, separators=(",", ":")).encode())
        <= 65536
    )
    assert sum(len(part.rows) for part in curated.sections) + len(curated.links) <= 256
    assert yaml.safe_load(result.details)["metadata"]["uid"] == item.uid
    assert "synthetic-unlisted-body-canary" in result.yaml


def test_only_link_labels_provenance_availability_reach_default_documents():
    resource = api("Lease")
    item = record(resource)
    destination = ReferenceDestination(
        RelationshipRef(
            "v1",
            "Node",
            None,
            "synthetic-destination-not-for-display",
            "synthetic-uid-not-for-display",
            None,
        ),
        True,
    )
    curated = CuratedDetails(
        (DetailSection("Reported facts", ("Fact", "Value"), (("Count", "0"),), 2),),
        (
            CuratedLink("hidden-key", "Declared owner", "Declared UID source", destination),
            CuratedLink(
                "disabled", "Other owner", "Declared UID source", None, "Owner UID unavailable"
            ),
            CuratedLink("missing", "Missing owner", "Declared source", None),
        ),
        ("Reported values only",),
    )
    result = inspection_documents(item.manifest, (), capture(resource, item), curated)
    assert "synthetic-destination-not-for-display" not in result.details
    assert "synthetic-uid-not-for-display" not in result.details
    assert "hidden-key" not in result.details
    assert "Declared owner" in result.details and "Declared UID source" in result.details
    value = yaml.safe_load(result.details)
    assert value["sections"][0]["omittedRows"] == 2
    assert [link["availability"] for link in value["links"]] == [
        "Available",
        "Owner UID unavailable",
        "Unavailable",
    ]


def test_unsupported_known_api_document_has_explicit_metadata_fallback_and_redacted_yaml():
    resource = ApiResource(
        "autoscaling",
        "v9",
        "horizontalpodautoscalers",
        "HorizontalPodAutoscaler",
        True,
        frozenset({"get"}),
    )
    item = resource_record(
        resource,
        {
            "metadata": {"name": "owned", "namespace": "team", "uid": "owned-uid"},
            "spec": {"future": "synthetic-future-body-canary"},
            "status": {"observed": "synthetic-future-status-canary"},
        },
    )
    result = inspection_documents(item.manifest, (), capture(resource, item), None, True)
    assert "metadata only" in result.details
    assert "synthetic-future" not in result.details
    assert "synthetic-future-body-canary" in result.yaml


def test_ca_bundle_concealment_applies_at_every_nested_path_without_hiding_presence():
    raw = {
        "webhooks": [
            {
                "clientConfig": {
                    "caBundle": "synthetic-public-ca-canary",
                    "service": {"name": "owned"},
                }
            }
        ]
    }
    safe = redacted(raw)
    assert safe["webhooks"][0]["clientConfig"]["caBundle"] == REDACTED
    assert safe["webhooks"][0]["clientConfig"]["service"]["name"] == "owned"
