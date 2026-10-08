"""One command decision path for initial CLI commands and interactive input."""

from dataclasses import dataclass
from enum import Enum, auto

from kubetrol.domain.connections import namespace_name
from kubetrol.domain.registry import RESOURCE_ALIASES, ResourceDefinition
from kubetrol.errors import AppError
from kubetrol.security.arguments import validate_argument
from kubetrol.services.access import AccessPolicy, Action


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
    UNAVAILABLE = auto()


_ACTIONS = {
    **dict.fromkeys(("exec", "shell", "ssh"), Action.EXEC),
    "attach": Action.ATTACH,
    "plugin": Action.PLUGIN,
    **dict.fromkeys(("delete", "edit", "scale", "rollout", "apply", "patch"), Action.MUTATE),
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
}


@dataclass(frozen=True)
class ScopedCommand:
    command: Command
    argument: str


@dataclass(frozen=True)
class ResourceCommand:
    definition: ResourceDefinition
    scope: str | None = None


ResolvedCommand = Command | ScopedCommand | ResourceCommand


def suggestions(
    text: str, contexts: tuple[str, ...], namespaces: tuple[str, ...]
) -> tuple[str, ...]:
    """Literal local candidates only; no regex, credentials or transport work."""
    text = text.removeprefix(":")
    verb, separator, prefix = text.partition(" ")
    if not separator:
        values = tuple(sorted(set(ALIASES) | set(RESOURCE_ALIASES)))
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
        else:
            return ()
        head = verb + " "
    candidates = sorted(
        set(head + value for value in values),
        # Preserve familiar :c → context and existing local command completions.
        key=lambda value: (not separator and value not in ALIASES, value.casefold(), value),
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

    def resolve(self, text: str) -> ResolvedCommand:
        text = text.strip().removeprefix(":").strip()
        if not text:
            return Command.EMPTY
        parts = text.split(maxsplit=1)
        verb = parts[0].lower()
        self.policy.require(_ACTIONS.get(verb, Action.READ))
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
        if command not in {Command.CONTEXTS, Command.NAMESPACES, Command.PODS}:
            return Command.UNAVAILABLE
        argument = parts[1]
        if command is Command.CONTEXTS:
            validate_argument(argument)
        elif argument != "*":
            namespace_name(argument)
        return ScopedCommand(command, argument)
