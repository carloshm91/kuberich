"""Small immutable capture builders; no reads, serialization or widget mutation."""

from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from kuberich.domain.exports import ExportCapture, ExportPresentation, ExportScope
from kuberich.domain.resources import ApiResource
from kuberich.domain.targets import ResourceTarget
from kuberich.services.exports import ExportLease

if TYPE_CHECKING:
    from kuberich.domain.exports import ExportSource
    from kuberich.ui.chrome import WorkspaceChrome


def header_namespace(chrome: "WorkspaceChrome | None") -> str | None:
    """Use the actual selected header scope, including an explicit All selection."""
    if chrome is None:
        return None
    if chrome.namespace is not None:
        return chrome.namespace()
    value = chrome.identity()[3]
    return None if value in {"All", "—"} else value


def target_scope(
    at: datetime,
    target: ResourceTarget,
    *,
    resource: ApiResource | None = None,
    resource_version: str | None = None,
    source_at: datetime | None = None,
    header: str | None = None,
) -> ExportScope:
    return ExportScope(
        export_at=at,
        source_at=source_at,
        context=target.session.context,
        header_namespace=header,
        collection_namespace=target.namespace,
        namespace_mode="one" if target.namespace is not None else "cluster",
        api_version=resource.api_version if resource else None,
        resource=target.resource,
        kind=resource.kind if resource else None,
        name=target.name,
        uid=target.uid,
        resource_version=resource_version,
        container=target.container,
    )


def captured_lease(
    scope: ExportScope,
    source: "ExportSource",
    current: Callable[[], bool],
    *,
    target: ResourceTarget | None = None,
    presentation: ExportPresentation | None = None,
    notices: tuple[str, ...] = (),
) -> ExportLease:
    return ExportLease(
        id=uuid4(),
        capture=ExportCapture(
            scope=scope, source=source, presentation=presentation, notices=notices
        ),
        current=current,
        session=target.session if target is not None else None,
    )
