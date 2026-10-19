"""Which workspace actions apply to the current view (pure, Textual-free rules)."""

from dataclasses import dataclass

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
        "attach",
        "upload",
        "download",
        "port_forward",
        "review_delete",
    }
)


@dataclass(frozen=True)
class ViewState:
    resource: str
    generic: bool = False
    modal: bool = False
    typing: bool = False


def action_available(action: str, view: ViewState) -> bool:
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
