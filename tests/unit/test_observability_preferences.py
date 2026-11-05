"""History configuration is explicit, context-local and validated while offline."""

import pytest

from kuberich.config.observability import observability_from, parse_observability
from kuberich.config.schema import ConfigDocument, parse_document
from kuberich.errors import AppError

BACKEND = {"namespace": "observability", "service": "prometheus"}


def test_optional_context_history_survives_document_round_trip_without_mutation():
    raw = {
        "schema_version": 1,
        "observability": {
            "schema_version": 1,
            "history": BACKEND,
            "contexts": {
                "owned": {"history": {**BACKEND, "service": "other"}},
                "disabled": {"history": None},
            },
        },
    }
    document = parse_document(raw)
    result = observability_from(document)
    assert result.history.service == "prometheus"
    assert result.for_context("owned").history.service == "other"
    assert result.for_context("disabled").history is None
    assert result.for_context("different").history is result.history
    assert document.to_mapping()["observability"] == raw["observability"]
    assert not document.unknown
    assert observability_from(ConfigDocument()).history is None
    assert parse_observability({}).history is None


@pytest.mark.parametrize(
    "value",
    [
        None,
        [],
        {"unknown": True},
        {"schema_version": True},
        {"schema_version": 2},
        {"history": []},
        {"history": {"url": "https://untrusted.example.test"}},
        {"history": {**BACKEND, "matchers": []}},
        {"history": {"namespace": "one"}},
        {"history": {**BACKEND, "namespace": 3}},
        {"history": {**BACKEND, "port": True}},
        {"history": {**BACKEND, "scheme": 3}},
        {"history": {**BACKEND, "cluster_label": 3}},
        {"history": {**BACKEND, "cluster_value": 3}},
        {"contexts": []},
        {"contexts": {str(i): {} for i in range(129)}},
        {"contexts": {3: {}}},
        {"contexts": {"": {}}},
        {"contexts": {"a" * 254: {}}},
        {"contexts": {"bad\n": {}}},
        {"contexts": {"owned": {"contexts": {}}}},
    ],
)
def test_invalid_configuration_never_initiates_discovery_or_installs_backend(value):
    with pytest.raises(AppError):
        parse_observability(value)


def test_explicit_cluster_binding_and_matchers_are_preserved():
    result = parse_observability(
        {
            "history": {
                **BACKEND,
                "port": 9443,
                "scheme": "https",
                "matchers": {"job": "cadvisor"},
                "cluster_label": "cluster",
                "cluster_value": "owned",
            }
        }
    )
    assert result.history.labels("team") == (
        ("cluster", "owned"),
        ("job", "cadvisor"),
        ("namespace", "team"),
    )
