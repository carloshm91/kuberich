"""Owned HTTP/Git fixture for real release transport and immutable-byte trials."""

import hashlib
import json
import subprocess
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from scripts.release_policy import REPOSITORY


class ReleaseServer:
    def __init__(self, directory: Path):
        self.directory = directory
        self.git = directory / "git"
        self.git.mkdir(parents=True)
        self.command("init", "--bare", str(self.git))
        tree = self.command("mktree", input="").strip()
        self.sha = self.command(
            "-c",
            "user.name=Release Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit-tree",
            tree,
            "-m",
            "Owned release fixture",
        ).strip()
        self.reads = {}
        self.posts = []
        self.assets = {}
        self.release = None
        self.requests = []
        self.corrupt_upload = False
        self.fail_upload = None
        self.ref_barrier = None
        self.server = None

    def command(self, *args, input=None):
        return subprocess.run(
            ["git", "--git-dir", str(self.git), *args],
            input=input,
            text=True,
            capture_output=True,
            check=True,
            timeout=10,
        ).stdout

    def get(self, path):
        if path in self.reads:
            return self.reads[path]
        prefix = f"/repos/{REPOSITORY}"
        if path.startswith(prefix + "/git/ref/tags/"):
            name = path.split("/tags/", 1)[1]
            result = subprocess.run(
                [
                    "git",
                    "--git-dir",
                    str(self.git),
                    "show-ref",
                    "--verify",
                    "--hash",
                    f"refs/tags/{name}",
                ],
                text=True,
                capture_output=True,
                timeout=10,
            )
            if result.returncode:
                barrier = self.ref_barrier
                if barrier is not None:
                    barrier.wait(timeout=5)
                    self.ref_barrier = None
                return None
            sha = result.stdout.strip()
            return {"object": {"type": self.command("cat-file", "-t", sha).strip(), "sha": sha}}
        if path.startswith(prefix + "/git/tags/"):
            content = self.command("cat-file", "-p", path.rsplit("/", 1)[1])
            fields = dict(
                line.split(" ", 1) for line in content.split("\n\n", 1)[0].splitlines()[:3]
            )
            return {
                "tag": fields["tag"],
                "object": {"type": fields["type"], "sha": fields["object"], "url": "fixture"},
            }
        if path.startswith(prefix + "/releases/tags/"):
            return self.release
        if path.startswith(prefix + "/releases/1/assets"):
            return [
                {"name": name, "digest": "sha256:" + hashlib.sha256(data).hexdigest()}
                for name, data in self.assets.items()
            ]
        return None

    def post(self, path, body, content_type):
        self.posts.append((path, body))
        prefix = f"/repos/{REPOSITORY}"
        if content_type.startswith("application/octet-stream"):
            from urllib.parse import parse_qs, urlsplit

            name = parse_qs(urlsplit(path).query)["name"][0]
            if self.fail_upload == name:
                return 503, {"message": "owned transient failure"}
            if name in self.assets:
                return 422, {"message": "already exists"}
            self.assets[name] = body
            digest = "0" * 64 if self.corrupt_upload else hashlib.sha256(body).hexdigest()
            return 201, {"name": name, "digest": "sha256:" + digest}
        value = json.loads(body)
        if path == prefix + "/git/tags":
            text = (
                f"object {value['object']}\ntype commit\ntag {value['tag']}\n"
                "tagger Release Fixture <fixture@example.invalid> 1791370000 +0000\n\n"
                + value["message"]
            )
            sha = self.command("mktag", input=text).strip()
            return 201, {"sha": sha}
        if path == prefix + "/git/refs":
            try:
                self.command("update-ref", value["ref"], value["sha"], "0" * 40)
            except subprocess.CalledProcessError:
                return 422, {"message": "immutable reference already exists"}
            return 201, value
        if path == prefix + "/releases":
            self.release = {**value, "id": 1}
            return 201, self.release
        if path == prefix + "/releases/1":
            self.release.update(value)
            return 200, self.release
        return 404, {}


@contextmanager
def release_server(directory):
    fixture = ReleaseServer(directory)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def serve(self):
            fixture.requests.append((self.command, self.path, self.headers.get("Authorization")))
            if self.path == "/redirect":
                self.send_response(302)
                self.send_header("Location", fixture.url + "target")
                self.end_headers()
                return
            if self.path == "/denied":
                status, value = 403, {"secret": "must not be printed"}
            elif self.path == "/large":
                status, value = 200, {"data": "x" * (4 * 1024 * 1024)}
            elif self.command == "GET":
                value = fixture.get(self.path)
                status = 404 if value is None else 200
            else:
                body = self.rfile.read(int(self.headers["Content-Length"]))
                status, value = fixture.post(self.path, body, self.headers["Content-Type"])
            content = json.dumps(value).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        do_GET = serve
        do_POST = serve
        do_PATCH = serve

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    fixture.url = f"http://127.0.0.1:{server.server_port}/"
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        yield fixture
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive()
