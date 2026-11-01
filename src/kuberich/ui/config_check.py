"""One validation path for `kuberich config check` and for reloading preferences."""

from kuberich.config.paths import ConfigLocation
from kuberich.config.schema import ConfigDocument, Settings
from kuberich.config.themes import BUILTINS, appearance_from
from kuberich.diagnostics.redaction import sanitize_text
from kuberich.errors import AppError


def validate_preferences(
    document: ConfigDocument, location: ConfigLocation, settings: Settings
) -> None:
    """Check every section; plugin files are read, so call this off the event loop."""
    navigation = None
    if "navigation" in document.extensions:
        from kuberich.config.navigation import navigation_from, validate_resource_views

        navigation = navigation_from(document)
        validate_resource_views(navigation)
    if "forwarding" in document.extensions:
        from kuberich.config.forwarding import forwarding_from

        forwarding_from(document)
    if "jumps" in document.extensions:
        from kuberich.config.jumps import jumps_from

        jumps_from(document)
    if "context_settings" in document.extensions:
        from kuberich.config.context_settings import context_settings_from

        context_settings_from(document)
    if "plugins" in document.extensions:
        from kuberich.adapters.plugin_files import load_plugins
        from kuberich.config.plugins import plugins_from

        plugin_preferences = plugins_from(document, location.path.parent)
        for context in (None, *(name for name, _ in plugin_preferences.contexts)):
            load_plugins(
                plugin_preferences, context, navigation.keys if navigation is not None else ()
            )
    appearance = appearance_from(document)
    if settings.theme not in BUILTINS | {theme.name for theme in appearance.themes}:
        raise AppError("Selected theme is unavailable; choose k9s or a registered theme.")


def unsupported_fields(document: ConfigDocument) -> str | None:
    names = sorted(sanitize_text(str(name))[:64] for name in document.unknown)
    if not names:
        return None
    shown = ", ".join(names[:8]) + (f" and {len(names) - 8} more" if len(names) > 8 else "")
    return f"Unsupported preference fields are kept but ignored: {shown}."
