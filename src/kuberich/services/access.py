"""Fail-closed application policy; server-side RBAC remains authoritative."""

from dataclasses import dataclass
from enum import Enum, auto

from kuberich.errors import AppError


class Action(Enum):
    READ = auto()
    MUTATE = auto()
    EXEC = auto()
    ATTACH = auto()
    PORT_FORWARD = auto()
    PLUGIN = auto()


@dataclass(frozen=True)
class AccessPolicy:
    read_only: bool

    def __post_init__(self) -> None:
        if type(self.read_only) is not bool:
            raise AppError("Read-only policy must be true or false.")

    def require(self, action: Action) -> None:
        if not isinstance(action, Action):
            raise AppError("Unknown action policy; operation refused.")
        if self.read_only and action is not Action.READ:
            raise AppError(
                "Read-only mode blocks mutations, shell, attach, port-forward and external plugins."
            )
