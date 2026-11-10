"""Which workspace actions apply to the current view (pure, Textual-free rules)."""

from dataclasses import dataclass

from kuberich.domain.curated import curated_read_only
from kuberich.domain.resources import ApiResource

MUTATING_TABLE_ACTIONS = frozenset({"edit", "review_delete", "annotate", "cleanup_pods", "upload"})

WORKLOAD_LOG_VIEWS = frozenset(
    {
        "pods",
        "deployments",
        "replicasets",
        "statefulsets",
        "daemonsets",
        "jobs",
        "cronjobs",
        "replicationcontrollers",
    }
)
POD_ONLY = frozenset({"logs", "shell", "attach", "upload", "download"})
# Table actions are unavailable while a modal screen or an input has focus.
TABLE_ACTIONS = frozenset(
    {
        "mark_selection",
        "mark_range",
        "copy_selection",
        "focus_filter",
        "focus_command",
        "history_back",
        "history_forward",
        "inspect_yaml",
        "inspect_details",
        "inspect_events",
        "configuration_data",
        "edit",
        "logs",
        "logs_all",
        "shell",
        "node_shell",
        "cordon",
        "drain",
        "uncordon",
        "attach",
        "upload",
        "download",
        "port_forward",
        "review_delete",
        "xray",
        "usedby",
        "open_relationship",
        "diagnose",
    }
)


@dataclass(frozen=True)
class ViewState:
    resource: str
    generic: bool = False
    modal: bool = False
    typing: bool = False
    descriptor: ApiResource | None = None


def action_available(action: str, view: ViewState) -> bool:
    if action in {"node_shell", "cordon", "drain", "uncordon"}:
        descriptor = view.descriptor
        return (
            view.resource == "nodes"
            and not view.modal
            and not view.typing
            and (
                not view.generic
                if descriptor is None
                else (
                    descriptor.group,
                    descriptor.version,
                    descriptor.name,
                    descriptor.kind,
                    descriptor.namespaced,
                )
                == ("", "v1", "nodes", "Node", False)
            )
        )
    if view.resource == "helm" and action in (
        TABLE_ACTIONS - {"focus_filter", "focus_command", "history_back", "history_forward"}
    ) | {"annotate", "cleanup_pods", "views"}:
        return False
    if (
        view.descriptor is not None
        and curated_read_only(view.descriptor)
        and action in MUTATING_TABLE_ACTIONS
    ):
        return False
    if action == "metric_history":
        return (
            view.resource in WORKLOAD_LOG_VIEWS | {"nodes", "pulse"}
            and not view.modal
            and not view.typing
        )
    if action == "diagnose" and (view.generic or view.resource not in WORKLOAD_LOG_VIEWS):
        return False
    if action == "open_relationship" and view.resource not in {
        "relationships",
        "authorization",
        "diagnostics",
    }:
        return False
    if action in {"xray", "usedby"} and view.resource in {
        "contexts",
        "pulse",
        "authorization",
        "diagnostics",
    }:
        return False
    if view.resource in {"pulse", "relationships", "authorization", "diagnostics"} and action in {
        "annotate",
        "cleanup_pods",
    }:
        return False
    if view.resource == "relationships" and action in TABLE_ACTIONS - {
        "focus_filter",
        "focus_command",
        "history_back",
        "history_forward",
        "xray",
        "usedby",
        "open_relationship",
    }:
        return False
    if view.resource in {"authorization", "diagnostics"} and action in TABLE_ACTIONS - {
        "focus_filter",
        "focus_command",
        "history_back",
        "history_forward",
        "open_relationship",
    }:
        return False
    if view.resource == "pulse" and action in TABLE_ACTIONS - {
        "focus_filter",
        "focus_command",
        "history_back",
        "history_forward",
    }:
        return False
    if (
        view.resource in {"pulse", "relationships", "authorization", "diagnostics"}
        and action == "views"
    ):
        return False
    if action == "review_delete" and (view.generic or view.resource == "namespaces"):
        return False
    if action == "configuration_data" and (
        view.generic or view.resource not in {"configmaps", "secrets"}
    ):
        return False
    if action == "logs_all" and (view.generic or view.resource not in WORKLOAD_LOG_VIEWS):
        return False
    if action == "edit" and view.generic:
        return False
    if action == "port_forward" and view.resource not in {"pods", "services"}:
        return False
    if action in POD_ONLY and view.resource != "pods":
        return False
    if action in TABLE_ACTIONS:
        return not view.modal and not view.typing
    return True
