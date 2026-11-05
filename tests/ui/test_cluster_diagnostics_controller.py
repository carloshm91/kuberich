"""Actual projection/filter/apply keeps source limitations visible under local queries."""

from dataclasses import replace

import pytest

from kuberich.domain.view_routes import ViewRoute
from kuberich.domain.views import ViewObservation
from kuberich.ui.controllers.base import RenderRequest, ViewDriver
from kuberich.ui.controllers.cluster_diagnostics import ClusterDiagnosticsController
from tests.support.diagnostic_ui import NOW, snapshot
from tests.ui.test_cluster_diagnostics_table import Host


@pytest.mark.asyncio
async def test_real_driver_retains_source_limits_and_age_when_no_finding_matches():
    app = Host()
    data = snapshot()
    request = RenderRequest(
        ViewObservation(diagnostics=data),
        "no-such-finding",
        lambda: True,
        ViewRoute.diagnostics(),
        expected_uid="not-a-resource-filter",
    )
    driver = ViewDriver(
        ClusterDiagnosticsController(
            app.table, lambda _: frozenset({"diagnostic_evidence"}), now=lambda: NOW
        )
    )
    async with app.run_test() as pilot:
        outcome = await driver.render(request)
        assert outcome.applied and outcome.count == 4 and outcome.filtered == 3
        assert all(
            app.table.row_at(item.key.value).finding is None for item in app.table.ordered_rows
        )
        assert app.table.get_cell("source:pods", "AGE").plain == "70s (stale)"
        assert "omitted findings: 3" in app.table.get_cell("source:pods", "SUMMARY").plain
        assert driver.available_actions(request) == frozenset({"diagnostic_evidence"})
        before = driver.capture_viewport()
        assert not (await driver.render(replace(request, current=lambda: False))).applied
        driver.restore_viewport(before)
        await pilot.pause()
        assert driver.capture_viewport() == before
        matched = await driver.render(replace(request, query="restart backoff"))
        assert matched.applied and app.table.row_at("finding") is not None
        invalid = await driver.render(replace(request, query="re:["))
        assert invalid.problem is not None and invalid.applied
