"""One command decision path for initial CLI commands and interactive input."""

from dataclasses import dataclass
from enum import Enum, auto

from kubetrol.services.access import AccessPolicy, Action


class Command(Enum):
    EMPTY = auto()
    HELP = auto()
    QUIT = auto()
    UNAVAILABLE = auto()


_ACTIONS = {
    **dict.fromkeys(("exec", "shell", "ssh"), Action.EXEC),
    "attach": Action.ATTACH,
    "plugin": Action.PLUGIN,
    **dict.fromkeys(("delete", "edit", "scale", "rollout", "apply", "patch"), Action.MUTATE),
}


@dataclass(frozen=True)
class CommandService:
    policy: AccessPolicy

    def resolve(self, text: str) -> Command:
        command = text.strip().removeprefix(":").lower()
        if not command:
            return Command.EMPTY
        verb = command.split(maxsplit=1)[0]
        self.policy.require(_ACTIONS.get(verb, Action.READ))
        if command in {"help", "?"}:
            return Command.HELP
        if command in {"quit", "q", "exit"}:
            return Command.QUIT
        return Command.UNAVAILABLE
