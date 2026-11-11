"""A failed native wrapper still drains the real owned API and active handler."""

import http.client
import sys
import threading

import pytest

from tests.support import resource_creation_cli


def test_wrapper_failure_closes_listener_controller_and_active_watch_handler(tmp_path, monkeypatch):
    server = resource_creation_cli.CreationServer(hold=False)
    monkeypatch.setattr(resource_creation_cli, "CreationServer", lambda **kwargs: server)
    original_thread = threading.Thread
    owners = []

    def track(*args, **kwargs):
        owner = original_thread(*args, **kwargs)
        owners.append(owner)
        return owner

    monkeypatch.setattr(resource_creation_cli.threading, "Thread", track)
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=2)

    def broken_wrap(argv, environment):
        connection.request(
            "GET",
            "/api/v1/namespaces/team/pods?watch=1&resourceVersion=owned&timeoutSeconds=30",
            headers={"Authorization": "Bearer synthetic-pty"},
        )
        assert connection.getresponse().status == 200
        assert server.handler_threads and server.handler_threads[0].is_alive()
        raise ValueError("Owned wrapper refused before app launch")

    try:
        with pytest.raises(ValueError, match="wrapper refused"):
            resource_creation_cli.terminal_resource_creation_cli(
                [sys.executable, "-m", "kuberich"], tmp_path, "never-launched", wrap=broken_wrap
            )
        assert len(owners) == 2 and all(not owner.is_alive() for owner in owners)
        assert server.socket.fileno() == -1
    finally:
        connection.close()
