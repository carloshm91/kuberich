"""One validation path for `kuberich config check` and for reloading preferences."""

from kuberich.adapters.plugin_files import load_plugins
from kuberich.config.context_settings import context_settings_from
from kuberich.config.forwarding import forwarding_from
from kuberich.config.jumps import jumps_from
from kuberich.config.navigation import navigation_from, validate_resource_views
from kuberich.config.paths import ConfigLocation
from kuberich.config.plugins import plugins_from
from kuberich.config.schema import ConfigDocument, Settings
from kuberich.diagnostics.redaction import sanitize_text
from kuberich.errors import AppError
from kuberich.ui.theme_catalog import BUILTINS, appearance_from


def validate_preferences(
    document: ConfigDocument, location: ConfigLocation, settings: Settings
) -> None:
    """Check every section; plugin files are read, so call this off the event loop."""
    navigation = navigation_from(document)
    validate_resource_views(navigation)
    forwarding_from(document)
    jumps_from(document)
    context_settings_from(document)
    plugin_preferences = plugins_from(document, location.path.parent)
    for context in (None, *(name for name, _ in plugin_preferences.contexts)):
        load_plugins(plugin_preferences, context, navigation.keys)
    appearance = appearance_from(document)
    if settings.theme not in BUILTINS | {theme.name for theme in appearance.themes}:
        raise AppError("Selected theme is unavailable; choose k9s or a registered theme.")


def unsupported_fields(document: ConfigDocument) -> str | None:
    names = sorted(sanitize_text(str(name))[:64] for name in document.unknown)
    if not names:
        return None
    shown = ", ".join(names[:8]) + (f" and {len(names) - 8} more" if len(names) > 8 else "")
    return f"Unsupported preference fields are kept but ignored: {shown}."
