"""Declarative local command metadata shared by parsing and terminal consumers."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum, auto
from types import MappingProxyType

from kuberich.domain.commands import Command
from kuberich.domain.view_actions import ViewState, action_available
from kuberich.errors import AppError
from kuberich.services.access import AccessPolicy, Action


class Capability(Enum):
    POD = auto()
    WORKLOAD = auto()
    RESOURCE = auto()
    CONTEXT = auto()
    SERVER_COLUMNS = auto()


@dataclass(frozen=True)
class CommandSpec:
    command: Command
    aliases: tuple[str, ...]
    handler: str
    help: str
    policy: Action = Action.READ
    capabilities: frozenset[Capability] = frozenset()
    ui_action: str | None = None
    generic_allowed: bool = True

    @property
    def read_only_allowed(self) -> bool:
        return self.policy is Action.READ


def _spec(
    command: Command,
    aliases: tuple[str, ...],
    help: str,
    *,
    policy: Action = Action.READ,
    capability: Capability | None = None,
    action: str | None = None,
    generic: bool = True,
) -> CommandSpec:
    return CommandSpec(
        command,
        aliases,
        command.name.lower(),
        help,
        policy,
        frozenset() if capability is None else frozenset({capability}),
        action,
        generic,
    )


COMMAND_SPECS = (
    _spec(Command.EMPTY, (), "Show current connection status."),
    _spec(Command.HELP, ("help", "?"), "Open keyboard and command help.", action="show_help"),
    _spec(
        Command.THEMES,
        ("themes", "theme"),
        "Preview themes and save appearance preferences.",
        action="change_theme",
    ),
    _spec(
        Command.ABOUT,
        ("about",),
        "Show the installed version and optional release notice.",
        action="about",
    ),
    _spec(
        Command.VIEWS,
        ("views",),
        "Configure and explicitly save resource columns and sorting.",
        action="views",
        capability=Capability.RESOURCE,
    ),
    _spec(Command.PLUGINS, ("plugins",), "Review configured plugin definitions."),
    _spec(Command.PLUGIN_JOBS, ("pluginjobs",), "Inspect and stop owned plugin jobs."),
    _spec(Command.QUIT, ("quit", "q", "exit"), "Close owned work and quit."),
    _spec(Command.PODS, ("po", "pod", "pods"), "List pods; optionally choose NAMESPACE or *."),
    _spec(
        Command.CONTEXTS,
        ("ctx", "context", "contexts"),
        "List local contexts; optionally select NAME.",
        action="contexts",
    ),
    _spec(
        Command.NAMESPACES,
        ("ns", "namespace", "namespaces"),
        "List namespaces; optionally select NAME or *.",
        action="namespaces",
    ),
    _spec(
        Command.STATUS, ("status",), "Inspect the current connection.", action="connection_details"
    ),
    _spec(Command.RETRY, ("retry",), "Reconnect the selected context.", action="retry"),
    _spec(
        Command.LOGIN,
        ("login",),
        "Explicitly run the credential login flow and reconnect.",
        action="login",
    ),
    _spec(
        Command.BACK, ("back",), "Return to the previous captured workspace.", action="history_back"
    ),
    _spec(
        Command.FORWARD,
        ("forward",),
        "Return to the next captured workspace.",
        action="history_forward",
    ),
    _spec(
        Command.SHELL,
        ("shell", "exec"),
        "Choose a pod container and open its shell.",
        policy=Action.EXEC,
        capability=Capability.POD,
        action="shell",
        generic=False,
    ),
    _spec(
        Command.ATTACH,
        ("attach",),
        "Attach to a selected pod container.",
        policy=Action.ATTACH,
        capability=Capability.POD,
        action="attach",
        generic=False,
    ),
    _spec(
        Command.UPLOAD,
        ("upload",),
        "Review uploading a file into a pod container.",
        policy=Action.MUTATE,
        capability=Capability.POD,
        action="upload",
        generic=False,
    ),
    _spec(
        Command.DOWNLOAD,
        ("download",),
        "Download a file from a pod container.",
        capability=Capability.POD,
        action="download",
        generic=False,
    ),
    _spec(
        Command.PORT_FORWARD,
        ("portforward",),
        "Review a pod or Service TCP port-forward.",
        policy=Action.PORT_FORWARD,
        capability=Capability.RESOURCE,
        action="port_forward",
        generic=False,
    ),
    _spec(
        Command.PORT_FORWARDS,
        ("pf", "portforwards"),
        "Inspect and stop owned port-forwards.",
        action="port_forwards",
    ),
    _spec(
        Command.ANNOTATE,
        ("annotate",),
        "Review a conditional annotation update.",
        policy=Action.MUTATE,
        capability=Capability.RESOURCE,
        action="annotate",
        generic=False,
    ),
    _spec(
        Command.EDIT,
        ("edit",),
        "Edit a captured resource through a reviewed draft.",
        policy=Action.MUTATE,
        capability=Capability.RESOURCE,
        action="edit",
        generic=False,
    ),
    _spec(Command.WRITES, ("writes",), "Inspect recorded mutation outcomes.", action="writes"),
    _spec(
        Command.SCALE,
        ("scale",),
        "Review a workload replica count.",
        policy=Action.MUTATE,
        capability=Capability.WORKLOAD,
        generic=False,
    ),
    _spec(
        Command.RESTART,
        ("restart",),
        "Review a workload rolling restart.",
        policy=Action.MUTATE,
        capability=Capability.WORKLOAD,
        generic=False,
    ),
    _spec(
        Command.ROLLBACK,
        ("rollback",),
        "Review a workload revision rollback.",
        policy=Action.MUTATE,
        capability=Capability.WORKLOAD,
        generic=False,
    ),
    _spec(
        Command.ROLLOUT,
        ("rollout",),
        "Inspect workload rollout status.",
        capability=Capability.WORKLOAD,
    ),
    _spec(
        Command.DELETE,
        ("delete",),
        "Review deleting the captured resource.",
        policy=Action.MUTATE,
        capability=Capability.RESOURCE,
        action="review_delete",
        generic=False,
    ),
    _spec(
        Command.DELETE_BATCH,
        ("deletebatch",),
        "Review deleting marked or visible resources.",
        policy=Action.MUTATE,
        capability=Capability.RESOURCE,
        generic=False,
    ),
    _spec(
        Command.TRIGGER,
        ("trigger",),
        "Review creating a Job from a CronJob.",
        policy=Action.MUTATE,
        capability=Capability.RESOURCE,
        generic=False,
    ),
    _spec(
        Command.SUSPEND,
        ("suspend",),
        "Review suspending a CronJob.",
        policy=Action.MUTATE,
        capability=Capability.RESOURCE,
        generic=False,
    ),
    _spec(
        Command.RESUME,
        ("resume",),
        "Review resuming a CronJob.",
        policy=Action.MUTATE,
        capability=Capability.RESOURCE,
        generic=False,
    ),
    _spec(Command.REFRESH, ("refresh",), "Refresh discovery on the current client."),
    _spec(
        Command.COLUMNS,
        ("columns",),
        "Show or configure server-printer column keys.",
        capability=Capability.SERVER_COLUMNS,
    ),
    _spec(
        Command.LOGS_ALL,
        ("logsall",),
        "Open bounded aggregate pod or workload logs.",
        capability=Capability.WORKLOAD,
        action="logs_all",
        generic=False,
    ),
    _spec(
        Command.RENAME,
        ("rename",),
        "Review renaming the selected local context.",
        policy=Action.MUTATE,
        capability=Capability.CONTEXT,
    ),
    _spec(
        Command.CLEANUP,
        ("cleanup",),
        "Review deleting completed and failed visible pods.",
        policy=Action.MUTATE,
        capability=Capability.POD,
        action="cleanup_pods",
    ),
    _spec(Command.JUMP, ("jump",), "Choose or open a configured resource jump."),
    _spec(Command.UNAVAILABLE, (), "Retain the current view and explain unavailable input."),
)

# These names retain fail-closed policy and alias reservations. They are not
# implemented commands and must never appear in help or completion as features.
RESERVED_ACTIONS = MappingProxyType(
    {"ssh": Action.EXEC, "apply": Action.MUTATE, "patch": Action.MUTATE, "plugin": Action.PLUGIN}
)


class CommandCatalog:
    def __init__(self, specs: tuple[CommandSpec, ...] = COMMAND_SPECS) -> None:
        commands = tuple(spec.command for spec in specs)
        if len(commands) != len(Command) or set(commands) != set(Command):
            raise AppError("The command catalog must declare every command exactly once.")
        aliases = tuple(alias for spec in specs for alias in spec.aliases)
        if len(set(aliases)) != len(aliases):
            raise AppError("Command aliases must have one declared owner.")
        if set(aliases) & RESERVED_ACTIONS.keys():
            raise AppError("Reserved operation names cannot become local command aliases.")
        if any(not spec.handler or not spec.help for spec in specs):
            raise AppError("Every command requires a handler and help text.")
        self.specs = specs
        self.by_command = MappingProxyType({spec.command: spec for spec in specs})
        self.aliases = MappingProxyType(
            {alias: spec.command for spec in specs for alias in spec.aliases}
        )

    def policy_for(self, verb: str) -> Action:
        verb = verb.lower()
        command = self.aliases.get(verb)
        return (
            self.by_command[command].policy
            if command is not None
            else RESERVED_ACTIONS.get(verb, Action.READ)
        )

    def available(self, action: str, view: ViewState) -> bool:
        # The existing pure view policy remains authoritative for binding
        # availability; read-only refusal stays in the shared access service.
        return action_available(action, view)

    def help_rows(self) -> tuple[tuple[str, str], ...]:
        return tuple((" / ".join(spec.aliases), spec.help) for spec in self.specs if spec.aliases)


COMMAND_CATALOG = CommandCatalog()


class BoundCommands:
    """Bind declared semantic handler IDs without resolving arbitrary attributes."""

    def __init__(
        self,
        policy: AccessPolicy,
        handlers: Mapping[str, Callable[[str | None], None]],
        catalog: CommandCatalog = COMMAND_CATALOG,
    ) -> None:
        self.policy, self.catalog = policy, catalog
        self.handlers = dict(handlers)

    def dispatch(self, command: Command, argument: str | None = None) -> None:
        spec = self.catalog.by_command[command]
        self.policy.require(spec.policy)
        self.handlers[spec.handler](argument)
