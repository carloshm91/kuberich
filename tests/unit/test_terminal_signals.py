"""Signal ownership must preserve host handlers and avoid repeated exit races."""

import signal

import pytest

from kubetrol.ui.shutdown import TERMINAL_SIGNALS, TerminalSignals


class App:
    def __init__(self):
        self.exits = []

    def exit(self, *, return_code):
        self.exits.append(return_code)


@pytest.mark.parametrize("signum,code", [(signal.SIGHUP, 129), (signal.SIGTERM, 143)])
def test_first_shutdown_signal_owns_exit_and_previous_handlers_restore(signum, code):
    previous = {value: signal.getsignal(value) for value in TERMINAL_SIGNALS}
    app = App()
    owner = TerminalSignals(app)
    try:
        owner.install()
        signal.getsignal(signum)(signum, None)
        signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
        signal.getsignal(signal.SIGHUP)(signal.SIGHUP, None)
        assert app.exits == [code]
    finally:
        owner.restore()
    assert {value: signal.getsignal(value) for value in TERMINAL_SIGNALS} == previous
    owner.restore()
    assert {value: signal.getsignal(value) for value in TERMINAL_SIGNALS} == previous


def test_partial_signal_installation_failure_restores_both_previous_handlers(monkeypatch):
    previous = {value: signal.getsignal(value) for value in TERMINAL_SIGNALS}
    app = App()
    owner = TerminalSignals(app)
    set_signal = signal.signal

    def fail_second_install(signum, handler):
        if signum == signal.SIGTERM and handler == owner.request:
            raise RuntimeError("owned fixture failure")
        return set_signal(signum, handler)

    monkeypatch.setattr(signal, "signal", fail_second_install)
    with pytest.raises(RuntimeError, match="owned fixture failure"):
        owner.install()
    assert not app.exits
    assert {value: signal.getsignal(value) for value in TERMINAL_SIGNALS} == previous
