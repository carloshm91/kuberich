"""Optional Service-proxy history settings; loading performs no network or writes."""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from kuberich.config.popeye import PopeyeSettings, parse_popeye_settings
from kuberich.config.schema import ConfigDocument
from kuberich.domain.history import ExternalHistoryBackend, HistoryBackend, HistoryOptions, Provider
from kuberich.errors import AppError


@dataclass(frozen=True)
class ObservabilityPreferences:
    history: HistoryOptions | None = None
    contexts: tuple[tuple[str, "ObservabilityPreferences"], ...] = ()
    popeye: PopeyeSettings | None = None

    def for_context(self, context: str) -> "ObservabilityPreferences":
        return dict(self.contexts).get(context, self)


def parse_observability(value: object, *, context: bool = False) -> ObservabilityPreferences:
    allowed = (
        {"history", "popeye"} if context else {"schema_version", "history", "popeye", "contexts"}
    )
    if not isinstance(value, dict) or value.keys() - allowed:
        raise AppError("observability accepts schema_version, history, popeye and contexts.")
    if not context and (
        type(value.get("schema_version", 1)) is not int or value.get("schema_version", 1) != 1
    ):
        raise AppError("observability.schema_version must be 1.")
    raw = value.get("history")
    history = None
    if raw is not None:
        fields = {
            "namespace",
            "service",
            "port",
            "scheme",
            "matchers",
            "cluster_label",
            "cluster_value",
            "url",
            "ca_file",
            "bearer_token_file",
            "provider",
            "profile",
            "node_matchers",
            "state_matchers",
            "api_prefix",
            "rate_window_seconds",
        }
        if not isinstance(raw, dict) or raw.keys() - fields:
            raise AppError(
                "observability.history requires an explicit Service or URL configuration."
            )
        matchers = raw.get("matchers", {})
        if not isinstance(matchers, dict):
            raise AppError("observability.history.matchers must be a mapping.")
        namespace, service = raw.get("namespace"), raw.get("service")
        port, scheme = raw.get("port", 9090), raw.get("scheme", "http")
        cluster_label, cluster_value = raw.get("cluster_label"), raw.get("cluster_value")
        if type(port) is not int or not isinstance(scheme, str):
            raise AppError("observability.history requires an integer port and string scheme.")
        if (cluster_label is not None and not isinstance(cluster_label, str)) or (
            cluster_value is not None and not isinstance(cluster_value, str)
        ):
            raise AppError("observability history cluster selectors must be strings.")
        endpoint: HistoryBackend | ExternalHistoryBackend
        if "url" in raw:
            if raw.keys() & {"namespace", "service", "port", "scheme", "api_prefix"}:
                raise AppError("History URL and Service settings are mutually exclusive.")
            url = raw["url"]
            if not isinstance(url, str):
                raise AppError("History URL must be a string.")
            paths = []
            for key in ("ca_file", "bearer_token_file"):
                item = raw.get(key)
                if item is not None and (
                    not isinstance(item, str)
                    or not item
                    or len(item) > 4096
                    or any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in item)
                ):
                    raise AppError(
                        "History credential paths require bounded text without controls."
                    )
                paths.append(Path(item) if item is not None else None)
            endpoint = ExternalHistoryBackend(
                url, tuple(matchers.items()), cluster_label, cluster_value, *paths
            )
        else:
            if raw.keys() & {"ca_file", "bearer_token_file"}:
                raise AppError("Independent history credential files require an external URL.")
            if not isinstance(namespace, str) or not isinstance(service, str):
                raise AppError("observability.history requires namespace and service strings.")
            endpoint = HistoryBackend(
                namespace,
                service,
                port,
                scheme,
                tuple(matchers.items()),
                cluster_label,
                cluster_value,
            )
        extra_matchers = []
        for key in ("node_matchers", "state_matchers"):
            item = raw.get(key, {})
            if not isinstance(item, dict):
                raise AppError("History source matchers must be mappings.")
            extra_matchers.append(tuple(item.items()))
        provider, profile = raw.get("provider", "auto"), raw.get("profile", "kubernetes-standard")
        prefix = raw.get("api_prefix", "")
        if (
            not isinstance(provider, str)
            or not isinstance(profile, str)
            or not isinstance(prefix, str)
        ):
            raise AppError("History provider, profile and API prefix must be strings.")
        history = HistoryOptions(
            endpoint,
            cast(Provider, provider),
            cast("Literal['kubernetes-standard']", profile),
            node_matchers=extra_matchers[0],
            state_matchers=extra_matchers[1],
            api_prefix=prefix,
            rate_window_seconds=raw.get("rate_window_seconds", 300),
        )
    contexts = value.get("contexts", {})
    if not isinstance(contexts, dict) or len(contexts) > 128:
        raise AppError("observability.contexts accepts at most 128 exact context names.")
    nested = []
    for name, spec in contexts.items():
        if (
            not isinstance(name, str)
            or not 1 <= len(name) <= 253
            or any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in name)
        ):
            raise AppError("Observability context names must be bounded text without controls.")
        nested.append((name, parse_observability(spec, context=True)))
    return ObservabilityPreferences(
        history, tuple(nested), parse_popeye_settings(value.get("popeye"))
    )


def observability_from(document: ConfigDocument) -> ObservabilityPreferences:
    return (
        parse_observability(document.extensions["observability"])
        if "observability" in document.extensions
        else ObservabilityPreferences()
    )
