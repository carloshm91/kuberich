"""Original synthetic OCI chart artifacts; no provider credentials or external bytes."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aiohttp import web

MANIFEST_MEDIA = "application/vnd.oci.image.manifest.v1+json"
CONFIG_MEDIA = "application/vnd.cncf.helm.config.v1+json"
CHART_MEDIA = "application/vnd.cncf.helm.chart.content.v1.tar+gzip"
PROVENANCE_MEDIA = "application/vnd.cncf.helm.chart.provenance.v1.prov"


def content_digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


@dataclass(frozen=True, slots=True, repr=False)
class OciArtifact:
    name: str
    version: str
    package: bytes
    config: bytes
    manifest: bytes
    provenance: bytes | None = None

    @property
    def tag(self) -> str:
        return self.version.replace("+", "_")

    @property
    def manifest_digest(self) -> str:
        return content_digest(self.manifest)

    @property
    def blobs(self) -> dict[str, bytes]:
        result = {
            content_digest(self.package): self.package,
            content_digest(self.config): self.config,
        }
        if self.provenance is not None:
            result[content_digest(self.provenance)] = self.provenance
        return result


def oci_artifact(
    name: str, version: str, package: bytes, *, provenance: bytes | None = None
) -> OciArtifact:
    config = json.dumps(
        {"apiVersion": "v2", "name": name, "version": version, "type": "application"},
        separators=(",", ":"),
    ).encode()

    def descriptor(media_type: str, data: bytes) -> dict[str, object]:
        return {"mediaType": media_type, "digest": content_digest(data), "size": len(data)}

    layers = [descriptor(CHART_MEDIA, package)]
    if provenance is not None:
        layers.append(descriptor(PROVENANCE_MEDIA, provenance))
    manifest = json.dumps(
        {
            "schemaVersion": 2,
            "mediaType": MANIFEST_MEDIA,
            "config": descriptor(CONFIG_MEDIA, config),
            "layers": layers,
        },
        separators=(",", ":"),
    ).encode()
    return OciArtifact(name, version, package, config, manifest, provenance)


def oci_handler(
    artifacts: Mapping[str, OciArtifact],
    requests: list[tuple[str, dict[str, str], str | None]] | None = None,
    *,
    namespace: str = "owned/owned-chart",
    denied_listing: bool = False,
    header_digest: bool = True,
) -> Callable[[web.Request], Awaitable[web.StreamResponse]]:
    """Serve original bytes on a task-owned listener; this is a controlled wire fixture."""
    from aiohttp import web

    observed = requests if requests is not None else []

    async def handler(request: web.Request) -> web.StreamResponse:
        observed.append((request.path, dict(request.query), request.headers.get("Authorization")))
        prefix = "/v2/" + namespace + "/"
        if not request.path.startswith(prefix):
            return web.Response(status=404)
        suffix = request.path[len(prefix) :]
        if suffix == "tags/list":
            if denied_listing:
                return web.Response(status=403)
            return web.json_response(
                {
                    "name": namespace,
                    "tags": sorted({item.tag for item in artifacts.values()} | {"latest"}),
                }
            )
        if suffix.startswith("manifests/"):
            reference = suffix[len("manifests/") :]
            artifact = next(
                (
                    item
                    for item in artifacts.values()
                    if reference in {item.tag, item.manifest_digest}
                ),
                None,
            )
            if artifact is not None:
                return web.Response(
                    body=artifact.manifest,
                    content_type=MANIFEST_MEDIA,
                    headers={"Docker-Content-Digest": artifact.manifest_digest}
                    if header_digest
                    else {},
                )
        if suffix.startswith("blobs/"):
            reference = suffix[len("blobs/") :]
            for artifact in artifacts.values():
                if reference in artifact.blobs:
                    return web.Response(
                        body=artifact.blobs[reference],
                        headers={"Docker-Content-Digest": reference} if header_digest else {},
                    )
        return web.Response(status=404)

    return handler
