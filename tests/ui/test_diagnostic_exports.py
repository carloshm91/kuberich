"""Public diagnostic captures freeze observed facts and current painted documents."""

import json
from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Static

from kuberich.domain.cluster_diagnostics import DiagnosticSeverity
from kuberich.domain.diagnostic_rows import diagnostic_rows
from kuberich.domain.exports import DiagnosticsSource, DocumentSource, TableSource, prepare_capture
from kuberich.ui.cluster_diagnostics import ClusterDiagnosticsTable
from kuberich.ui.diagnostic_evidence import DiagnosticEvidenceScreen
from tests.support.diagnostic_ui import NOW, POD, finding, snapshot
from tests.support.workspace import wait_for


class TableHost(App):
    def __init__(self, *, callbacks=True):
        super().__init__()
        self.header = "header-scope"
        self.query = "visible"
        self.table = (
            ClusterDiagnosticsTable(namespace=lambda: self.header, query=lambda: self.query)
            if callbacks
            else ClusterDiagnosticsTable()
        )

    def compose(self) -> ComposeResult:
        yield self.table

    def on_mount(self):
        self.table.setup()


class EvidenceHost(App):
    def __init__(self, *, supplied=True, unresolved=False):
        super().__init__()
        self.data = snapshot(collecting=True)
        item = self.data.findings[0]
        if unresolved:
            item = replace(item, subject=None, evidence=())
        self.valid = True
        self.header = "header-scope"
        self.snapshots = []
        self.effects = []

        async def open_object(ref):
            self.effects.append(ref)

        async def open_logs(mode):
            self.effects.append(mode)

        def retained(request):
            self.snapshots.append(request)
            return self.data

        self.detail = DiagnosticEvidenceScreen(
            self.data.request,
            item,
            sources=self.data.sources,
            current=lambda: self.valid,
            open_object=open_object,
            open_logs=open_logs,
            refresh=lambda: self.effects.append("refresh"),
            **({"snapshot": retained, "header_namespace": lambda: self.header} if supplied else {}),
        )

    def compose(self) -> ComposeResult:
        yield Static("Underlying diagnostic workspace")

    def on_mount(self):
        self.push_screen(self.detail)


def rooted(data):
    return replace(data, request=replace(data.request, scope=replace(data.request.scope, root=POD)))


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(40, 12), (120, 36)])
async def test_table_capture_keeps_full_incomplete_snapshot_separate_from_painted_filter(size):
    app = TableHost()
    visible = replace(finding("visible"), summary="visible finding")
    hidden = replace(finding("hidden"), severity=DiagnosticSeverity.INFO, summary="hidden finding")
    data = rooted(snapshot(findings=(visible, hidden), collecting=True))
    rows = tuple(row for row in diagnostic_rows(data, now=NOW) if row.key != "hidden")
    assert app.table.capture_export(NOW) == ()
    async with app.run_test(size=size) as pilot:
        assert app.table.capture_export(NOW) == ()
        await app.table.apply_rows(rows, data, lambda: True)
        app.table.move_cursor(row=app.table.get_row_index("visible"))
        await pilot.pause()
        choices = dict(app.table.capture_export(NOW + timedelta(seconds=5)))
        assert set(choices) == {"diagnostics", "screen"}
        diagnostic, screen = choices["diagnostics"], choices["screen"]
        assert diagnostic.id != screen.id
        assert diagnostic.session == screen.session == data.request.scope.session
        assert isinstance(diagnostic.capture.source, DiagnosticsSource)
        assert diagnostic.capture.source.snapshot is data
        assert isinstance(screen.capture.source, TableSource)
        assert "hidden" not in screen.capture.source.row_keys
        assert "visible" in screen.capture.source.row_keys
        assert screen.capture.source.concealed_columns == frozenset()
        assert screen.capture.presentation.query == "visible"
        assert screen.capture.presentation.viewport.selected == "visible"
        scope = diagnostic.capture.scope
        assert scope.export_at == NOW + timedelta(seconds=5) and scope.source_at == NOW
        assert scope.context == "owned" and scope.header_namespace == "header-scope"
        assert scope.collection_namespace == "team" and scope.namespace_mode == "one"
        assert (scope.api_version, scope.resource, scope.kind, scope.name, scope.uid) == (
            "v1",
            "pods",
            "Pod",
            "example",
            "pod-uid",
        )
        assert scope.resource_version is None
        payload = prepare_capture(diagnostic.capture, "diagnostics", artifact_id=uuid4()).payload
        facts = json.loads(payload)["payload"]
        assert {item["key"] for item in facts["findings"]} == {"visible", "hidden"}
        assert facts["collecting"] and facts["sources"][0]["omitted_findings"] == 3
        assert facts["sources"][1]["status"] == "forbidden"
        assert facts["findings"][0]["evidence"][1]["historical"]
        updated = replace(
            data,
            collecting=False,
            observed_at=NOW + timedelta(seconds=7),
            findings=(*data.findings, finding("later")),
        )
        await app.table.apply_rows(diagnostic_rows(updated, now=NOW), updated, lambda: True)
        assert diagnostic.current() and screen.current()
        assert diagnostic.capture.source.snapshot is data and data.collecting
        assert "later" not in screen.capture.source.row_keys
        assert (
            prepare_capture(diagnostic.capture, "diagnostics", artifact_id=uuid4()).payload
            == payload
        )
        # Ordinary viewport/paint changes do not invalidate immutable captured content.
        app.table.move_cursor(row=0)
        await pilot.pause()
        assert diagnostic.current() and screen.current()
    assert not diagnostic.current() and not screen.current()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change", ["header", "query", "sort", "descending", "display", "request", "reset"]
)
async def test_table_leases_reject_changed_scope_presentation_or_request(change):
    app = TableHost()
    data = snapshot()
    async with app.run_test() as pilot:
        await app.table.apply_rows(diagnostic_rows(data, now=NOW), data, lambda: True)
        await pilot.pause()
        choices = app.table.capture_export(NOW)
        assert all(lease.current() for _, lease in choices)
        if change == "header":
            app.header = "different"
        elif change == "query":
            app.query = "different"
        elif change == "sort":
            app.table.set_sort("source", app.table.descending)
        elif change == "descending":
            app.table.set_sort(app.table.sort_column, not app.table.descending)
        elif change == "display":
            app.table.display = False
            assert app.table.capture_export(NOW) == ()
        elif change == "request":
            newer = replace(data, request=replace(data.request, revision=2))
            await app.table.apply_rows(diagnostic_rows(newer, now=NOW), newer, lambda: True)
        else:
            app.table.reset(2)
            assert app.table.capture_export(NOW) == ()
        assert all(not lease.current() for _, lease in choices)
        assert all(lease.capture.scope.header_namespace == "header-scope" for _, lease in choices)


@pytest.mark.asyncio
async def test_table_unknown_header_all_namespace_and_mismatched_request_refuse_fabrication():
    app = TableHost(callbacks=False)
    data = snapshot()
    data = replace(
        data, request=replace(data.request, scope=replace(data.request.scope, namespace=None))
    )
    async with app.run_test():
        await app.table.apply_rows(diagnostic_rows(data, now=NOW), data, lambda: True)
        choices = app.table.capture_export(NOW)
        assert all(lease.current() for _, lease in choices)
        scope = choices[0][1].capture.scope
        assert scope.header_namespace is None and scope.collection_namespace is None
        assert scope.namespace_mode == "all"
        assert scope.api_version is scope.resource is scope.kind is scope.name is scope.uid is None
        assert choices[0][1].capture.presentation.query == ""
        app.table.request = replace(data.request, revision=2)
        assert app.table.capture_export(NOW) == ()
        app.table.request = None
        assert app.table.capture_export(NOW) == ()


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(40, 12), (120, 36)])
async def test_evidence_captures_rendered_document_and_matching_full_observation_without_effects(
    size,
):
    app = EvidenceHost()
    original = app.data
    assert app.detail.capture_export(NOW) == ()
    async with app.run_test(size=size) as pilot:
        await wait_for(lambda: app.detail.is_mounted)
        choices = dict(app.detail.capture_export(NOW + timedelta(seconds=4)))
        assert set(choices) == {"screen", "diagnostics"}
        document, diagnostic = choices["screen"], choices["diagnostics"]
        assert document.id != diagnostic.id
        assert document.session == diagnostic.session == original.request.scope.session
        assert isinstance(document.capture.source, DocumentSource)
        assert document.capture.source.page == "evidence"
        assert document.capture.source.text == app.detail.viewer.text
        assert "Collection namespace: team" in document.capture.source.text
        assert "Historical evidence" in document.capture.source.text
        assert isinstance(diagnostic.capture.source, DiagnosticsSource)
        assert diagnostic.capture.source.snapshot is original
        assert document.capture.scope.header_namespace == "header-scope"
        assert document.capture.scope.collection_namespace == "team"
        assert document.capture.scope.uid == "pod-uid"
        assert document.capture.scope.resource_version is None
        assert diagnostic.capture.scope.uid is None  # Collection has no root.
        assert document.current() and diagnostic.current() and not app.effects
        app.data = replace(original, observed_at=NOW + timedelta(seconds=10), collecting=False)
        await pilot.pause()
        assert document.current() and diagnostic.current()
        assert diagnostic.capture.source.snapshot.collecting
        assert document.capture.source.text == app.detail.viewer.text and not app.effects
        app.data = replace(app.data, request=replace(app.data.request, revision=2))
        assert not diagnostic.current()
        assert document.current()  # Existing evidence has its independent exact-current port.
        assert set(dict(app.detail.capture_export(NOW))) == {"screen"}
    assert not document.current() and not diagnostic.current()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["header", "current", "request", "finding", "stop"])
async def test_evidence_leases_reject_original_source_changes_and_invalidated_capture(change):
    app = EvidenceHost()
    async with app.run_test():
        await wait_for(lambda: app.detail.is_mounted)
        choices = app.detail.capture_export(NOW)
        if change == "header":
            app.header = "different"
        elif change == "current":
            app.valid = False
            assert app.detail.capture_export(NOW) == ()
        elif change == "request":
            app.detail.request = replace(app.detail.request, revision=2)
        elif change == "finding":
            app.detail.finding = replace(app.detail.finding, key="replacement")
        else:
            await app.detail.stop_owned()
            assert app.detail.capture_export(NOW) == ()
        assert all(not lease.current() for _, lease in choices)
        assert not app.effects


@pytest.mark.asyncio
async def test_evidence_backwards_compatible_unknown_header_and_unresolved_subject_capture():
    app = EvidenceHost(supplied=False, unresolved=True)
    async with app.run_test():
        await wait_for(lambda: app.detail.is_mounted)
        choices = dict(app.detail.capture_export(NOW))
        assert set(choices) == {"screen"} and not app.snapshots
        scope = choices["screen"].capture.scope
        assert scope.header_namespace is None and scope.collection_namespace == "team"
        assert scope.api_version is scope.resource is scope.kind is scope.name is scope.uid is None
        assert scope.source_at == NOW - timedelta(seconds=70)
        assert choices["screen"].current()
        assert "unresolved" in choices["screen"].capture.source.text
        assert not app.effects


@pytest.mark.asyncio
async def test_evidence_collection_root_provenance_and_missing_snapshots_are_explicit():
    app = EvidenceHost()
    app.data = rooted(app.data)
    app.detail.request = app.data.request
    async with app.run_test():
        await wait_for(lambda: app.detail.is_mounted)
        choices = dict(app.detail.capture_export(NOW))
        diagnostic = choices["diagnostics"]
        assert diagnostic.capture.scope.uid == "pod-uid"
        assert diagnostic.capture.scope.name == "example"
        assert diagnostic.capture.scope.resource == "pods"
        assert diagnostic.capture.scope.resource_version is None
        assert diagnostic.capture.scope.container is None
        app.data = None
        assert not diagnostic.current()
        choices = dict(app.detail.capture_export(NOW))
        assert set(choices) == {"screen"}
        assert choices["screen"].capture.scope.source_at == NOW - timedelta(seconds=10)
        assert not app.effects
