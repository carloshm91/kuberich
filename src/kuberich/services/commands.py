"""One command decision path for initial CLI commands and interactive input."""

from dataclasses import dataclass
from enum import Enum, auto

from kuberich.domain.connections import namespace_name
from kuberich.domain.registry import RESOURCE_ALIASES, ResourceDefinition
from kuberich.domain.resources import Discovery, api_segment
from kuberich.errors import AppError
from kuberich.security.arguments import validate_argument
from kuberich.services.access import AccessPolicy, Action


class Command(Enum):
    EMPTY = auto()
    HELP = auto()
    QUIT = auto()
    PODS = auto()
    CONTEXTS = auto()
    NAMESPACES = auto()
    STATUS = auto()
    RETRY = auto()
    LOGIN = auto()
    BACK = auto()
    FORWARD = auto()
    SHELL = auto()
    ATTACH = auto()
    UPLOAD = auto()
    DOWNLOAD = auto()
    PORT_FORWARD = auto()
    PORT_FORWARDS = auto()
    ANNOTATE = auto()
    EDIT = auto()
    WRITES = auto()
    SCALE = auto()
    RESTART = auto()
    ROLLBACK = auto()
    ROLLOUT = auto()
    DELETE = auto()
    DELETE_BATCH = auto()
    TRIGGER = auto()
    SUSPEND = auto()
    RESUME = auto()
    REFRESH = auto()
    COLUMNS = auto()
    LOGS_ALL = auto()
    UNAVAILABLE = auto()


_ACTIONS = {
    **dict.fromkeys(("exec", "shell", "ssh"), Action.EXEC),
    "attach": Action.ATTACH,
    "upload": Action.MUTATE,
    "plugin": Action.PLUGIN,
    "portforward": Action.PORT_FORWARD,
    "annotate": Action.MUTATE,
    **dict.fromkeys(
        (
            "delete",
            "deletebatch",
            "trigger",
            "suspend",
            "resume",
            "edit",
            "scale",
            "restart",
            "rollback",
            "apply",
            "patch",
        ),
        Action.MUTATE,
    ),
}

ALIASES = {
    **dict.fromkeys(("help", "?"), Command.HELP),
    **dict.fromkeys(("quit", "q", "exit"), Command.QUIT),
    **dict.fromkeys(("po", "pod", "pods"), Command.PODS),
    **dict.fromkeys(("ctx", "context", "contexts"), Command.CONTEXTS),
    **dict.fromkeys(("ns", "namespace", "namespaces"), Command.NAMESPACES),
    "status": Command.STATUS,
    "retry": Command.RETRY,
    "login": Command.LOGIN,
    "back": Command.BACK,
    "forward": Command.FORWARD,
    "shell": Command.SHELL,
    "exec": Command.SHELL,
    "attach": Command.ATTACH,
    "upload": Command.UPLOAD,
    "download": Command.DOWNLOAD,
    "pf": Command.PORT_FORWARDS,
    "portforwards": Command.PORT_FORWARDS,
    "portforward": Command.PORT_FORWARD,
    "annotate": Command.ANNOTATE,
    "edit": Command.EDIT,
    "writes": Command.WRITES,
    "scale": Command.SCALE,
    "restart": Command.RESTART,
    "rollback": Command.ROLLBACK,
    "rollout": Command.ROLLOUT,
    "delete": Command.DELETE,
    "deletebatch": Command.DELETE_BATCH,
    "trigger": Command.TRIGGER,
    "suspend": Command.SUSPEND,
    "resume": Command.RESUME,
    "refresh": Command.REFRESH,
    "columns": Command.COLUMNS,
    "logsall": Command.LOGS_ALL,
}


@dataclass(frozen=True)
class ScopedCommand:
    command: Command
    argument: str


@dataclass(frozen=True)
class ResourceCommand:
    definition: ResourceDefinition
    scope: str | None = None


@dataclass(frozen=True)
class GenericResourceCommand:
    name: str
    group: str | None = None
    version: str | None = None
    scope: str | None = None


def generic_command(text: str, discovery: Discovery | None = None) -> GenericResourceCommand:
    """resource[.group][/version] [namespace or *], with explicit GVR identity."""
    parts = text.split()
    if not 1 <= len(parts) <= 2:
        raise AppError("Use :resource NAME[.GROUP][/VERSION] [NAMESPACE or *].")
    name_group, slash, version = parts[0].partition("/")
    name, dot, group = name_group.partition(".")
    api_segment(name)
    if dot:
        api_segment(group)
    if slash:
        api_segment(version)
    scope = parts[1] if len(parts) == 2 else None
    if scope is not None and scope != "*":
        namespace_name(scope)
    command = GenericResourceCommand(
        name, ("" if group == "core" else group) if dot else None, version if slash else None, scope
    )
    if discovery is not None:
        resource = discovery.resolve(command.name, group=command.group, version=command.version)
        if scope is not None and not resource.namespaced:
            raise AppError("This resource is cluster-scoped; omit the namespace argument.")
        command = GenericResourceCommand(resource.name, resource.group, command.version, scope)
    return command


ResolvedCommand = Command | ScopedCommand | ResourceCommand | GenericResourceCommand


def resource_candidates(discovery: Discovery | None) -> tuple[str, ...]:
    if discovery is None:
        return ()
    candidates = set()
    canonical: dict[str, set[tuple[str, str]]] = {}
    aliases: dict[str, set[tuple[str, str]]] = {}
    for resource in discovery.resources:
        qualified = resource.name + "." + (resource.group or "core")
        candidates.add(qualified)
        candidates.add(qualified + "/" + resource.version)
        family = resource.group, resource.name
        canonical.setdefault(resource.name, set()).add(family)
        for alias in resource.aliases:
            aliases.setdefault(alias, set()).add(family)
    for name in canonical.keys() | aliases.keys():
        if len(canonical.get(name) or aliases[name]) == 1:
            candidates.add(name)
    return tuple(sorted(candidates))


def suggestions(
    text: str,
    contexts: tuple[str, ...],
    namespaces: tuple[str, ...],
    discovery: Discovery | None = None,
) -> tuple[str, ...]:
    """Literal local candidates only; no regex, credentials or transport work."""
    text = text.removeprefix(":")
    verb, separator, prefix = text.partition(" ")
    if not separator:
        values = tuple(
            sorted(
                set(ALIASES)
                | set(RESOURCE_ALIASES)
                | set(resource_candidates(discovery))
                | {"resource"}
            )
        )
        head = ""
        prefix = verb
    else:
        command = ALIASES.get(verb.lower())
        if command is Command.CONTEXTS:
            values = contexts
        elif command in {Command.NAMESPACES, Command.PODS} or (
            verb.lower() in RESOURCE_ALIASES and RESOURCE_ALIASES[verb.lower()].namespaced
        ):
            values = namespaces
        elif verb == "resource":
            values = resource_candidates(discovery)
        elif discovery is not None:
            try:
                resolved = generic_command(verb, discovery)
                resource = discovery.resolve(
                    resolved.name, group=resolved.group, version=resolved.version
                )
            except AppError:
                return ()
            if not resource.namespaced:
                return ()
            values = namespaces
        else:
            return ()
        head = verb + " "
    candidates = sorted(
        set(head + value for value in values),
        # Preserve familiar :c → context and existing local command completions.
        key=lambda value: (
            not separator and (value not in ALIASES or value == "columns"),
            not separator and ALIASES.get(value) in {Command.PORT_FORWARDS, Command.PORT_FORWARD},
            value.casefold(),
            value,
        ),
    )
    return tuple(
        value
        for value in candidates
        if len(value) <= 256
        and value[len(head) :].casefold().startswith(prefix.casefold())
        and value != text
    )[:8]


@dataclass(frozen=True)
class CommandService:
    policy: AccessPolicy

    def resolve(self, text: str, discovery: Discovery | None = None) -> ResolvedCommand:
        text = text.strip().removeprefix(":").strip()
        if not text:
            return Command.EMPTY
        parts = text.split(maxsplit=1)
        verb = parts[0].lower()
        self.policy.require(_ACTIONS.get(verb, Action.READ))
        if verb == "resource":
            return generic_command(parts[1] if len(parts) == 2 else "", discovery)
        if verb == "columns" and len(parts) == 2:
            return ScopedCommand(Command.COLUMNS, parts[1])
        if (
            verb not in ALIASES
            and verb not in RESOURCE_ALIASES
            and (discovery is not None or "." in verb or "/" in verb)
        ):
            # Ordinary unknown input need not be a Kubernetes reference. Keep
            # explicit :resource validation precise without routing arbitrary
            # markup/control text through the implicit resource grammar.
            try:
                api_segment(verb.partition(".")[0].partition("/")[0])
            except AppError:
                return Command.UNAVAILABLE
            return generic_command(text, discovery)
        definition = RESOURCE_ALIASES.get(verb)
        if definition is not None:
            if len(parts) == 1:
                return ResourceCommand(definition)
            if not definition.namespaced:
                raise AppError("This resource is cluster-scoped; omit the namespace argument.")
            if parts[1] != "*":
                namespace_name(parts[1])
            return ResourceCommand(definition, parts[1])
        command = ALIASES.get(verb, Command.UNAVAILABLE)
        if len(parts) == 1:
            return command
        if command not in {
            Command.CONTEXTS,
            Command.NAMESPACES,
            Command.PODS,
            Command.SCALE,
            Command.ROLLBACK,
        }:
            return Command.UNAVAILABLE
        argument = parts[1]
        if command is Command.CONTEXTS:
            validate_argument(argument)
        elif command in {Command.SCALE, Command.ROLLBACK}:
            from kuberich.domain.workloads import replica_count

            replica_count(argument)
        elif argument != "*":
            namespace_name(argument)
        return ScopedCommand(command, argument)
