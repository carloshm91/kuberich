"""Mount real table widgets without a competing workspace data producer."""

from textual import on
from textual.app import App, ComposeResult
from textual.widgets import Static

from kuberich.domain.registry import RESOURCE_ALIASES
from kuberich.ui.app import KubeRichApp
from kuberich.ui.chrome import WorkspaceFrame
from kuberich.ui.pods import PodTable
from kuberich.ui.standard import StandardTable


class TableApp[T: PodTable | StandardTable](App[None]):
    CSS_PATH = KubeRichApp.CSS_PATH

    def __init__(self, table: T) -> None:
        super().__init__()
        self.table = self.resources = self.standard_table = table

    def compose(self) -> ComposeResult:
        with WorkspaceFrame(id="resource-view"):
            yield self.table
            yield Static(id="empty-state")

    def on_mount(self) -> None:
        if (
            isinstance(self.table, StandardTable)
            and self.table.definition != RESOURCE_ALIASES["deploy"]
        ):
            self.table.configure(RESOURCE_ALIASES["deploy"])
        else:
            self.table.setup()
        self.set_focus(self.table)

    @on(PodTable.SortChanged)
    @on(StandardTable.SortChanged)
    def show_sort(self) -> None:
        self.query_one(WorkspaceFrame).border_subtitle = self.table.sort_summary
