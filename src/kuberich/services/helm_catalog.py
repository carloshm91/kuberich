"""Application-owned Helm repositories and frozen chart packages, independent of Kubernetes."""

import asyncio
import hashlib
import re
import threading
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, replace
from functools import partial
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urljoin, urlsplit, urlunsplit

from platformdirs import user_state_path

from kuberich.adapters.helm_catalog_files import CatalogFiles, CatalogReceipt
from kuberich.adapters.helm_catalog_http import CatalogBody, CatalogHttp
from kuberich.domain.helm_archive import inspect_chart_package
from kuberich.domain.helm_catalog import (
    MAX_CATALOG_ENTRIES,
    MAX_CATALOG_PAGES,
    MAX_CHART_BYTES,
    MAX_INDEX_BYTES,
    MAX_VALUES_BYTES,
    CatalogSnapshot,
    ChartSnapshot,
    ChartVersion,
    HelmRepository,
    HelmRepositoryKind,
    RepositoryCredentials,
    catalog_url,
    chart_version,
    chart_version_key,
    digest,
    oci_chart_version,
    oci_digest,
    oci_tag,
    url_origin,
)
from kuberich.domain.helm_cli import helm_json
from kuberich.errors import AppError
from kuberich.services.access import AccessPolicy, Action
from kuberich.services.ownership import finish_owned
from kuberich.services.resources import parse_owned


def _index(repository: HelmRepository, data: bytes) -> tuple[ChartVersion, ...]:
    from kuberich.domain.editing import parse_manifest_documents

    try:
        values = parse_manifest_documents(data, max_bytes=MAX_INDEX_BYTES, max_documents=1)
        if len(values) != 1 or values[0].get("apiVersion") != "v1":
            raise ValueError
        entries = values[0].get("entries")
        if not isinstance(entries, dict):
            raise ValueError
        result: list[ChartVersion] = []
        for name, versions in entries.items():
            if not isinstance(versions, list):
                raise ValueError
            for value in versions:
                if not isinstance(value, dict) or value.get("name") != name:
                    raise ValueError
                urls = value.get("urls")
                if not isinstance(urls, list) or not 1 <= len(urls) <= 16:
                    raise ValueError
                checked = []
                for url in urls:
                    if not isinstance(url, str):
                        raise ValueError
                    resolved = urljoin(repository.url + "/", url)
                    canonical = catalog_url(
                        resolved, allow_loopback_http=repository.allow_loopback_http
                    )
                    if (
                        canonical != resolved
                        or url_origin(canonical)
                        not in {repository.origin, *repository.download_origins}
                        or (
                            repository.origin.startswith("https:")
                            and not canonical.startswith("https:")
                        )
                    ):
                        raise ValueError
                    checked.append(canonical)
                sha256 = value.get("digest")
                if not isinstance(sha256, str):
                    raise ValueError
                if sha256.startswith("sha256:"):
                    sha256 = sha256[7:]
                digest(sha256)
                version = value.get("version")
                if not isinstance(version, str):
                    raise ValueError
                result.append(
                    ChartVersion(
                        repository.name, name, version, checked[0], sha256, repository.revision
                    )
                )
                if len(result) > MAX_CATALOG_ENTRIES:
                    raise ValueError
        CatalogSnapshot(0, (repository,), tuple(result))
        return tuple(result)
    except (AppError, ValueError, TypeError):
        raise AppError(
            "Helm repository index is invalid, ambiguous or exceeds the supported catalog policy."
        ) from None


OCI_MANIFEST_MEDIA = "application/vnd.oci.image.manifest.v1+json"
OCI_CONFIG_MEDIA = "application/vnd.cncf.helm.config.v1+json"
OCI_CHART_MEDIA = "application/vnd.cncf.helm.chart.content.v1.tar+gzip"
OCI_PROVENANCE_MEDIA = "application/vnd.cncf.helm.chart.provenance.v1.prov"


def _oci_error() -> AppError:
    return AppError(
        "OCI chart metadata is invalid, changed or outside the supported media/digest/size policy."
    )


def _descriptor(value: object, media_type: str, limit: int) -> tuple[str, int]:
    if (
        not isinstance(value, dict)
        or set(value) - {"mediaType", "digest", "size", "annotations"}
        or value.get("mediaType") != media_type
        or type(value.get("size")) is not int
        or not 1 <= value["size"] <= limit
    ):
        raise _oci_error()
    content_digest = value.get("digest")
    if not isinstance(content_digest, str):
        raise _oci_error()
    return oci_digest(content_digest), value["size"]


def _content(body: CatalogBody, expected: str, size: int) -> None:
    if len(body.data) != size or "sha256:" + hashlib.sha256(body.data).hexdigest() != expected:
        raise _oci_error()
    if body.content_digest is not None and oci_digest(body.content_digest) != expected:
        raise _oci_error()


@dataclass(frozen=True, slots=True)
class _OciChart:
    name: str
    version: str
    manifest_digest: str
    layer_digest: str
    layer_bytes: int


class _OciReader:
    """One cumulative metadata budget for registered-chart listing and resolution."""

    def __init__(
        self, repository: HelmRepository, transport: CatalogHttp, guard: Callable[[], None]
    ) -> None:
        self.repository, self.transport, self.guard = repository, transport, guard
        self.remaining = MAX_INDEX_BYTES
        self.revision = hashlib.sha256(repository.url.encode())
        self.base = repository.origin + "/v2/" + repository.oci_path

    async def get(
        self, url: str, limit: int, accept: str, *, params: dict[str, str] | None = None
    ) -> CatalogBody:
        if self.remaining < 1:
            raise AppError("OCI catalog metadata exceeded its cumulative byte bound.")
        body = await self.transport.get(
            url,
            max_bytes=min(limit, self.remaining),
            accept=accept,
            guard=self.guard,
            params=params,
        )
        self.remaining -= len(body.data)

        def record() -> None:
            self.revision.update(len(body.data).to_bytes(8, "big"))
            self.revision.update(body.data)

        await parse_owned(record)
        return body

    async def chart(self, reference: str, *, expected_version: str | None = None) -> _OciChart:
        body = await self.get(
            self.base + "/manifests/" + reference, MAX_INDEX_BYTES, OCI_MANIFEST_MEDIA
        )
        actual = await parse_owned(lambda: "sha256:" + hashlib.sha256(body.data).hexdigest())
        if (
            body.content_type != OCI_MANIFEST_MEDIA
            or (reference.startswith("sha256:") and reference != actual)
            or (body.content_digest is not None and oci_digest(body.content_digest) != actual)
        ):
            raise _oci_error()
        value = await parse_owned(partial(helm_json, body.data, limit=MAX_INDEX_BYTES))
        if (
            not isinstance(value, dict)
            or type(value.get("schemaVersion")) is not int
            or value["schemaVersion"] != 2
            or value.get("mediaType") != OCI_MANIFEST_MEDIA
            or "subject" in value
        ):
            raise _oci_error()
        config_digest, config_size = _descriptor(
            value.get("config"), OCI_CONFIG_MEDIA, MAX_VALUES_BYTES
        )
        layers = value.get("layers")
        if not isinstance(layers, list) or not 1 <= len(layers) <= 2:
            raise _oci_error()
        selected: tuple[str, int] | None = None
        provenance = False
        for layer in layers:
            if isinstance(layer, dict) and layer.get("mediaType") == OCI_CHART_MEDIA:
                if selected is not None:
                    raise _oci_error()
                selected = _descriptor(layer, OCI_CHART_MEDIA, MAX_CHART_BYTES)
            elif not provenance:
                _descriptor(layer, OCI_PROVENANCE_MEDIA, MAX_VALUES_BYTES)
                provenance = True
            else:
                raise _oci_error()
        if selected is None:
            raise _oci_error()
        config = await self.get(
            self.base + "/blobs/" + config_digest, config_size, OCI_CONFIG_MEDIA
        )
        await parse_owned(lambda: _content(config, config_digest, config_size))
        metadata = await parse_owned(lambda: helm_json(config.data, limit=MAX_VALUES_BYTES))
        if (
            not isinstance(metadata, dict)
            or metadata.get("apiVersion") != "v2"
            or metadata.get("name") != self.repository.oci_path.rsplit("/", 1)[-1]
        ):
            raise _oci_error()
        version = metadata.get("version")
        if not isinstance(version, str):
            raise _oci_error()
        chart_version(version)
        if expected_version is not None and version != expected_version:
            raise _oci_error()
        return _OciChart(metadata["name"], version, actual, selected[0], selected[1])

    async def tags(self) -> tuple[str, ...]:
        url = self.base + "/tags/list"
        params = {"n": "500"}
        tags: list[str] = []
        seen: set[str] = set()
        continuations: set[tuple[tuple[str, str], ...]] = set()
        for _ in range(MAX_CATALOG_PAGES):
            body = await self.get(url, MAX_INDEX_BYTES, "application/json", params=params)
            value = await parse_owned(partial(helm_json, body.data, limit=MAX_INDEX_BYTES))
            if not isinstance(value, dict) or value.get("name") != self.repository.oci_path:
                raise _oci_error()
            page = value.get("tags")
            if page is None:
                page = []
            if not isinstance(page, list) or len(page) > 500:
                raise _oci_error()
            for tag in page:
                oci_tag(tag)
                if tag in seen or (tags and tag.casefold() < tags[-1].casefold()):
                    raise _oci_error()
                tags.append(tag)
                seen.add(tag)
                if len(tags) > MAX_CATALOG_ENTRIES:
                    raise _oci_error()
            if body.link is None:
                return tuple(tags)
            match = re.fullmatch(r'<([^<>]+)>;\s*rel="next"', body.link)
            if match is None or not page:
                raise _oci_error()
            destination = urlsplit(urljoin(url, match[1]))
            if (
                urlunsplit((destination.scheme, destination.netloc, destination.path, "", ""))
                != url
                or destination.fragment
            ):
                raise _oci_error()
            try:
                pairs = parse_qsl(destination.query, strict_parsing=True)
            except ValueError:
                raise _oci_error() from None
            params = dict(pairs)
            if (
                len(params) != len(pairs)
                or set(params) - {"n", "last"}
                or params.get("last") != page[-1]
            ):
                raise _oci_error()
            marker = tuple(sorted(params.items()))
            if marker in continuations:
                raise _oci_error()
            continuations.add(marker)
        raise AppError("OCI tag listing exceeded its fixed pagination bound.")


class HelmCatalogService:
    """Serialize owned catalog effects; cached browsing never performs network work."""

    def __init__(self, policy: AccessPolicy, directory: Path | None = None) -> None:
        root = (
            directory
            if directory is not None
            else user_state_path("kuberich", appauthor=False) / "helm"
        )
        self.policy = policy
        self._files = CatalogFiles(root)
        self._receipt = CatalogReceipt(CatalogSnapshot())
        self._loaded = False
        self._lock = asyncio.Lock()
        self._closed = False
        self._tasks: set[asyncio.Task[Any]] = set()
        self._transports: set[CatalogHttp] = set()

    @property
    def snapshot(self) -> CatalogSnapshot:
        return self._receipt.snapshot

    @property
    def operation_count(self) -> int:
        return len(self._tasks)

    def _check(self, *, mutate: bool = False) -> None:
        self.policy.require(Action.MUTATE if mutate else Action.READ)
        if self._closed:
            raise AppError("Helm repository catalog is closed.")

    def _mutate(self) -> None:
        self._check(mutate=True)

    async def _own[T](self, operation: Coroutine[Any, Any, T]) -> T:
        task = asyncio.create_task(operation)
        self._tasks.add(task)
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            task.cancel()
            await finish_owned(asyncio.gather(task, return_exceptions=True))
            raise
        finally:
            self._tasks.discard(task)

    async def _work[T](self, operation: Callable[[threading.Event], T]) -> T:
        cancel = threading.Event()
        task = asyncio.create_task(asyncio.to_thread(operation, cancel))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            cancel.set()
            await finish_owned(asyncio.gather(task, return_exceptions=True))
            raise

    async def _load(self) -> CatalogSnapshot:
        self._check()
        current = await self._work(
            lambda cancel: self._files.read(guard=self._check, cancel=cancel)
        )
        self._check()
        if (
            self._loaded
            and current != self._receipt
            and current.snapshot.generation <= self.snapshot.generation
        ):
            raise AppError(
                "Helm catalog files changed without a new generation; reopen the catalog owner."
            )
        self._receipt = current
        self._loaded = True
        return self.snapshot

    async def load(self) -> CatalogSnapshot:
        async def run() -> CatalogSnapshot:
            async with self._lock:
                return await self._load()

        return await self._own(run())

    async def revalidate(self, generation: int) -> None:
        """Reread exact private inputs without importing replacement authority or networking."""

        async def run() -> None:
            self._check()
            async with self._lock:
                if type(generation) is not int or generation != self.snapshot.generation:
                    raise AppError(
                        "Helm catalog generation changed; reload and prepare a fresh review."
                    )
                captured = self._receipt
                current = await self._work(
                    lambda cancel: self._files.read(guard=self._check, cancel=cancel)
                )
                self._check()
                if current != captured:
                    raise AppError("Helm catalog files changed; reload and prepare a fresh review.")
                await self._work(
                    lambda cancel: self._files.credentials(
                        captured, guard=self._check, cancel=cancel
                    )
                )
                self._check()

        await self._own(run())

    async def _ready(self) -> None:
        if not self._loaded:
            await self._load()

    async def _credentials(self) -> dict[str, RepositoryCredentials]:
        guard = self._mutate
        return await self._work(
            lambda cancel: self._files.credentials(self._receipt, guard=guard, cancel=cancel)
        )

    async def _save(
        self, snapshot: CatalogSnapshot, credentials: dict[str, RepositoryCredentials]
    ) -> CatalogSnapshot:
        guard = self._mutate
        guard()
        self._receipt = await self._work(
            lambda cancel: self._files.write(
                snapshot, credentials, self._receipt, guard=guard, cancel=cancel
            )
        )
        guard()
        return self.snapshot

    async def _fetch_oci(
        self, repository: HelmRepository, transport: CatalogHttp
    ) -> tuple[HelmRepository, tuple[ChartVersion, ...]]:
        reader = _OciReader(repository, transport, self._mutate)
        selected = []
        if repository.pinned_digest is not None:
            selected.append(await reader.chart(repository.pinned_digest))
        else:
            for tag in await reader.tags():
                version = oci_chart_version(tag)
                if version is not None:
                    selected.append(await reader.chart(tag, expected_version=version))
        current = replace(repository, revision=reader.revision.hexdigest())
        charts = tuple(
            ChartVersion(
                current.name,
                item.name,
                item.version,
                reader.base + "/manifests/" + item.manifest_digest,
                item.layer_digest[7:],
                current.revision,
                item.manifest_digest,
            )
            for item in selected
        )
        CatalogSnapshot(0, (current,), charts)
        return current, charts

    async def _fetch(
        self, repository: HelmRepository, credentials: RepositoryCredentials
    ) -> tuple[HelmRepository, tuple[ChartVersion, ...]]:
        transport = CatalogHttp(repository, credentials)
        self._transports.add(transport)
        guard = self._mutate
        try:
            async with asyncio.timeout(120):
                if repository.kind is HelmRepositoryKind.OCI:
                    return await self._fetch_oci(repository, transport)
                body = await transport.get(
                    repository.url + "/index.yaml",
                    max_bytes=MAX_INDEX_BYTES,
                    accept="application/yaml, text/yaml, application/octet-stream",
                    guard=guard,
                )
                revision = await parse_owned(lambda: hashlib.sha256(body.data).hexdigest())
                current = replace(repository, revision=revision)
                charts = await parse_owned(lambda: _index(current, body.data))
                guard()
                return current, charts
        except TimeoutError:
            raise AppError(
                "Helm catalog preparation exceeded its deadline; refresh explicitly before retrying."
            ) from None
        finally:
            await finish_owned(asyncio.create_task(transport.close()))
            self._transports.discard(transport)

    async def add(
        self,
        name: str,
        url: str,
        *,
        oci: bool = False,
        credentials: RepositoryCredentials | None = None,
        allow_loopback_http: bool = False,
        ca_file: Path | None = None,
        token_origins: tuple[str, ...] = (),
        download_origins: tuple[str, ...] = (),
    ) -> CatalogSnapshot:
        async def run() -> CatalogSnapshot:
            self._check(mutate=True)
            async with self._lock:
                await self._ready()
                if any(repository.name == name for repository in self.snapshot.repositories):
                    raise AppError(
                        "A Helm repository with this name already exists; update or remove that exact entry."
                    )
                kind = HelmRepositoryKind.OCI if oci else HelmRepositoryKind.HTTP
                canonical = catalog_url(url, allow_loopback_http=allow_loopback_http, oci=oci)
                repository = HelmRepository(
                    name,
                    canonical,
                    kind,
                    "0" * 64,
                    allow_loopback_http,
                    ca_file,
                    token_origins,
                    download_origins,
                )
                configured = credentials if credentials is not None else RepositoryCredentials()
                if not isinstance(configured, RepositoryCredentials):
                    raise AppError(
                        "Helm repository credentials require an explicit typed configuration."
                    )
                previous = await self._credentials()
                current, charts = await self._fetch(repository, configured)
                snapshot = CatalogSnapshot(
                    self.snapshot.generation + 1,
                    (*self.snapshot.repositories, current),
                    (*self.snapshot.charts, *charts),
                )
                return await self._save(snapshot, {**previous, name: configured})

        return await self._own(run())

    def _repository(self, name: str) -> HelmRepository:
        result = next((item for item in self.snapshot.repositories if item.name == name), None)
        if result is None:
            raise AppError("Select an existing Helm repository from the current catalog.")
        return result

    def update(
        self,
        name: str,
        *,
        expected_generation: int | None = None,
        credentials: RepositoryCredentials | None = None,
    ) -> Coroutine[Any, Any, CatalogSnapshot]:
        generation = (
            self.snapshot.generation if expected_generation is None else expected_generation
        )

        async def run() -> CatalogSnapshot:
            self._check(mutate=True)
            async with self._lock:
                await self._ready()
                if type(generation) is not int or generation != self.snapshot.generation:
                    raise AppError(
                        "Helm catalog generation changed; reload before updating this repository."
                    )
                repository = self._repository(name)
                previous = await self._credentials()
                if credentials is not None:
                    if not isinstance(credentials, RepositoryCredentials):
                        raise AppError(
                            "Helm repository credentials require an explicit typed configuration."
                        )
                    previous[name] = credentials
                current, charts = await self._fetch(repository, previous[name])
                snapshot = CatalogSnapshot(
                    self.snapshot.generation + 1,
                    tuple(
                        current if item.name == name else item
                        for item in self.snapshot.repositories
                    ),
                    (
                        *tuple(item for item in self.snapshot.charts if item.repository != name),
                        *charts,
                    ),
                )
                return await self._save(snapshot, previous)

        return self._own(run())

    def remove(
        self, name: str, *, expected_generation: int | None = None
    ) -> Coroutine[Any, Any, CatalogSnapshot]:
        generation = (
            self.snapshot.generation if expected_generation is None else expected_generation
        )

        async def run() -> CatalogSnapshot:
            self._check(mutate=True)
            async with self._lock:
                await self._ready()
                if type(generation) is not int or generation != self.snapshot.generation:
                    raise AppError(
                        "Helm catalog generation changed; reload before removing this repository."
                    )
                self._repository(name)
                credentials = await self._credentials()
                snapshot = CatalogSnapshot(
                    self.snapshot.generation + 1,
                    tuple(item for item in self.snapshot.repositories if item.name != name),
                    tuple(item for item in self.snapshot.charts if item.repository != name),
                )
                credentials.pop(name)
                return await self._save(snapshot, credentials)

        return self._own(run())

    def search(self, query: str = "") -> tuple[ChartVersion, ...]:
        self._check()
        if not isinstance(query, str) or len(query) > 4096:
            raise AppError("Helm chart search text exceeds its bound.")
        folded = query.casefold()
        result = [
            item
            for item in self.snapshot.charts
            if folded in (item.repository + "/" + item.name + " " + item.version).casefold()
        ]
        return tuple(
            sorted(
                result,
                key=lambda item: (item.repository, item.name, chart_version_key(item.version)),
                reverse=True,
            )
        )

    async def select(self, chart: ChartVersion) -> ChartSnapshot:
        async def run() -> ChartSnapshot:
            self._check(mutate=True)
            async with self._lock:
                await self._ready()
                if not isinstance(chart, ChartVersion) or chart not in self.snapshot.charts:
                    raise AppError(
                        "Helm chart catalog identity changed; select the chart version again."
                    )
                repository = self._repository(chart.repository)
                credentials = await self._credentials()
                transport = CatalogHttp(repository, credentials[repository.name])
                self._transports.add(transport)
                guard = self._mutate
                try:
                    async with asyncio.timeout(120):
                        selected: _OciChart | None = None
                        url, size, accept = (
                            chart.url,
                            MAX_CHART_BYTES,
                            "application/gzip, application/octet-stream",
                        )
                        if repository.kind is HelmRepositoryKind.OCI:
                            if chart.manifest_digest is None:
                                raise _oci_error()
                            reader = _OciReader(repository, transport, guard)
                            if chart.url != reader.base + "/manifests/" + chart.manifest_digest:
                                raise _oci_error()
                            selected = await reader.chart(
                                chart.manifest_digest, expected_version=chart.version
                            )
                            if (
                                selected.name != chart.name
                                or selected.layer_digest != "sha256:" + chart.sha256
                            ):
                                raise _oci_error()
                            url, size, accept = (
                                reader.base + "/blobs/" + selected.layer_digest,
                                selected.layer_bytes,
                                OCI_CHART_MEDIA,
                            )
                        body = await transport.get(url, max_bytes=size, accept=accept, guard=guard)
                        if selected is not None:
                            await parse_owned(
                                lambda: _content(body, selected.layer_digest, selected.layer_bytes)
                            )
                        generation = self.snapshot.generation

                        def freeze() -> ChartSnapshot:
                            if hashlib.sha256(body.data).hexdigest() != chart.sha256:
                                raise AppError("Helm chart package differs from its frozen digest.")
                            defaults = inspect_chart_package(
                                body.data, expected_name=chart.name, expected_version=chart.version
                            )
                            return ChartSnapshot(
                                chart.name,
                                chart.version,
                                chart.repository + "/" + chart.name,
                                chart.sha256,
                                body.data,
                                defaults,
                                generation,
                                chart.manifest_digest,
                                selected.layer_digest if selected is not None else None,
                                chart.catalog_revision,
                            )

                        snapshot = await parse_owned(freeze)
                        guard()
                        return snapshot
                except TimeoutError:
                    raise AppError(
                        "Helm chart selection exceeded its deadline; select explicitly before retrying."
                    ) from None
                finally:
                    await finish_owned(asyncio.create_task(transport.close()))
                    self._transports.discard(transport)

        return await self._own(run())

    async def close(self) -> None:
        self._closed = True
        tasks = tuple(self._tasks)
        for task in tasks:
            task.cancel()
        await finish_owned(asyncio.gather(*tasks, return_exceptions=True))
        await finish_owned(
            asyncio.gather(*(transport.close() for transport in tuple(self._transports)))
        )
