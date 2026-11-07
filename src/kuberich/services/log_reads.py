"""An owned release handle for one bounded, synchronously observed log read."""

from collections.abc import Callable

from kuberich.domain.log_reads import LogReadState
from kuberich.domain.views import ViewObservation
from kuberich.domain.watches import WatchEvent


class LogReadLease:
    def __init__(
        self, state: LogReadState, current: Callable[[], bool], release: Callable[[], None]
    ) -> None:
        self.state = state
        self._current: Callable[[], bool] | None = current
        self._release: Callable[[], None] | None = release

    def read_current(self) -> bool:
        if self._current is None or not self._current():
            self.state.invalidate()
        return self.state.current

    def observe(self, view: ViewObservation, *, event: WatchEvent | None = None) -> None:
        if self.read_current():
            self.state.observe(view, event=event)

    def release(self) -> None:
        self.state.invalidate()
        self._current = None
        release, self._release = self._release, None
        if release is not None:
            release()
