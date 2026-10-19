"""Explicit local opt-in for annotation shortcuts and versioned named presets."""

from dataclasses import dataclass

from kuberich.config.schema import ConfigDocument
from kuberich.domain.forward_presets import ForwardPreset, ForwardTransport, mapping_text
from kuberich.errors import AppError


@dataclass(frozen=True)
class ForwardPreferences:
    auto_annotations: bool = False
    presets: tuple[ForwardPreset, ...] = ()
    contexts: tuple[tuple[str, "ForwardPreferences"], ...] = ()

    def for_context(self, context: str) -> "ForwardPreferences":
        return dict(self.contexts).get(context, self)


def parse_forwarding(value: object, *, context: bool = False) -> ForwardPreferences:
    allowed = (
        {"auto_annotations", "presets"}
        if context
        else {"schema_version", "auto_annotations", "presets", "contexts"}
    )
    if not isinstance(value, dict) or value.keys() - allowed:
        raise AppError("forwarding accepts schema_version, auto_annotations, presets and contexts.")
    if not context and (
        type(value.get("schema_version", 1)) is not int or value.get("schema_version", 1) != 1
    ):
        raise AppError("forwarding.schema_version must be 1.")
    automatic = value.get("auto_annotations", False)
    if type(automatic) is not bool:
        raise AppError("forwarding.auto_annotations must be true or false.")
    presets = value.get("presets", {})
    if not isinstance(presets, dict) or len(presets) > 32:
        raise AppError("forwarding.presets accepts at most 32 named presets.")
    parsed = []
    for name, spec in presets.items():
        if name in {"manual", "annotation"}:
            raise AppError("manual and annotation are reserved forward preset names.")
        if not isinstance(spec, dict) or spec.keys() - {"ports", "address", "transport", "retries"}:
            raise AppError("Each forward preset accepts ports, address, transport and retries.")
        try:
            transport = ForwardTransport(spec.get("transport", "auto"))
        except (TypeError, ValueError):
            raise AppError("Forward transport must be auto, websocket or spdy.") from None
        parsed.append(
            ForwardPreset(
                name,
                mapping_text(spec.get("ports")),
                spec.get("address", "127.0.0.1"),
                transport,
                spec.get("retries", 0),
            )
        )
    contexts = value.get("contexts", {})
    if not isinstance(contexts, dict) or len(contexts) > 128:
        raise AppError("forwarding.contexts accepts at most 128 exact context names.")
    nested = []
    for name, spec in contexts.items():
        if (
            not isinstance(name, str)
            or not 1 <= len(name) <= 253
            or any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in name)
        ):
            raise AppError("Forward context names must be bounded text without controls.")
        nested.append((name, parse_forwarding(spec, context=True)))
    return ForwardPreferences(automatic, tuple(parsed), tuple(nested))


def forwarding_from(document: ConfigDocument) -> ForwardPreferences:
    return (
        parse_forwarding(document.extensions["forwarding"])
        if "forwarding" in document.extensions
        else ForwardPreferences()
    )
