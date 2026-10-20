"""Keyboard help for the main workspace."""

from typing import TYPE_CHECKING, cast

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.widgets import Button, Static

from kuberich.ui.chrome import TEXT_SHORTCUTS, WorkspaceBars, WorkspaceFrame, WorkspaceHeader
from kuberich.ui.nested import CommandWorkspace
from kuberich.ui.text_navigation import ReadOnlyScroll

if TYPE_CHECKING:
    from kuberich.ui.app import KubeRichApp


class HelpScreen(CommandWorkspace):
    """Scrollable help keeps its close control accessible in small terminals."""

    AUTO_FOCUS = "#help-scroll"

    def __init__(self, navigation: str = "", aliases: str = "") -> None:
        super().__init__()
        self.navigation, self.aliases = navigation, aliases

    def compose(self) -> ComposeResult:
        yield WorkspaceHeader(
            cast("KubeRichApp", self.app).chrome, TEXT_SHORTCUTS, binding_profile="text"
        )
        with WorkspaceBars():
            mode = (
                "Read-only"
                if cast("KubeRichApp", self.app).commands.policy.read_only
                else "Read/write"
            )
            yield Static(
                f"Keyboard help · {mode} · j/k · g/G · : command",
                markup=False,
                classes="help-caption",
            )
            yield from self.command_bar()
        with WorkspaceFrame(id="help-dialog"):
            yield Static("Keyboard help", id="help-title", markup=False)
            with ReadOnlyScroll(id="help-scroll"):
                yield Static(
                    Text(
                        "/                 Focus filter\n"
                        ":                 Focus command\n"
                        "? or F1           Open help\n"
                        "c / F2            Contexts (:ctx)\n"
                        "n / F3            Namespaces (:ns)\n"
                        "r / F4            Retry connection (:retry)\n"
                        ":login            Explicit credential helper login and reconnect\n"
                        ":themes / :about  Appearance, preferences and version notice\n"
                        "i / F5            Connection status (:status)\n"
                        "Letter shortcuts work outside text inputs.\n"
                        "PageUp / PageDown Scroll help\n"
                        "Tab in command    Accept selected suggestion\n"
                        "Up / Down + Enter Select and submit suggestion\n"
                        "Tab / Shift+Tab   Move focus when no suggestion\n"
                        "Alt+Left / Right  Navigation back / forward\n"
                        "Escape            Back / leave input\n"
                        "Escape in table   Clear active filter\n"
                        "q / Ctrl+Q        Quit (q outside inputs)\n"
                        "Ctrl+C            Quit\n\n"
                        "Commands: po/pod/pods [NS or *], ctx [NAME], ns [NAME or *], "
                        "status, retry, login, back, forward, shell/exec, pf/portforwards, "
                        "portforward, annotate, edit (Shift+E), scale, restart, rollback, rollout, "
                        "delete, deletebatch, cleanup, jump [NAME], trigger, suspend, resume, writes, help, quit.\n"
                        "In :ctx, :rename NEW renames and Ctrl+D deletes the selected context.\n"
                        "Resources: deploy, rs, sts, ds, job, cj, svc, ep, ing, cm, sec, "
                        "no, pvc, pv, sc. Namespaced resources accept [NS or *].\n"
                        "Discovered: :resource NAME[.GROUP][/VERSION] [NS or *]. "
                        "Unique discovered aliases work directly; ambiguous names require a group.\n"
                        ":refresh renews discovery on the current client. "
                        ":columns shows server keys; :columns cN ... / default / none.\n"
                        "Generic resources are read-only; :views configures and explicitly saves columns/sort.\n"
                        "Filter: plain case-insensitive text; re:PATTERN for regex. "
                        "Searches namespace, name, readiness, status and restarts. "
                        "Invalid or timed-out regex shows all pods and an error.\n"
                        "Filters also accept !re:, fuzzy:, label: and allowlisted field:.\n"
                        "Alt+Up/Down recall commands/filters; :!! repeats through normal review.\n"
                        ":wide, :errors, :mark/:range/:selectall/:selectnone; :copy/:copyns/:copytext.\n"
                        ":favorites; :favorite add/remove NAMESPACE explicitly saves preferences.\n"
                        ":headless/:crumbsless/:fullscreen toggle session presentation.\n\n"
                        "Context sessions and live pod synchronization are available. "
                        "Pod rows, container logs and embedded shells are available.\n"
                        "l                 Selected pod logs (regular / init)\n"
                        "Shift+L / :logsall Aggregate Pod/workload logs (8 readers); c sources, s display filter, J plain/JSON.\n"
                        "Logs: / search, p pause, f follow, ? effective controls.\n"
                        "Enter             Pod containers → container logs\n"
                        "x / :shell        Choose a pod's container for its shell\n"
                        "Shift+F           Start pod/Service TCP port-forward\n"
                        ":pf               List owned forwards; s stops selected\n"
                        "Forwards survive view/namespace changes; context/retry/exit stops them.\n"
                        "Containers: s/x shell, a attach, u upload, d download, Enter/l logs, Esc pods.\n"
                        ":attach / :upload / :download choose a container first.\n"
                        "Shell: Ctrl+] return, Ctrl+C interrupt, Ctrl+Q quit.\n"
                        "d                 Resource details\n"
                        "y / e             YAML / related events\n"
                        "Viewer: m managedFields, / search, n/N matches, Ctrl+Y copy.\n"
                        "Header click      Sort / reverse column\n"
                        "Arrows / PageUp / PageDown navigate the table.\n\n"
                        + self.navigation
                        + "\n\n"
                        + self.aliases
                    ),
                    id="help-content",
                )
            yield Button("Back", id="close-help", variant="primary", compact=True)

    @on(Button.Pressed, "#close-help")
    def close_help(self) -> None:
        self.dismiss()
