"""Measured zero, bounded quantities, denominator semantics, and current allocation limits."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D

import pytest

from kuberich.domain.metrics import (
    MAX_CONTAINERS,
    MAX_RESOURCES,
    METRIC_KEYS,
    MetricReport,
    MetricsSnapshot,
    MetricStatus,
    ResourceAmount,
    aggregate,
    amount,
    node_sample,
    number,
    percentage,
    pod_budget,
    pod_sample,
    sample_time,
)
from kuberich.domain.quantities import parse_quantity
from kuberich.domain.resources import ApiResource, resource_record
from kuberich.errors import AppError
from tests.support.metrics import NOW, budget_record, budgeted, sample, sampled
from tests.support.pods import record
from tests.support.resources import item


@pytest.mark.parametrize(
    "text,expected",
    [
        ("0", "0"),
        ("+0.5", ".5"),
        (".5", ".5"),
        ("1.", "1"),
        ("1000000n", ".001"),
        ("1000u", ".001"),
        ("10m", ".01"),
        ("1k", "1000"),
        ("1K", "1000"),
        ("1M", "1000000"),
        ("1Mi", "1048576"),
        ("2Gi", "2147483648"),
        ("1e3", "1000"),
        ("1E-3", ".001"),
        ("1E", "1e18"),
        ("1e30", "1e30"),
        ("1e-30", "1e-30"),
    ],
)
def test_quantities_normalize_decimal_binary_and_exponents(text, expected):
    assert parse_quantity(text) == D(expected)


@pytest.mark.parametrize(
    "text",
    [
        None,
        0,
        True,
        "",
        "-1",
        "NaN",
        "Infinity",
        "1e31",
        "1e-31",
        "1e99999999999999999999999999999",
        "1" * 65,
        "1MiB",
        "1.2.3",
        " 1",
        "1 ",
        "1x",
    ],
)
def test_quantities_reject_invalid_unbounded_and_nonfinite_values(text):
    assert parse_quantity(text) is None and amount(text) is None


def test_usage_bounds_display_units_zero_and_percentages_do_not_clamp():
    assert amount(str(2**63)) is None
    assert amount(str(2**63 - 1)) == D(2**63 - 1)
    assert number(None) == "N/A"
    assert number(D(0), "cpu") == number(D(0), "memory") == "0"
    assert number(D("1e-9"), "cpu") == "<0.001"
    assert number(D(".25"), "cpu") == "250"
    assert number(D(2**20), "memory") == "1"
    assert number(D("1.230")) == "1.23"
    assert percentage(D(0), D(1)) == 0
    assert percentage(D(2), D(1)) == 200
    assert percentage(None, D(1)) is None
    assert percentage(D(1), None) is percentage(D(1), D(0)) is None


@pytest.mark.parametrize(
    "request_value,limit,expected_request,expected_limit,pct_request,pct_limit",
    [
        ("100m", "1", "100", "1000", "250", "25"),
        ("0", "0", "0", "0", "N/A", "N/A"),
        (None, None, "N/A", "unlimited", "N/A", "N/A"),
    ],
)
def test_pod_sample_uses_actual_declared_budget_with_explicit_missing_and_zero(
    request_value, limit, expected_request, expected_limit, pct_request, pct_limit
):
    result = pod_sample(budget_record(request=request_value, limit=limit), sampled(), NOW)
    assert result.status is MetricStatus.VALID
    assert result.value("cpu") == ("250", D(".25"))
    assert result.value("memory") == ("64", D(64 * 2**20))
    assert result.value("cpu-req")[0] == expected_request
    assert result.value("cpu-lim")[0] == expected_limit
    assert result.value("cpu-percent-request")[0] == pct_request
    assert result.value("cpu-percent-limit")[0] == pct_limit
    assert result.value("memory-percent-request")[0] == "200"
    assert result.value("memory-percent-limit")[0] == "50"
    assert result.value("window") == ("30", D(30))
    assert result.value("sample")[0] == NOW.isoformat()
    assert result.value("metrics")[0] == "valid"
    assert result.value("extended") == ("—", "—")
    assert dict(result.containers)["app"].cpu.usage == D(".25")
    assert all(isinstance(result.value(key)[0], str) for key in METRIC_KEYS)


@pytest.mark.parametrize(
    "extra",
    [
        {"initContainers": [{"name": "init"}]},
        {"initContainers": [{"name": "sidecar", "restartPolicy": "Always"}]},
        {"overhead": {"cpu": "50m"}},
        {"resources": {"requests": {"cpu": "3"}, "limits": {"cpu": "4"}}},
    ],
)
def test_complex_pod_allocation_preserves_usage_and_labels_uncertain_denominators(extra):
    value = budgeted()
    value["spec"].update(extra)
    result = pod_sample(record(value), sampled(), NOW)
    assert result.cpu.usage == D(".25")
    assert result.value("cpu-req") == ("N/A (budget)", None)
    assert result.value("cpu-lim") == ("N/A (budget)", None)
    assert result.value("cpu-percent-request") == ("N/A", None)
    assert "uncertain Pod allocation" in result.detail


@pytest.mark.parametrize(
    "status",
    [
        {"resize": "InProgress"},
        {"allocatedResources": {"cpu": "1"}},
        {"containerStatuses": [{"allocatedResources": {"cpu": "1"}}]},
        {"containerStatuses": [{"resources": {"requests": {"cpu": "1"}}}]},
    ],
)
def test_resize_allocation_is_not_claimed_as_a_scheduler_total(status):
    value = budgeted()
    value["status"].update(status)
    assert pod_budget(record(value)).cpu.uncertain


def test_extended_resources_are_vendor_neutral_and_never_claim_gpu_utilization():
    value = budgeted()
    value["spec"]["containers"][0]["resources"]["requests"].update(
        {"vendor.example/slices": "2", "other.test/device": "1"}
    )
    value["spec"]["containers"].append(
        {"name": "worker", "resources": {"requests": {"vendor.example/slices": "3"}}}
    )
    result = pod_budget(record(value))
    assert dict(result.extended)["vendor.example/slices"].request == 5
    assert dict(result.extended)["other.test/device"].request == 1
    assert dict(result.extended)["vendor.example/slices"].usage is None
    text = result.value("extended")[0]
    assert "vendor.example/slices req=5" in text and "other.test/device req=1" in text
    uncertain = replace(
        result,
        extended=(
            (
                "vendor.example/slices",
                ResourceAmount(uncertain=True, unlimited=True, capacity=D(4), allocatable=D(3)),
            ),
        ),
    )
    assert "uncertain budget" in uncertain.value("extended")[0]
    assert "cap=4 alloc=3" in uncertain.value("extended")[0]


def test_partial_members_do_not_invent_full_usage_percentages_or_erase_known_usage():
    value = budgeted()
    value["spec"]["containers"].append(
        {"name": "worker", "resources": {"requests": {"cpu": "100m"}, "limits": {"cpu": "1"}}}
    )
    result = pod_sample(record(value), sampled(), NOW)
    assert result.status is MetricStatus.PARTIAL and "1/2 containers" in result.detail
    assert result.cpu.usage == D(".25") and result.cpu.request == D(".2")
    assert result.value("cpu-percent-request") == ("N/A", None)
    complete = pod_sample(budget_record(), sampled(), NOW)
    total = aggregate((complete, result, pod_budget(budget_record())))
    assert total.status is MetricStatus.PARTIAL and "1/3 Pods" in total.detail
    assert total.cpu.usage == D(".5") and total.value("cpu-percent-limit")[1] is None
    assert aggregate((complete, complete)).cpu.percent("request") == 250
    assert aggregate(()).status is MetricStatus.NO_SAMPLE
    assert "membership incomplete" in aggregate((complete,), complete=False).detail


@pytest.mark.parametrize(
    "usage", [{"cpu": "0", "memory": "0"}, {"cpu": "NaN", "memory": "1Mi"}, {}, None]
)
def test_zero_and_incomplete_usage_are_distinct(usage):
    result = pod_sample(
        budget_record(), sampled(sample(containers=[{"name": "app", "usage": usage}])), NOW
    )
    if usage and usage.get("cpu") == "0":
        assert result.status is MetricStatus.VALID and result.cpu.usage == result.memory.usage == 0
    else:
        assert result.status is MetricStatus.PARTIAL and result.cpu.usage is None


def test_no_sample_stale_expiry_identity_and_replacement_creation_are_distinct():
    pod = budget_record(created=NOW - timedelta(seconds=10))
    assert pod_sample(pod, None, NOW).status is MetricStatus.NO_SAMPLE
    assert pod_sample(pod, sampled(uid="old-uid"), NOW).status is MetricStatus.NO_SAMPLE
    assert (
        pod_sample(pod, sampled(now=NOW - timedelta(seconds=20)), NOW).status
        is MetricStatus.NO_SAMPLE
    )
    stale = pod_sample(budget_record(), sampled(now=NOW - timedelta(seconds=61)), NOW)
    assert stale.status is MetricStatus.STALE and stale.cpu.usage is None
    current = pod_sample(pod, sampled(), NOW)
    assert current.fresh(NOW) is current
    expired = current.fresh(NOW + timedelta(seconds=61))
    assert (
        expired.status is MetricStatus.STALE
        and expired.cpu.usage is None
        and expired.cpu.request == current.cpu.request
    )
    assert dict(expired.containers)["app"].cpu.usage is None
    cache = MetricsSnapshot(((pod.uid, current),))
    assert cache.report(pod.uid, NOW) is current
    assert cache.report("missing", NOW).status is MetricStatus.NO_SAMPLE
    assert (
        MetricsSnapshot(((pod.uid, replace(current, timestamp=NOW.replace(year=2000))),))
        .report(pod.uid)
        .status
        is MetricStatus.STALE
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("timestamp", None),
        ("timestamp", "x" * 65),
        ("timestamp", "garbage"),
        ("timestamp", "2026-11-04T12:00:00"),
        ("timestamp", (NOW + timedelta(seconds=6)).isoformat()),
        ("window", None),
        ("window", "x" * 65),
        ("window", ""),
        ("window", "0s"),
        ("window", "25h"),
        ("window", "NaNs"),
    ],
)
def test_invalid_sampling_intervals_are_bounded_and_rejected(field, value):
    manifest = sample()
    manifest[field] = value
    with pytest.raises(AppError):
        sample_time(manifest, NOW)


def test_compound_sampling_window():
    assert sample_time({"timestamp": NOW.isoformat(), "window": "1h2m3.5s"}, NOW)[:2] == (
        NOW,
        D("3723.5"),
    )


@pytest.mark.parametrize(
    "containers",
    [
        None,
        [None],
        [{}],
        [{"name": "unknown", "usage": {}}],
        [{"name": "app"}, {"name": "app"}],
        [{"name": "app"}] * (MAX_CONTAINERS + 1),
    ],
)
def test_invalid_container_samples_fail_closed(containers):
    value = sample()
    value["containers"] = containers
    with pytest.raises(AppError):
        pod_sample(budget_record(), sampled(value), NOW)


def test_resource_key_and_container_bounds():
    value = budgeted()
    value["spec"]["containers"][0]["resources"]["requests"] = {
        f"vendor.example/device-{index}": "1" for index in range(MAX_RESOURCES + 1)
    }
    with pytest.raises(AppError, match="resource keys"):
        pod_budget(record(value))
    value["spec"]["containers"][0]["resources"]["requests"].pop("vendor.example/device-0")
    with pytest.raises(AppError, match="Pod resource keys"):
        pod_budget(record(value))
    members = tuple(
        MetricReport(extended=((f"example.test/{index}", ResourceAmount()),))
        for index in range(MAX_RESOURCES + 1)
    )
    with pytest.raises(AppError, match="aggregated resource keys"):
        aggregate(members)


def node_record():
    api = ApiResource("", "v1", "nodes", "Node", False, frozenset({"list", "watch"}))
    value = item("node", namespace=None)
    value["status"] = {
        "capacity": {"cpu": "4", "memory": "8Gi", "vendor.example/slice": "8"},
        "allocatable": {"cpu": "3", "memory": "6Gi", "vendor.example/slice": "6"},
    }
    return resource_record(api, value)


def test_node_usage_allocatable_requests_capacity_and_partial_membership():
    node = node_record()
    usage = sampled(name="node", namespace=None, cpu="1500m", memory="3Gi")
    report = node_sample(node, usage, (pod_budget(budget_record()),), NOW)
    assert report.cpu.usage == D("1.5") and report.cpu.request == D(".1")
    assert report.value("cpu-percent-allocatable") == ("50", D(50))
    assert report.value("memory-percent-allocatable") == ("50", D(50))
    assert report.value("cpu-capacity") == ("4000", D(4))
    assert report.value("memory-allocatable") == ("6144", D(6 * 2**30))
    assert "vendor.example/slice" in report.value("extended")[0]
    partial = node_sample(node, usage, (pod_budget(budget_record()),), NOW, complete=False)
    assert partial.value("cpu-req")[1] is None and partial.value("cpu-percent-allocatable")[1] == 50
    assert "incomplete" in partial.detail
    assert node_sample(node, None, (), NOW).status is MetricStatus.NO_SAMPLE
    assert node_sample(node, None, (), NOW).cpu.request == 0
    assert node_sample(node, replace(usage, uid="old"), (), NOW).status is MetricStatus.NO_SAMPLE
    assert (
        node_sample(replace(node, created_at=NOW + timedelta(seconds=1)), usage, (), NOW).status
        is MetricStatus.NO_SAMPLE
    )
    assert (
        node_sample(node, sampled(name="node", namespace=None, cpu="NaN"), (), NOW).status
        is MetricStatus.PARTIAL
    )
    assert (
        node_sample(
            node, sampled(name="node", namespace=None, now=NOW - timedelta(seconds=61)), (), NOW
        ).status
        is MetricStatus.STALE
    )


@pytest.mark.parametrize("name", [None, "", "x" * 254])
def test_invalid_container_names_cannot_enter_sample_maps(name):
    manifest = sample(containers=[{"name": name, "usage": {}}])
    with pytest.raises(AppError):
        pod_sample(budget_record(), sampled(manifest), NOW)


def test_resource_key_length_is_bounded():
    manifest = sample(containers=[{"name": "app", "usage": {"x" * 254: "1"}}])
    with pytest.raises(AppError, match="resource keys"):
        pod_sample(budget_record(), sampled(manifest), NOW)


@pytest.mark.parametrize(
    "window,seconds",
    [("500ms", ".5"), ("1us", ".000001"), ("1µs", ".000001"), ("1ns", ".000000001")],
)
def test_subsecond_sampling_windows(window, seconds):
    assert sample_time({"timestamp": NOW.isoformat(), "window": window}, NOW)[1] == D(seconds)


@pytest.mark.parametrize(
    "placement,key",
    [
        ("init", "vendor.example/slice"),
        ("sidecar", "other.test/device"),
        ("pod", "hugepages-2Mi"),
        ("overhead", "vendor.example/overhead"),
    ],
)
def test_extended_totals_propagate_complex_allocations_even_when_key_is_absent_from_app_containers(
    placement, key
):
    ordinary = budgeted("ordinary")
    ordinary["spec"]["containers"][0]["resources"].update(
        {"requests": {"cpu": "100m", key: "2"}, "limits": {"cpu": "1", key: "2"}}
    )
    complex_pod = budgeted("complex")
    extra = {"requests": {key: "1"}, "limits": {key: "1"}}
    if placement in {"init", "sidecar"}:
        complex_pod["spec"]["initContainers"] = [
            {
                "name": "initializer",
                "resources": extra,
                **({"restartPolicy": "Always"} if placement == "sidecar" else {}),
            }
        ]
    elif placement == "pod":
        complex_pod["spec"]["resources"] = extra
    else:
        complex_pod["spec"]["overhead"] = {key: "1"}
    normal_report, complex_report = pod_budget(record(ordinary)), pod_budget(record(complex_pod))
    assert key in dict(complex_report.extended)
    assert dict(complex_report.extended)[key].uncertain
    assert f"{key} req=N/A lim=N/A" in complex_report.value("extended")[0]
    total = aggregate((normal_report, complex_report))
    assert dict(total.extended)[key].uncertain
    assert f"{key} req=N/A lim=N/A" in total.value("extended")[0]
    assert "uncertain budget" in total.value("extended")[0]
    # An uncertain member with no declaration of this key must not be treated
    # as a proven zero reservation when another member declares it.
    unknown = budgeted("unknown")
    unknown["spec"]["initContainers"] = [{"name": "init"}]
    missing_key = aggregate((normal_report, pod_budget(record(unknown))))
    assert dict(missing_key.extended)[key].uncertain
    assert "req=N/A" in missing_key.value("extended")[0]
    node = node_record()
    node_report = node_sample(
        node, sampled(name="node", namespace=None), (normal_report, complex_report), NOW
    )
    assert dict(node_report.extended)[key].uncertain
    assert "req=N/A" in node_report.value("extended")[0]
    assert "allocation uncertain" in node_report.detail
    partial = node_sample(
        node, sampled(name="node", namespace=None), (normal_report,), NOW, complete=False
    )
    assert dict(partial.extended)[key].uncertain and "req=N/A" in partial.value("extended")[0]


def test_nullable_optional_container_lists_do_not_crash_metrics_projection():
    value = budgeted()
    value["spec"].update(initContainers=None, ephemeralContainers=None)
    value["status"]["containerStatuses"] = None
    result = pod_sample(record(value), sampled(), NOW)
    assert result.status is MetricStatus.VALID and result.cpu.usage == D(".25")


@pytest.mark.parametrize("statuses", [True, "malformed", [{}] * (MAX_CONTAINERS + 1)])
def test_observed_container_status_payloads_are_bounded(statuses):
    value = budgeted()
    value["status"]["containerStatuses"] = statuses
    with pytest.raises(AppError, match="observed container statuses"):
        pod_budget(record(value))
