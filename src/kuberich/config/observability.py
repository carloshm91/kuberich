"""Optional Service-proxy history settings; loading performs no network or writes."""

from dataclasses import dataclass

from kuberich.config.schema import ConfigDocument
from kuberich.domain.history import HistoryBackend
from kuberich.errors import AppError


@dataclass(frozen=True)
class ObservabilityPreferences:
    history: HistoryBackend | None = None
    contexts: tuple[tuple[str, "ObservabilityPreferences"], ...] = ()

    def for_context(self, context: str) -> "ObservabilityPreferences":
        return dict(self.contexts).get(context, self)


def parse_observability(value: object, *, context: bool = False) -> ObservabilityPreferences:
    allowed = {"history"} if context else {"schema_version", "history", "contexts"}
    if not isinstance(value, dict) or value.keys() - allowed:
        raise AppError("observability accepts schema_version, history and contexts.")
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
        }
        if not isinstance(raw, dict) or raw.keys() - fields:
            raise AppError("observability.history requires a Service-proxy configuration.")
        matchers = raw.get("matchers", {})
        if not isinstance(matchers, dict):
            raise AppError("observability.history.matchers must be a mapping.")
        namespace, service = raw.get("namespace"), raw.get("service")
        port, scheme = raw.get("port", 9090), raw.get("scheme", "http")
        cluster_label, cluster_value = raw.get("cluster_label"), raw.get("cluster_value")
        if not isinstance(namespace, str) or not isinstance(service, str):
            raise AppError("observability.history requires namespace and service strings.")
        if type(port) is not int or not isinstance(scheme, str):
            raise AppError("observability.history requires an integer port and string scheme.")
        if (cluster_label is not None and not isinstance(cluster_label, str)) or (
            cluster_value is not None and not isinstance(cluster_value, str)
        ):
            raise AppError("observability history cluster selectors must be strings.")
        history = HistoryBackend(
            namespace, service, port, scheme, tuple(matchers.items()), cluster_label, cluster_value
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
    return ObservabilityPreferences(history, tuple(nested))


def observability_from(document: ConfigDocument) -> ObservabilityPreferences:
    return (
        parse_observability(document.extensions["observability"])
        if "observability" in document.extensions
        else ObservabilityPreferences()
    )
