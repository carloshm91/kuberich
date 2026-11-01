"""Typed, independently versioned navigation and per-context resource preferences."""

from dataclasses import dataclass, replace

from kuberich.config.schema import ConfigDocument
from kuberich.domain.aliases import Aliases, parse_aliases
from kuberich.domain.connections import namespace_name
from kuberich.domain.keyboard import KeyOverrides, key_mapping, parse_keys
from kuberich.domain.resource_preferences import ViewSpec, applicable_view, parse_view, resource_key
from kuberich.errors import AppError
from kuberich.security.arguments import validate_argument

type Views = tuple[tuple[str, ViewSpec], ...]


def _views(value: object, legacy: bool) -> Views:
    if not isinstance(value, dict) or len(value) > 128:
        raise AppError("views must contain at most 128 version-pinned resource entries.")
    result = {}
    for key, raw in value.items():
        key = resource_key(key)
        view = parse_view(raw, legacy=legacy)
        if view.printer_signature is not None and not key.startswith("server:"):
            if not legacy:
                raise AppError("Printer-based views use a server: resource identifier.")
            key = "server:" + key
        if key in result:
            raise AppError("Migrated resource preferences contain duplicate view identifiers.")
        result[key] = view
    return tuple(sorted(result.items()))


@dataclass(frozen=True)
class NavigationPreferences:
    keys: KeyOverrides = ()
    aliases: Aliases = ()
    views: Views = ()
    contexts: tuple[tuple[str, Views], ...] = ()
    migrated: bool = False
    mouse: bool = False
    favorites: tuple[tuple[str, tuple[str, ...]], ...] = ()

    def mapping(self) -> dict[str, object]:
        return {
            **({"mouse": True} if self.mouse else {}),
            **(
                {"favorites": {context: list(names) for context, names in self.favorites}}
                if self.favorites
                else {}
            ),
            "schema_version": 1,
            "keys": dict(key_mapping(self.keys)),
            "aliases": dict(self.aliases),
            "views": {key: view.mapping() for key, view in self.views},
            "contexts": {
                context: {"views": {key: view.mapping() for key, view in views}}
                for context, views in self.contexts
            },
        }

    def with_favorite(
        self, context: str, name: str, *, remove: bool = False
    ) -> "NavigationPreferences":
        namespace_name(name)
        values = dict(self.favorites)
        selected = set(values.get(context, ()))
        selected.discard(name) if remove else selected.add(name)
        values[context] = tuple(sorted(selected))
        updated = replace(self, favorites=tuple(sorted(values.items())))
        return parse_navigation(updated.mapping())

    def choices(self, key: str, context: str | None) -> tuple[ViewSpec, ...]:
        scoped = dict(dict(self.contexts).get(context, ())) if context is not None else {}
        return tuple(
            view for view in (scoped.get(key), dict(self.views).get(key)) if view is not None
        )

    def with_view(self, key: str, view: ViewSpec, context: str | None) -> "NavigationPreferences":
        resource_key(key)
        if context is None:
            views = dict(self.views)
            views[key] = view
            return replace(self, views=tuple(sorted(views.items())), migrated=False)
        contexts = dict(self.contexts)
        selected = dict(contexts.get(context, ()))
        selected[key] = view
        contexts[context] = tuple(sorted(selected.items()))
        return replace(self, contexts=tuple(sorted(contexts.items())), migrated=False)


def parse_navigation(
    value: object, reserved: frozenset[str] = frozenset()
) -> NavigationPreferences:
    if not isinstance(value, dict) or value.keys() - {
        "schema_version",
        "keys",
        "aliases",
        "views",
        "contexts",
        "mouse",
        "favorites",
    }:
        raise AppError(
            "navigation accepts only schema_version, keys, aliases, views, contexts, mouse and favorites."
        )
    schema = value.get("schema_version", 0)
    if type(schema) is not int or schema not in {0, 1}:
        raise AppError("Unsupported navigation.schema_version; use version 1.")
    keys = value.get("keys", {})
    if (
        schema == 0
        and isinstance(keys, dict)
        and keys
        and all(isinstance(key, str) for key in keys.values())
    ):
        keys = {"table": keys}
    contexts = value.get("contexts", {})
    if not isinstance(contexts, dict) or len(contexts) > 128:
        raise AppError("navigation.contexts accepts at most 128 context entries.")
    scoped = []
    for context, fields in contexts.items():
        if not isinstance(context, str) or not 1 <= len(context) <= 253:
            raise AppError("Navigation context names must be 1-253 characters.")
        validate_argument(context)
        if not isinstance(fields, dict) or fields.keys() - {"views"}:
            raise AppError("Each navigation context accepts a views mapping.")
        scoped.append((context, _views(fields.get("views", {}), schema == 0)))
    mouse = value.get("mouse", False)
    if type(mouse) is not bool:
        raise AppError("navigation.mouse must be true or false.")
    favorites = value.get("favorites", {})
    if not isinstance(favorites, dict) or len(favorites) > 128:
        raise AppError("Namespace favorites support at most 128 contexts.")
    parsed_favorites = []
    for context, names in favorites.items():
        if not isinstance(context, str) or not 1 <= len(context) <= 253:
            raise AppError("Favorite context names must be 1-253 characters.")
        validate_argument(context)
        if (
            not isinstance(names, list)
            or any(not isinstance(name, str) for name in names)
            or len(names) > 64
            or len(set(names)) != len(names)
        ):
            raise AppError("Favorites require at most 64 unique namespace names per context.")
        parsed_favorites.append((context, tuple(sorted(namespace_name(name) for name in names))))
    return NavigationPreferences(
        parse_keys(keys),
        parse_aliases(value.get("aliases", {}), reserved),
        _views(value.get("views", {}), schema == 0),
        tuple(sorted(scoped)),
        schema == 0,
        mouse,
        tuple(sorted(parsed_favorites)),
    )


def navigation_from(document: ConfigDocument) -> NavigationPreferences:
    if "navigation" not in document.extensions:
        return NavigationPreferences()

    from kuberich.services.commands import RESERVED_COMMANDS

    return parse_navigation(document.extensions["navigation"], RESERVED_COMMANDS)


def validate_resource_views(navigation: NavigationPreferences) -> None:
    """Validate known built-in fields offline; discovered schemas need the actual API."""
    if not navigation.views and not any(views for _, views in navigation.contexts):
        return

    from kuberich.domain.pods import PodColumn
    from kuberich.domain.registry import RESOURCE_ALIASES

    fields = {
        "v1/pods": tuple(column.value for column in PodColumn),
        "v1/namespaces": ("name", "status", "age"),
    }
    for definition in RESOURCE_ALIASES.values():
        key = "/".join(part for part in (definition.group, "v1", definition.name) if part)
        fields[key] = tuple(column.key for column in definition.columns)
    for views in (navigation.views, *(views for _, views in navigation.contexts)):
        for key, view in views:
            if key in fields:
                applicable_view(view, fields[key])
