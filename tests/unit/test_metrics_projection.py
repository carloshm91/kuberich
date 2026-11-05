"""Numeric reports enrich cached rows without mixing resource identities or views."""

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

from kuberich.domain.metrics import MetricReport, MetricsSnapshot, MetricStatus, ResourceAmount
from kuberich.domain.namespaces import namespace_row
from kuberich.domain.pods import pod_row
from kuberich.domain.registry import RESOURCE_ALIASES, resource_row
from kuberich.domain.resources import ApiResource, resource_record
from kuberich.domain.targets import SessionIdentity
from kuberich.domain.views import ResourceScope, ViewObservation
from kuberich.services.metrics_projection import with_metrics
from tests.support.pods import pod, record
from tests.support.standard import api, row_record


def test_projection_enriches_pod_and_standard_numeric_values_and_leaves_other_views_intact():
    report = MetricReport(
        MetricStatus.VALID, ResourceAmount(usage=Decimal(".25")), timestamp=datetime.now(UTC)
    )
    pod_value = pod_row(record(pod("api")))
    definition = RESOURCE_ALIASES["nodes"]
    node_value = resource_row(row_record(definition), definition)
    view = ViewObservation(
        scope=ResourceScope(SessionIdentity("owned", 1), api(definition), None),
        metrics=MetricsSnapshot(((node_value.uid, report), (pod_value.uid, report))),
    )
    assert with_metrics((pod_value,), view)[0].metrics is report
    projected = with_metrics((node_value,), view)[0]
    index = [column.key for column in definition.columns].index("cpu")
    assert projected.values[index].sort == Decimal(".25") and projected.values[index].text == "250"
    assert node_value.values[index].sort is None
    assert with_metrics((node_value,), replace(view, scope=None)) == (node_value,)
    ns_api = ApiResource("", "v1", "namespaces", "Namespace", False, frozenset({"list"}))
    ns_row = namespace_row(
        resource_record(
            ns_api, {"metadata": {"name": "team", "uid": "ns"}, "status": {"phase": "Active"}}
        )
    )
    assert with_metrics((ns_row,), view) == (ns_row,)
    missing = with_metrics((replace(pod_value, uid="replacement"),), view)[0]
    assert missing.metrics.status is MetricStatus.NO_SAMPLE and missing.metrics.cpu.usage is None
    expired_view = replace(view, metrics=replace(view.metrics, cache_expired=True))
    assert with_metrics((pod_value,), expired_view)[0].metrics.status is MetricStatus.STALE
    stale_node = with_metrics((node_value,), expired_view)[0]
    assert stale_node.values[index].text == "N/A" and stale_node.values[index].sort is None
    assert report.cpu.usage == Decimal(".25")
