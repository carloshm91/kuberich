"""Helm observations retain safe metadata and bind reviews to storage identity."""

from dataclasses import FrozenInstanceError, replace
from uuid import UUID

import pytest

from kuberich.domain.helm import (
    MAX_HELM_RENDER_BYTES,
    HelmApproval,
    HelmDisclosureIntent,
    HelmDocument,
    HelmDocumentKind,
    HelmDriver,
    HelmHistory,
    HelmHook,
    HelmInspection,
    HelmList,
    HelmOutcome,
    HelmProblem,
    HelmRelease,
    HelmReleaseKey,
    HelmRequest,
    HelmRevision,
    HelmRollbackIntent,
    HelmRollbackOptions,
    HelmRollbackResult,
    HelmScope,
    HelmSettings,
    HelmSnapshot,
    HelmStatus,
    HelmStorageIdentity,
    HelmTarget,
    HelmVersion,
    helm_cell,
    helm_positive,
    helm_timestamp,
)
from kuberich.domain.processes import ProcessPurpose
from kuberich.domain.targets import SessionIdentity
from kuberich.errors import AppError
from kuberich.services.access import Action

KEY = HelmReleaseKey("team", "demo")
REQUEST = HelmRequest(HelmScope(SessionIdentity("owned", 1), "team", HelmDriver.SECRET), 2)
HEAD = HelmStorageIdentity(
    KEY, HelmDriver.SECRET, 3, "sh.helm.release.v1.demo.v3", "uid-3", "opaque/3", "deployed"
)
TARGET = HelmTarget(REQUEST, HEAD)
PRIOR = HelmStorageIdentity(
    KEY, HelmDriver.SECRET, 1, "sh.helm.release.v1.demo.v1", "uid-1", "opaque/1", "superseded"
)
RELEASE = HelmRelease(KEY, 3, "deployed", "tiny-1.0", "1.0", "")
REVISION = HelmRevision(1, "superseded", "tiny-1.0", "1.0", None, True, None)
HISTORY = HelmHistory((REVISION,), True)
HOOK = HelmHook("demo-hook", "Job", ("pre-rollback",))
STATUS = HelmStatus(KEY, 3, "deployed", None, "2026-11-09T12:00:00Z", True, False, (HOOK,))


def intent(**kwargs):
    return HelmRollbackIntent(
        UUID(int=1), TARGET, PRIOR, kwargs.get("options", HelmRollbackOptions()), (HOOK,)
    )


def test_records_are_immutable_and_keep_full_stable_identity():
    inspected = HelmInspection(TARGET, RELEASE, STATUS, HISTORY)
    assert inspected.target.head.resource_version == "opaque/3"
    assert inspected.release.key == KEY
    assert HelmList((RELEASE,), True).releases == (RELEASE,)
    assert HelmSnapshot(REQUEST, None, True, None).collecting
    assert (
        HelmSnapshot(
            REQUEST, HelmList((), True), False, HelmProblem("forbidden", "Storage denied.")
        ).problem.kind
        == "forbidden"
    )
    with pytest.raises(FrozenInstanceError):
        inspected.release.revision = 4
    assert HelmSettings().driver is HelmDriver.SECRET
    assert HelmSettings("/opt/Helm tools/helm").executable == "/opt/Helm tools/helm"
    assert HelmVersion("v3.22.1", 3).major == 3
    assert HelmVersion("v4.3.1", 4).major == 4
    assert HelmScope(REQUEST.scope.session, None, HelmDriver.CONFIGMAP).namespace is None
    assert ProcessPurpose.HELM_READ.action is Action.READ
    assert ProcessPurpose.HELM_MUTATE.action is Action.MUTATE


def test_disclosure_and_approval_repr_do_not_include_revealed_payload_or_tokens():
    document = HelmDocument(TARGET, 1, HelmDocumentKind.VALUES, "SYNTHETIC_SECRET\n", True)
    approval = HelmApproval(UUID(int=4), UUID(int=5))
    assert "SYNTHETIC_SECRET" not in repr(document)
    assert str(approval.token) not in repr(approval)
    assert (
        HelmDisclosureIntent(UUID(int=1), TARGET, PRIOR, HelmDocumentKind.MANIFEST).selected
        == PRIOR
    )
    assert HelmDisclosureIntent(UUID(int=2), TARGET, HEAD, HelmDocumentKind.NOTES).selected == HEAD
    assert HelmRollbackResult(
        HelmOutcome.UNKNOWN, "Connection lost; effects may have started.", None, True
    ).may_have_started
    assert (
        HelmRollbackResult(HelmOutcome.SUCCEEDED, "Helm reported success.", RELEASE, True).observed
        == RELEASE
    )


def test_review_defaults_and_effects_are_explicit_and_application_authored():
    review = intent()
    assert review.options == HelmRollbackOptions(False, True, 300)
    assert "Rollback hooks are disabled." in review.effects
    assert "Wait for resources and Jobs." in review.effects
    assert any("not atomic" in value for value in review.effects)
    changed = intent(options=HelmRollbackOptions(True, False, 1))
    assert "Rollback hooks will run." in changed.effects
    assert "Do not wait for ordinary resource readiness." in changed.effects
    assert (
        "Per-operation timeout: 1 seconds; whole-command deadline is separate." in changed.effects
    )
    assert HelmRollbackOptions(timeout_seconds=600).timeout_seconds == 600


@pytest.mark.parametrize("value", [False, 0, -1, 2_147_483_648, 1.0, "1"])
def test_revisions_reject_bool_zero_negative_overflow_and_coercion(value):
    with pytest.raises(HelmProblem):
        helm_positive(value)


@pytest.mark.parametrize("value", [None, "", "x" * 4097, "a\x1bb", "a\n", "a\ud800"])
def test_metadata_cells_reject_unsafe_or_unbounded_values(value):
    with pytest.raises(AppError):
        helm_cell(value)


def test_literal_and_timestamp_validation_preserves_opaque_identity():
    assert helm_positive(1) == 1
    assert helm_cell("", empty=True) == ""
    assert helm_cell("opaque/4") == "opaque/4"
    assert helm_timestamp(None) is None
    assert helm_timestamp("2026-11-09T07:00:00-05:00") == "2026-11-09T07:00:00-05:00"


@pytest.mark.parametrize("value", ["2026-11-09", "2026-11-09T12:00:00", "not-a-date"])
def test_timestamp_requires_parseable_timezone_aware_time(value):
    with pytest.raises(HelmProblem):
        helm_timestamp(value)


@pytest.mark.parametrize(
    "change",
    [
        lambda: HelmProblem("unknown", "Safe"),
        lambda: HelmSettings("-helm"),
        lambda: HelmSettings("helm --debug"),
        lambda: HelmSettings(driver="secret"),
        lambda: HelmVersion("v3.22.0", 3),
        lambda: HelmVersion([], 3),
        lambda: HelmVersion("v3.22.1", True),
        lambda: HelmVersion("v3.22.1", 4),
        lambda: HelmScope(None, "team", HelmDriver.SECRET),
        lambda: HelmScope(REQUEST.scope.session, "Team", HelmDriver.SECRET),
        lambda: HelmRequest(REQUEST.scope, -1),
        lambda: HelmRequest(REQUEST.scope, False),
        lambda: HelmRequest(None, 1),
        lambda: HelmReleaseKey("team", "-demo"),
        lambda: HelmReleaseKey("", "demo"),
        lambda: HelmReleaseKey("team", "x" * 54),
        lambda: HelmReleaseKey("x" * 64, "demo"),
        lambda: HelmReleaseKey("team", 3),
        lambda: replace(RELEASE, key=None),
        lambda: replace(RELEASE, status="invalid state"),
        lambda: replace(RELEASE, status=False),
        lambda: HelmList((RELEASE, RELEASE), True),
        lambda: HelmList((RELEASE,) * 501, True),
        lambda: HelmList([], True),
        lambda: HelmList((None,), True),
        lambda: HelmList((), 1),
        lambda: replace(HEAD, storage_name="sh.helm.release.v1.demo.v2"),
        lambda: replace(HEAD, uid=""),
        lambda: HelmTarget(REQUEST, replace(HEAD, driver=HelmDriver.CONFIGMAP)),
        lambda: HelmTarget(REQUEST, replace(HEAD, key=HelmReleaseKey("other", "demo"))),
        lambda: replace(REVISION, updated=""),
        lambda: replace(REVISION, rollback_revision=0),
        lambda: replace(REVISION, description_present=1),
        lambda: HelmHistory((REVISION, REVISION), True),
        lambda: HelmHistory((REVISION,) * 201, True),
        lambda: HelmHook("hook", "Job", []),
        lambda: HelmHook("hook", "Job", ("pre-rollback",) * 33),
        lambda: HelmHook("hook", "Job", ("x" * 65,)),
        lambda: replace(STATUS, notes_present=1),
        lambda: HelmInspection(TARGET, replace(RELEASE, revision=2), STATUS, HISTORY),
        lambda: HelmInspection(TARGET, RELEASE, replace(STATUS, status="failed"), HISTORY),
        lambda: HelmDocument(TARGET, 1, "values", "", False),
        lambda: HelmDocument(TARGET, 1, HelmDocumentKind.VALUES, "x\x1b", True),
        lambda: HelmDocument(
            TARGET, 1, HelmDocumentKind.VALUES, "x" * (MAX_HELM_RENDER_BYTES + 1), False
        ),
        lambda: HelmRollbackOptions(run_hooks=1),
        lambda: HelmRollbackOptions(wait=1),
        lambda: HelmRollbackOptions(timeout_seconds=0),
        lambda: HelmRollbackOptions(timeout_seconds=601),
        lambda: HelmRollbackOptions(timeout_seconds=True),
        lambda: HelmDisclosureIntent("id", TARGET, PRIOR, HelmDocumentKind.NOTES),
        lambda: HelmDisclosureIntent(
            UUID(int=1), TARGET, replace(PRIOR, driver=HelmDriver.CONFIGMAP), HelmDocumentKind.NOTES
        ),
        lambda: HelmDisclosureIntent(
            UUID(int=1),
            TARGET,
            replace(HEAD, revision=4, storage_name="sh.helm.release.v1.demo.v4"),
            HelmDocumentKind.NOTES,
        ),
        lambda: HelmRollbackIntent(UUID(int=1), TARGET, HEAD, HelmRollbackOptions(), ()),
        lambda: HelmRollbackIntent(
            UUID(int=1),
            HelmTarget(REQUEST, replace(HEAD, status="pending-upgrade")),
            PRIOR,
            HelmRollbackOptions(),
            (),
        ),
        lambda: HelmRollbackIntent(
            UUID(int=1), TARGET, replace(PRIOR, status="failed"), HelmRollbackOptions(), ()
        ),
        lambda: HelmApproval(UUID(int=1), "token"),
        lambda: HelmRollbackResult("unknown", "Safe", None, False),
        lambda: HelmRollbackResult(HelmOutcome.FAILED, "Safe", None, 1),
        lambda: HelmSnapshot(REQUEST, None, False, "raw error"),
    ],
)
def test_invalid_records_cannot_carry_authority(change):
    with pytest.raises(AppError):
        change()


def test_remaining_valid_optional_fields_are_retained():
    assert (
        replace(REVISION, updated="2026-11-09T12:00:00Z", rollback_revision=1).rollback_revision
        == 1
    )
    all_scope = replace(REQUEST.scope, namespace=None)
    target = HelmTarget(replace(REQUEST, scope=all_scope), HEAD)
    assert target.head.key.namespace == "team"
