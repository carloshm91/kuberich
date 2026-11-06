"""EndpointSlice's optional nil lists preserve zero membership and UID evidence."""

from dataclasses import replace

import pytest

from kuberich.domain.relationships import endpoint_references, fact_list
from kuberich.errors import AppError
from tests.support.relationships import ENDPOINTS, SLICES, record


@pytest.mark.parametrize("endpoints", [None, []])
@pytest.mark.parametrize("ports", [None, []])
def test_api_accepted_empty_slice_lists_mean_no_references(endpoints, ports):
    # Actual owned Kubernetes GET and Table in kind-005 emitted endpoints:null.
    assert endpoint_references(SLICES, record(SLICES, endpoints=endpoints, ports=ports)) == ()


def test_null_ports_keep_observed_pod_identity_and_unspecified_readiness():
    source = record(
        SLICES,
        ports=None,
        endpoints=[
            {
                "addresses": ["192.0.2.1"],
                "targetRef": {
                    "apiVersion": "v1",
                    "kind": "Pod",
                    "namespace": "team",
                    "name": "owned",
                    "uid": "pod-uid",
                },
                "conditions": {},
            }
        ],
    )
    (reference,) = endpoint_references(SLICES, source)
    assert reference.target.uid == "pod-uid" and reference.target.namespace == "team"
    assert reference.ports == () and reference.ready is None
    assert reference.details[-2:] == ("serving=unknown", "terminating=unknown")
    with pytest.raises(AppError, match="Incomplete"):
        endpoint_references(SLICES, replace(source, metadata_only=True))


@pytest.mark.parametrize("value", [False, 0, "", {}, [None]])
@pytest.mark.parametrize("field", ["endpoints", "ports"])
def test_malformed_slice_lists_stay_invalid_instead_of_becoming_empty(field, value):
    with pytest.raises(AppError):
        endpoint_references(SLICES, record(SLICES, **{field: value}))


def test_slice_normalization_does_not_change_the_strict_shared_list_contract():
    with pytest.raises(AppError):
        fact_list(None)
    with pytest.raises(AppError):
        endpoint_references(ENDPOINTS, record(ENDPOINTS, subsets=[{"ports": None}]))
