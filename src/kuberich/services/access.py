"""Fail-closed application policy; server-side RBAC remains authoritative."""

from enum import Enum, auto

from kuberich.errors import AppError


class Action(Enum):
    READ = auto()
    MUTATE = auto()
    EXEC = auto()
    ATTACH = auto()
    PORT_FORWARD = auto()
    PLUGIN = auto()


class AccessPolicy:
    """One shared policy; a context or reload can tighten it, never lift the base."""

    __slots__ = ("_base", "_context")

    def __init__(self, read_only: bool) -> None:
        if type(read_only) is not bool:
            raise AppError("Read-only policy must be true or false.")
        self._base = read_only
        self._context = False

    @property
    def read_only(self) -> bool:
        return self._base or self._context

    def restrict(self, context_read_only: bool) -> None:
        """Apply the current context's setting; leaving that context restores the base."""
        if type(context_read_only) is not bool:
            raise AppError("Read-only policy must be true or false.")
        self._context = context_read_only

    def tighten(self) -> None:
        """Make the session read-only until it ends; nothing lifts this."""
        self._base = True

    def __repr__(self) -> str:
        return f"AccessPolicy(read_only={self.read_only})"

    def require(self, action: Action) -> None:
        if not isinstance(action, Action):
            raise AppError("Unknown action policy; operation refused.")
        if self.read_only and action is not Action.READ:
            raise AppError(
                "Read-only mode blocks mutations, shell, attach, port-forward and external plugins."
            )
