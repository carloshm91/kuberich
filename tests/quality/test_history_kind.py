"""The real-provider verifier refuses drifting artifacts before cluster creation."""

import json
import re
import subprocess
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
import yaml

from kuberich.domain.connections import HttpProblem
from kuberich.domain.history import (
    HistoryPoint,
    HistorySeries,
    HistorySnapshot,
    HistoryStatus,
    MemberIdentity,
    MembershipEvidence,
)
from scripts import verify_history_kind as verifier
from scripts.owned_kind import NODE_IMAGE, SHELL_IMAGE, OwnedCluster


def test_actual_provider_images_chart_sources_and_dependency_locks_are_pinned():
    assert {pin.name for pin in verifier.CHARTS} == {
        "kube-prometheus-stack",
        "victoria-metrics-single",
    }
    for pin in verifier.CHARTS:
        assert re.fullmatch(r"[0-9a-f]{64}", pin.sha256)
        assert re.fullmatch(r"[0-9a-f]{40}", pin.source)
        assert re.fullmatch(r"sha256:[0-9a-f]{64}", pin.lock_digest)
        assert pin.url.endswith(pin.name + "-" + pin.version + ".tgz")
    assert {
        "operator",
        "reloader",
        "prometheus",
        "ksm",
        "node-exporter",
        "victoriametrics",
        "thanos",
    } == set(verifier.IMAGES)
    for image in (*verifier.IMAGES.values(), NODE_IMAGE, SHELL_IMAGE):
        assert re.fullmatch(r"[^\s]+@sha256:[0-9a-f]{64}", image)


def test_every_direct_and_operator_rendered_image_is_checked():
    documents = verifier.fixture_manifests()
    assert set(verifier.rendered_images(documents)) == {SHELL_IMAGE, verifier.IMAGES["thanos"]}
    with pytest.raises(ValueError, match="digest-pinned"):
        verifier.rendered_images(({"spec": {"image": "prometheus:latest"}},))
    with pytest.raises(ValueError, match="digest-pinned"):
        verifier.rendered_images(
            (
                {
                    "spec": {
                        "containers": [
                            {"args": ["--prometheus-config-reloader-image=unqualified:latest"]}
                        ]
                    }
                },
            )
        )


def test_minimal_stack_retains_native_collectors_and_thanos_sidecar():
    values = verifier.stack_values()
    assert not values["grafana"]["enabled"] and not values["alertmanager"]["enabled"]
    assert not values["defaultRules"]["create"]
    assert "kube-state-metrics" in values and "prometheus-node-exporter" in values
    assert values["prometheus"]["prometheusSpec"]["thanos"]["image"] == verifier.IMAGES["thanos"]
    assert values["prometheus"]["prometheusSpec"]["remoteWrite"][0]["url"].endswith("/api/v1/write")
    assert values["prometheus-node-exporter"]["image"]["digest"].startswith("sha256:")
    assert not verifier.vm_values()["server"]["persistentVolume"]["enabled"]
    assert "@sha256:" in verifier.vm_values()["server"]["image"]["tag"]


def test_query_observations_bound_series_and_preserve_actual_absence():
    assert verifier._samples({"status": "success", "data": {"result": []}}) == ()
    assert verifier._samples(
        {"status": "success", "data": {"result": [{"metric": {"container": "POD"}}]}}
    ) == ({"container": "POD"},)
    for document in (
        None,
        {"status": "error"},
        {"status": "success", "data": {"result": [None] * 129}},
    ):
        with pytest.raises(AssertionError):
            verifier._samples(document)


def test_owned_receiver_and_reset_exporter_emit_valid_bounded_http_and_only_presence_metadata():
    synthetic_request = "GET /api/v1/query_range?end=0 HTTP/1.1\r\nAuthorization: synthetic-control\r\nImpersonate-User: synthetic-control\r\n\r\n"
    captured = subprocess.run(
        ["sh", "-c", verifier.CAPTURE_RESPONDER],
        input=synthetic_request,
        text=True,
        capture_output=True,
        check=True,
        timeout=5,
    )
    assert "synthetic-control" not in captured.stderr
    assert (
        '"authorization_present":1' in captured.stderr
        and '"impersonation_count":1' in captured.stderr
    )
    with pytest.raises(AssertionError):
        verifier.assert_backend_isolation(
            ({"authorization_present": 1, "impersonation_count": 1, "query_range": 1},)
        )
    verifier.assert_backend_isolation(
        ({"authorization_present": 0, "impersonation_count": 0, "query_range": 1},)
    )
    exported = subprocess.run(
        ["sh", "-c", verifier.RESET_RESPONDER],
        input=synthetic_request,
        text=True,
        capture_output=True,
        check=True,
        timeout=5,
    )
    header, body = exported.stdout.split("\n\n", 1)
    length = int(re.search(r"Content-Length: ([0-9]+)", header)[1])
    assert len(body.encode()) == length and body.endswith("\n")
    assert "kuberich_fixture_counter_total" in body and "synthetic-reset" in body
    assert "container_cpu_usage_seconds_total" not in body


def test_native_qualification_requires_parsed_positive_values_for_both_core_families():
    empty = verifier.native_value_summary(HistorySnapshot(HistoryStatus.NO_DATA))
    assert empty["cpu"]["positive_points"] == empty["memory"]["positive_points"] == 0
    point = HistoryPoint(datetime(2026, 11, 6, tzinfo=UTC), Decimal("0.25"))
    observed = verifier.native_value_summary(
        HistorySnapshot(
            HistoryStatus.PARTIAL,
            series=(
                HistorySeries("cpu", "Native CPU", "cores", (point,)),
                HistorySeries("memory", "Native memory", "bytes", (point,)),
            ),
        )
    )
    assert observed["cpu"]["positive_points"] == observed["memory"]["positive_points"] == 1
    assert observed["cpu"]["minimum"] == "0.25"


def test_rollout_comparison_rejects_old_uid_rebind_lost_history_and_fabricated_young_values():
    now = datetime(2026, 11, 6, tzinfo=UTC)
    historical = HistorySnapshot(
        HistoryStatus.PARTIAL,
        series=(
            HistorySeries("cpu", "CPU", "cores", (HistoryPoint(now, Decimal("0.25")),)),
            HistorySeries("memory", "Memory", "bytes", (HistoryPoint(now, Decimal("1024")),)),
        ),
        membership_evidence=MembershipEvidence(),
    )
    projection = HistorySnapshot(
        HistoryStatus.NO_DATA,
        end=now + timedelta(seconds=60),
        membership_evidence=MembershipEvidence(
            "current-members",
            "current-only",
            now,
            (MemberIdentity("owned", "new", "new-uid", now),),
        ),
    )
    evidence = verifier.rollout_comparison(historical, projection, frozenset({"old-uid"}))
    assert evidence["historical_membership_status"] == "name-inferred"
    assert evidence["current_member_uids"] == ["new-uid"]
    for previous, current in (
        (replace(historical, series=()), projection),
        (historical, replace(projection, series=historical.series)),
        (historical, replace(projection, end=now + timedelta(seconds=301))),
        (
            historical,
            replace(
                projection,
                membership_evidence=replace(
                    projection.membership_evidence,
                    members=(MemberIdentity("owned", "old", "old-uid", now),),
                ),
            ),
        ),
    ):
        with pytest.raises(AssertionError):
            verifier.rollout_comparison(previous, current, frozenset({"old-uid"}))


@pytest.mark.asyncio
async def test_mixed_manifest_apply_preserves_namespaces_and_owned_destination(
    tmp_path, monkeypatch
):
    cluster = OwnedCluster(
        "owned", tmp_path / "owned-kubeconfig", tmp_path, "kind-owned", ("owned-node",)
    )
    calls = []

    def capture(argv, environment, timeout):
        calls.append((argv, environment["KUBECONFIG"]))
        return "owned result"

    monkeypatch.setattr(verifier, "run_owned", capture)
    documents = (
        {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {"name": "system", "namespace": "kube-system"},
        },
        {"apiVersion": "v1", "kind": "Pod", "metadata": {"name": "fixture"}},
        {
            "apiVersion": "rbac.authorization.k8s.io/v1",
            "kind": "ClusterRole",
            "metadata": {"name": "owned-role"},
        },
    )
    await verifier._apply(cluster, "owned-kubectl", "mixed", documents)
    argv, config = calls[0]
    assert argv[:5] == [
        "owned-kubectl",
        "--kubeconfig",
        str(cluster.path),
        "--context",
        cluster.context,
    ]
    assert "--namespace" not in argv and argv[5] == "apply"
    assert config == str(cluster.path)
    written = tuple(yaml.safe_load_all((tmp_path / "mixed.yaml").read_text()))
    assert written[0]["metadata"]["namespace"] == "kube-system"
    assert written[1]["metadata"]["namespace"] == verifier.NAMESPACE
    assert "namespace" not in written[2]["metadata"]
    assert "namespace" not in documents[1]["metadata"]
    await verifier._command(cluster, "owned-kubectl", "get", "pods")
    ordinary, _ = calls[1]
    assert ordinary[5:7] == ["--namespace", verifier.NAMESPACE]
    with pytest.raises(ValueError, match="manifest application"):
        await verifier._command(cluster, "owned-kubectl", "get", "pods", namespace=None)
    with pytest.raises(ValueError, match="owned fixture"):
        await verifier._apply(
            cluster,
            "owned-kubectl",
            "other",
            ({"kind": "Pod", "metadata": {"name": "outside", "namespace": "unselected"}},),
        )


def test_reset_scrape_contract_uses_one_explicit_named_port_and_matching_monitor_selector():
    documents = {document["kind"]: document for document in verifier.reset_manifests()}
    container = documents["Deployment"]["spec"]["template"]["spec"]["containers"][0]
    port = container["ports"][0]
    service = documents["Service"]
    monitor = documents["ServiceMonitor"]
    assert port == {"name": "metrics", "containerPort": 9101}
    assert service["spec"]["ports"][0]["targetPort"] == port["name"]
    assert monitor["spec"]["endpoints"][0] == {
        "port": port["name"],
        "path": "/metrics",
        "interval": "2s",
        "scrapeTimeout": "1s",
    }
    assert container["readinessProbe"]["httpGet"] == {"path": "/metrics", "port": port["name"]}
    assert monitor["spec"]["selector"]["matchLabels"] == service["metadata"]["labels"]
    assert monitor["spec"]["namespaceSelector"]["matchNames"] == [verifier.NAMESPACE]
    selector = verifier.stack_values()["prometheus"]["prometheusSpec"]["serviceMonitorSelector"][
        "matchLabels"
    ]
    assert all(monitor["metadata"]["labels"].get(key) == value for key, value in selector.items())


def test_reset_queries_retain_only_finite_numeric_values_for_the_synthetic_fixture():
    def document(value="2", fixture="synthetic-reset"):
        return {
            "status": "success",
            "data": {
                "resultType": "vector",
                "result": [{"metric": {"fixture": fixture}, "value": [0, value]}],
            },
        }

    assert (
        verifier.reset_numbers(
            {"status": "success", "data": {"resultType": "vector", "result": []}}
        )
        == ()
    )
    assert verifier.reset_numbers(document()) == ("2",)
    for value in ("NaN", "Inf", "-1", "9" * 65, "malformed", "1e21"):
        with pytest.raises(AssertionError):
            verifier.reset_numbers(document(value))
    with pytest.raises(AssertionError, match="another fixture"):
        verifier.reset_numbers(document(fixture="unrelated"))
    assert verifier.scrape_error_kind("connection refused") == "connection-refused"
    assert (
        verifier.scrape_error_kind("text format parsing error: private-response")
        == "exposition-format"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["prometheus", "victoriametrics", "thanos"])
async def test_reset_failure_retains_provider_queries_and_calls_bounded_diagnostics(
    tmp_path, monkeypatch, provider
):
    stages = []

    class EmptyTransport:
        async def get_json(self, suffix, params, *, max_bytes):
            assert suffix == "query" and max_bytes == 1024 * 1024
            if provider == "thanos":
                assert params["partial_response"] == "false" and params["dedup"] == "true"
            result_type = "matrix" if "time" in params else "vector"
            return {"status": "success", "data": {"resultType": result_type, "result": []}}

    async def diagnostics(client, cluster, kubectl, directory, observed_provider, stage):
        stages.append((observed_provider, stage))

    async def original_deadline(operation, *, timeout):
        assert timeout == 180
        assert not await operation()
        raise TimeoutError

    monkeypatch.setattr(verifier, "reset_diagnostics", diagnostics)
    monkeypatch.setattr(verifier, "until", original_deadline)
    with pytest.raises(TimeoutError):
        await verifier.verify_reset(
            EmptyTransport(), provider, None, None, "owned-kubectl", tmp_path
        )
    assert stages == [(provider, "before"), (provider, "failure")]
    records = [
        json.loads(line)
        for line in (tmp_path / "reset-query-observations.jsonl").read_text().splitlines()
    ]
    assert len(records) == 4 and all(record["provider"] == provider for record in records)
    queries = {key: value for record in records for key, value in record["queries"].items()}
    assert set(queries) == {"counter", "gauge", "resets", "raw"}
    assert all(queries[key]["values"] == [] for key in ("counter", "gauge", "resets"))
    assert all(query["result_count"] == 0 for query in queries.values())
    assert queries["raw"]["adjacent_decreases"] == queries["raw"]["sample_count"] == 0


def raw_reset_document(query_time, values=("18", "0")):
    return {
        "status": "success",
        "data": {
            "resultType": "matrix",
            "result": [
                {
                    "metric": {
                        "__name__": "kuberich_fixture_counter_total",
                        "fixture": "synthetic-reset",
                        "instance": "owned-reset:9101",
                    },
                    "values": [
                        [query_time - 4 + index * 2, value] for index, value in enumerate(values)
                    ],
                }
            ],
        },
    }


def test_raw_reset_proof_uses_adjacent_samples_from_each_series_in_the_api_time_window():
    query_time = datetime(2026, 11, 6, tzinfo=UTC).timestamp()
    document = raw_reset_document(query_time)
    observation = verifier.raw_reset_observation(document, query_time=query_time)
    assert observation.adjacent_decreases == 1
    assert observation.result_count == 1 and observation.sample_count == 2
    assert observation.query_timestamp == query_time
    assert observation.series[0].samples == ((query_time - 4, "18"), (query_time - 2, "0"))
    assert len(observation.series[0].identity_sha256) == 64
    # Two individually monotonic series cannot manufacture a drop at their boundary.
    document = raw_reset_document(query_time, ("17", "18"))
    other = deepcopy(document["data"]["result"][0])
    other["metric"]["instance"] = "owned-reset-other:9101"
    other["values"] = [[query_time - 4, "0"], [query_time - 2, "1"]]
    document["data"]["result"].append(other)
    assert verifier.raw_reset_observation(document, query_time=query_time).adjacent_decreases == 0
    document = raw_reset_document(query_time)
    document["data"]["result"][0]["values"] = [[query_time - 59.999, "18"], [query_time, "0"]]
    assert verifier.raw_reset_observation(document, query_time=query_time).adjacent_decreases == 1


def test_raw_reset_proof_bounds_all_series_and_does_not_invent_startup_resets():
    query_time = datetime(2026, 11, 6, tzinfo=UTC).timestamp()
    one_sample = raw_reset_document(query_time, ("0",))
    assert verifier.raw_reset_observation(one_sample, query_time=query_time).adjacent_decreases == 0
    document = raw_reset_document(query_time)
    template = document["data"]["result"][0]
    template["values"] = [[query_time - 31.5 + index / 2, "1"] for index in range(64)]
    document["data"]["result"] = []
    for index in range(8):
        series = deepcopy(template)
        series["metric"]["instance"] = f"owned-{index}:9101"
        document["data"]["result"].append(series)
    observation = verifier.raw_reset_observation(document, query_time=query_time)
    assert observation.sample_count == 512 and observation.result_count == 8
    assert observation.adjacent_decreases == 0
    for invalid_time in (float("nan"), float("inf")):
        with pytest.raises(AssertionError, match="query time"):
            verifier.raw_reset_observation(document, query_time=invalid_time)


@pytest.mark.parametrize(
    "case",
    [
        "wrong-type",
        "missing-data",
        "wrong-fixture",
        "wrong-metric",
        "bad-label",
        "duplicate-series",
        "too-many-series",
        "empty-samples",
        "too-many-samples",
        "malformed-pair",
        "string-timestamp",
        "bool-timestamp",
        "nan-timestamp",
        "infinite-timestamp",
        "duplicate-time",
        "reverse-time",
        "left-boundary",
        "future",
        "stale",
        "negative",
        "nan",
        "infinite",
        "malformed-value",
        "whitespace-value",
        "underscore-value",
        "large-value",
        "long-value",
    ],
)
def test_raw_reset_proof_rejects_invalid_identity_protocol_values_times_and_bounds(case):
    query_time = datetime(2026, 11, 6, tzinfo=UTC).timestamp()
    document = raw_reset_document(query_time)
    results = document["data"]["result"]
    metric, samples = results[0]["metric"], results[0]["values"]
    if case == "wrong-type":
        document["data"]["resultType"] = "vector"
    elif case == "missing-data":
        document["data"] = None
    elif case == "wrong-fixture":
        metric["fixture"] = "unrelated"
    elif case == "wrong-metric":
        metric["__name__"] = "kuberich_fixture_gauge"
    elif case == "bad-label":
        metric["instance"] = "owned\nprivate"
    elif case == "duplicate-series":
        results.append(deepcopy(results[0]))
    elif case == "too-many-series":
        results.extend(deepcopy(results[0]) for _ in range(8))
    elif case == "empty-samples":
        samples.clear()
    elif case == "too-many-samples":
        samples[:] = [[query_time - 59 + index / 2, "1"] for index in range(65)]
    elif case == "malformed-pair":
        samples[0] = [query_time - 4]
    elif case in {"string-timestamp", "bool-timestamp", "nan-timestamp", "infinite-timestamp"}:
        samples[0][0] = {
            "string-timestamp": str(query_time - 4),
            "bool-timestamp": True,
            "nan-timestamp": float("nan"),
            "infinite-timestamp": float("inf"),
        }[case]
    elif case == "duplicate-time":
        samples[1][0] = samples[0][0]
    elif case == "reverse-time":
        samples.reverse()
    elif case == "left-boundary":
        samples[0][0] = query_time - 60
    elif case == "future":
        samples[1][0] = query_time + 0.001
    elif case == "stale":
        samples[:] = [[query_time - 34, "18"], [query_time - 32, "0"]]
    else:
        samples[1][1] = {
            "negative": "-1",
            "nan": "NaN",
            "infinite": "Inf",
            "malformed-value": "invalid",
            "whitespace-value": " 1",
            "underscore-value": "1_0",
            "large-value": "1e21",
            "long-value": "9" * 65,
        }[case]
    with pytest.raises(AssertionError):
        verifier.raw_reset_observation(document, query_time=query_time)


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["prometheus", "victoriametrics", "thanos"])
@pytest.mark.parametrize("actual_drop", [True, False])
async def test_reset_readiness_requires_raw_drop_before_unchanged_positive_provider_rate(
    tmp_path, monkeypatch, provider, actual_drop
):
    stages, queries = [], []

    class Transport:
        async def get_json(self, suffix, params, *, max_bytes):
            assert suffix == "query" and max_bytes == 1024 * 1024 and params["timeout"] == "8s"
            queries.append(dict(params))
            if provider == "thanos":
                assert {
                    key: params[key]
                    for key in ("dedup", "partial_response", "max_source_resolution")
                } == {"dedup": "true", "partial_response": "false", "max_source_resolution": "0s"}
            expression = params["query"]
            if "time" in params:
                assert expression == 'kuberich_fixture_counter_total{fixture="synthetic-reset"}[1m]'
                return raw_reset_document(
                    float(params["time"]), ("18", "0" if actual_drop else "19")
                )
            if expression.startswith("resets("):
                value = "0" if provider == "thanos" and actual_drop else "1"
            elif expression.startswith("rate"):
                expected = "rate_prometheus" if provider == "victoriametrics" else "rate"
                assert (
                    expression
                    == f'{expected}(kuberich_fixture_counter_total{{fixture="synthetic-reset"}}[1m])'
                )
                value = "0.9"
            else:
                value = "42" if "gauge" in expression else "2"
            return {
                "status": "success",
                "data": {
                    "resultType": "vector",
                    "result": [{"metric": {"fixture": "synthetic-reset"}, "value": [0, value]}],
                },
            }

    async def diagnostics(client, cluster, kubectl, directory, observed_provider, stage):
        stages.append(stage)

    async def original_deadline(operation, *, timeout):
        assert timeout == 180
        ready = await operation()
        assert ready == actual_drop
        if not ready:
            raise TimeoutError

    monkeypatch.setattr(verifier, "reset_diagnostics", diagnostics)
    monkeypatch.setattr(verifier, "until", original_deadline)
    if actual_drop:
        result = await verifier.verify_reset(Transport(), provider, None, None, "owned", tmp_path)
        assert result["actual_reset_observed"] is True
        assert result["raw_reset_observation"]["adjacent_decreases"] == 1
        assert result["observed_rates"] == ("0.9",)
        assert result["resets_function_role"] == (
            "diagnostic" if provider == "thanos" else "required"
        )
        assert stages == ["before", "ready"] and len(queries) == 5
    else:
        with pytest.raises(TimeoutError):
            await verifier.verify_reset(Transport(), provider, None, None, "owned", tmp_path)
        assert stages == ["before", "failure"] and len(queries) == 4
        assert all(not params["query"].startswith("rate") for params in queries)
    records = [
        json.loads(line)
        for line in (tmp_path / "reset-query-observations.jsonl").read_text().splitlines()
    ]
    raw = next(record["queries"]["raw"] for record in records if "raw" in record["queries"])
    assert raw["adjacent_decreases"] == int(actual_drop)
    assert raw["query_timestamp"] == float(
        next(params["time"] for params in queries if "time" in params)
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [
        "resets-http",
        "raw-http",
        "raw-malformed",
        "missing-gauge",
        "rate-empty",
        "rate-zero",
        "rate-large",
        "rate-nan",
        "rate-negative",
    ],
)
async def test_thanos_diagnostic_reset_zero_cannot_bypass_transport_raw_gauge_or_rate_failure(
    tmp_path, monkeypatch, failure
):
    stages = []

    class Transport:
        async def get_json(self, suffix, params, *, max_bytes):
            expression = params["query"]
            if failure == "resets-http" and expression.startswith("resets("):
                raise HttpProblem(503)
            if "time" in params:
                if failure == "raw-http":
                    raise HttpProblem(503)
                document = raw_reset_document(float(params["time"]))
                if failure == "raw-malformed":
                    document["data"]["result"][0]["values"][1][1] = "invalid"
                return document
            value = "0" if expression.startswith("resets(") else "42"
            result = [{"metric": {"fixture": "synthetic-reset"}, "value": [0, value]}]
            if failure == "missing-gauge" and "gauge" in expression:
                result = []
            if expression.startswith("rate("):
                value = {
                    "rate-zero": "0",
                    "rate-large": "10",
                    "rate-nan": "NaN",
                    "rate-negative": "-1",
                }.get(failure, "0.9")
                result[0]["value"][1] = value
                if failure == "rate-empty":
                    result = []
            return {"status": "success", "data": {"resultType": "vector", "result": result}}

    async def diagnostics(client, cluster, kubectl, directory, observed_provider, stage):
        stages.append(stage)

    async def original_deadline(operation, *, timeout):
        assert timeout == 180
        if not await operation():
            raise TimeoutError

    monkeypatch.setattr(verifier, "reset_diagnostics", diagnostics)
    monkeypatch.setattr(verifier, "until", original_deadline)
    expected = (
        HttpProblem
        if failure.endswith("http")
        else TimeoutError
        if failure in {"missing-gauge", "rate-empty", "rate-zero"}
        else AssertionError
    )
    with pytest.raises(expected):
        await verifier.verify_reset(Transport(), "thanos", None, None, "owned", tmp_path)
    assert stages == ["before", "failure"]
    records = [
        json.loads(line)
        for line in (tmp_path / "reset-query-observations.jsonl").read_text().splitlines()
    ]
    errors = [
        entry for record in records for entry in record["queries"].values() if "error_type" in entry
    ]
    if failure.endswith("http"):
        assert len(errors) == 1 and errors[0]["http_status"] == 503
    elif failure in {"raw-malformed", "rate-nan", "rate-negative"}:
        assert len(errors) == 1 and errors[0]["error_type"] == "AssertionError"


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["prometheus", "victoriametrics", "thanos"])
@pytest.mark.parametrize(
    "case", ["zero-to-positive", "empty-to-positive", "lost-raw-witness", "reset-function-zero"]
)
async def test_reset_retries_share_original_deadline_and_require_fresh_raw_and_provider_evidence(
    tmp_path, monkeypatch, provider, case
):
    raw_calls, rate_calls = [], []
    stages = []
    succeeds = case in {"zero-to-positive", "empty-to-positive"} or (
        case == "reset-function-zero" and provider == "thanos"
    )

    class Transport:
        async def get_json(self, suffix, params, *, max_bytes):
            expression = params["query"]
            if "time" in params:
                raw_calls.append(dict(params))
                drops = case != "lost-raw-witness" or len(raw_calls) == 1
                return raw_reset_document(float(params["time"]), ("18", "0" if drops else "19"))
            value = "42"
            if expression.startswith("resets("):
                value = "0" if case == "reset-function-zero" or provider == "thanos" else "1"
            elif expression.startswith("rate"):
                rate_calls.append(dict(params))
                value = "0" if len(rate_calls) == 1 and case != "reset-function-zero" else "0.5"
            results = [{"metric": {"fixture": "synthetic-reset"}, "value": [0, value]}]
            if (
                expression.startswith("rate")
                and case == "empty-to-positive"
                and len(rate_calls) == 1
            ):
                results = []
            return {"status": "success", "data": {"resultType": "vector", "result": results}}

    async def diagnostics(client, cluster, kubectl, directory, observed_provider, stage):
        stages.append(stage)

    async def original_deadline(operation, *, timeout):
        assert timeout == 180
        for _ in range(2):
            if await operation():
                return
        raise TimeoutError

    monkeypatch.setattr(verifier, "reset_diagnostics", diagnostics)
    monkeypatch.setattr(verifier, "until", original_deadline)
    if succeeds:
        result = await verifier.verify_reset(Transport(), provider, None, None, "owned", tmp_path)
        assert result["observed_rates"] == ("0.5",)
        assert result["raw_reset_observation"]["query_timestamp"] == float(raw_calls[-1]["time"])
        assert stages == ["before", "ready"]
    else:
        with pytest.raises(TimeoutError):
            await verifier.verify_reset(Transport(), provider, None, None, "owned", tmp_path)
        assert stages == ["before", "failure"]
    if case in {"zero-to-positive", "empty-to-positive"}:
        assert len(raw_calls) == len(rate_calls) == 2
    elif case == "lost-raw-witness":
        assert len(raw_calls) == 2 and len(rate_calls) == 1
    elif provider != "thanos":
        assert len(raw_calls) == 2 and not rate_calls
    else:
        assert len(raw_calls) == len(rate_calls) == 1


@pytest.mark.asyncio
async def test_reset_diagnostics_keep_only_source_job_health_and_bounded_source_state(
    tmp_path, monkeypatch
):
    class Client:
        async def get_json(self, path, **kwargs):
            if path.endswith("/targets"):
                return {
                    "data": {
                        "activeTargets": [
                            {
                                "labels": {"service": "owned-reset"},
                                "health": "down",
                                "lastError": "connection refused synthetic-sensitive-detail",
                            },
                            {
                                "labels": {"service": "unrelated"},
                                "health": "down",
                                "lastError": "unrelated-private",
                            },
                        ]
                    }
                }
            if path.endswith("/pods"):
                return {
                    "items": [
                        {
                            "metadata": {"name": "owned-reset-pod"},
                            "status": {
                                "phase": "Pending",
                                "conditions": [
                                    {
                                        "type": "Ready",
                                        "status": "False",
                                        "reason": "ContainersNotReady",
                                    }
                                ],
                                "containerStatuses": [
                                    {
                                        "name": "exporter",
                                        "ready": False,
                                        "restartCount": 3,
                                        "state": {
                                            "waiting": {
                                                "reason": "CrashLoopBackOff",
                                                "message": "private-runtime-message",
                                            }
                                        },
                                    }
                                ],
                            },
                        }
                    ]
                }
            return {"metadata": {}, "spec": {}}

    async def command(cluster, kubectl, *arguments, **kwargs):
        if arguments[0] == "logs":
            assert "--tail=20" in arguments and "--limit-bytes=4096" in arguments
            return "owned exporter startup\n"
        return 'kuberich_fixture_counter_total{fixture="synthetic-reset"} 7\n'

    monkeypatch.setattr(verifier, "_command", command)
    await verifier.reset_diagnostics(
        Client(), None, "owned-kubectl", tmp_path, "victoriametrics", "failure"
    )
    text = (tmp_path / "victoriametrics-reset-failure.json").read_text()
    observed = json.loads(text)
    assert len(observed["scrape_targets"]) == 1
    assert observed["scrape_targets"][0]["last_error_kind"] == "connection-refused"
    assert observed["source_pods"][0]["containers"][0]["restart_count"] == 3
    assert observed["source_log"] == "owned exporter startup\n"
    assert not any(
        marker in text
        for marker in ("synthetic-sensitive-detail", "unrelated-private", "private-runtime-message")
    )
