"""Read the explicitly selected kubeconfig and print a migration fragment only."""

from collections.abc import Mapping

import yaml

from kuberich.config.catalog import load_catalog
from kuberich.domain.connections import ConnectionProblem, ConnectionRequest
from kuberich.domain.oidc_migration import oidc_exec_fragment
from kuberich.errors import AppError


def render_oidc_migration(request: ConnectionRequest, environment: Mapping[str, str]) -> str:
    catalog = load_catalog(request, environment)
    selected = request.context or catalog.current
    if selected is None:
        raise AppError("OIDC migration needs --context or a kubeconfig current-context.")
    try:
        context = catalog.select(selected)
    except ConnectionProblem as error:
        raise AppError(str(error)) from None
    fragment = oidc_exec_fragment(context.user.data.get("auth-provider"), context.user.directory)
    return (
        "# Review this fragment before replacing the selected user's auth-provider entry.\n"
        "# Requires int128/kubelogin; this command does not install or execute it.\n"
        "# Replace any CLIENT_SECRET placeholder manually in a private configuration.\n"
        "# Existing tokens are omitted; the helper owns future sign-in and refresh.\n"
        "# Review legacy extra-scopes and provider policy with your administrator.\n"
        + yaml.safe_dump(fragment, sort_keys=False, allow_unicode=True)
    )
